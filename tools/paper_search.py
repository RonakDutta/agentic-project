"""
Scholarly paper search for the Prior-Art Research step.

Queries three free scholarly indexes in parallel and merges the results:
- arXiv API (export.arxiv.org, Atom XML, no key)
- Semantic Scholar Graph API (no key needed; SEMANTIC_SCHOLAR_API_KEY raises the limit)
- OpenAlex works API (no key needed; OPENALEX_API_KEY / OPENALEX_EMAIL raise the limit)

Every paper returned here came back from one of those APIs in this run (or from
the 7-day disk cache of an earlier real response). When every source is down,
the result is empty and says so; no placeholder papers are ever produced.
"""

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config import settings

logger = logging.getLogger(__name__)

ARXIV_URL = "https://export.arxiv.org/api/query"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_URL = "https://api.openalex.org/works"
_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_TIMEOUT = 12
_USER_AGENT = "agentic-copilot-prior-art/1.0 (academic project)"


@dataclass
class Paper:
    title: str
    authors: List[str]
    year: Optional[int]
    abstract: str
    url: str
    source: str  # "arxiv", "semantic_scholar" or "openalex"
    venue: str = ""
    citation_count: Optional[int] = None
    doi: str = ""
    arxiv_id: str = ""
    pdf_url: str = ""
    # Filled in by the Prior-Art agent
    ref_id: str = ""
    similarity: float = 0.0
    also_found_in: List[str] = field(default_factory=list)

    def key(self) -> str:
        return normalise_title(self.title)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PaperSearchResult:
    papers: List[Paper]
    queries: List[str]
    sources_ok: List[str]
    sources_failed: Dict[str, str]
    from_cache: bool = False

    @property
    def backend_label(self) -> str:
        if not self.sources_ok:
            return "unavailable"
        return " + ".join(self.sources_ok)


def normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# --------------------------------------------------------------------------- #
# Source adapters
# --------------------------------------------------------------------------- #

def arxiv_query_variants(query: str) -> List[str]:
    """
    arXiv's search ANDs every term, so a long title often matches nothing.
    Variants go from strict to loose: the first 3 terms together, then any two
    of the first 5 terms together (ranked by arXiv relevance, reranked later).
    """
    terms = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 2][:6]
    if not terms:
        return []
    variants = [" AND ".join(f"all:{t}" for t in terms[:3])]
    head = terms[:5]
    pairs = [f"(all:{a} AND all:{b})" for i, a in enumerate(head) for b in head[i + 1:]]
    if pairs:
        variants.append(" OR ".join(pairs))
    return variants


def search_arxiv(query: str, limit: int) -> List[Paper]:
    papers: List[Paper] = []
    seen = set()
    for search in arxiv_query_variants(query):
        for paper in _arxiv_request(search, limit):
            if paper.key() not in seen:
                seen.add(paper.key())
                papers.append(paper)
        if len(papers) >= max(3, limit // 2):
            break
    return papers[:limit]


def _arxiv_request(search: str, limit: int) -> List[Paper]:
    resp = requests.get(
        ARXIV_URL,
        params={"search_query": search, "max_results": limit, "sortBy": "relevance"},
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    papers: List[Paper] = []
    for entry in root.findall("a:entry", _ATOM):
        title = _clean(entry.findtext("a:title", "", _ATOM))
        if not title:
            continue
        abs_url = _clean(entry.findtext("a:id", "", _ATOM))
        arxiv_id = abs_url.rsplit("/abs/", 1)[-1] if "/abs/" in abs_url else ""
        published = entry.findtext("a:published", "", _ATOM) or ""
        doi = entry.findtext("arxiv:doi", "", _ATOM) or ""
        venue = entry.findtext("arxiv:journal_ref", "", _ATOM) or "arXiv preprint"
        pdf = next((l.get("href") for l in entry.findall("a:link", _ATOM) if l.get("title") == "pdf"), "") or ""
        papers.append(Paper(
            title=title,
            authors=[_clean(a.findtext("a:name", "", _ATOM)) for a in entry.findall("a:author", _ATOM)],
            year=int(published[:4]) if published[:4].isdigit() else None,
            abstract=_clean(entry.findtext("a:summary", "", _ATOM)),
            url=abs_url.replace("http://", "https://"),
            source="arxiv",
            venue=_clean(venue),
            doi=doi.strip(),
            arxiv_id=re.sub(r"v\d+$", "", arxiv_id),
            pdf_url=pdf.replace("http://", "https://"),
        ))
    return papers


def search_semantic_scholar(query: str, limit: int) -> List[Paper]:
    headers = {"User-Agent": _USER_AGENT}
    key = getattr(settings, "semantic_scholar_api_key", "")
    if key:
        headers["x-api-key"] = key
    resp = requests.get(
        S2_URL,
        params={
            "query": query,
            "limit": limit,
            "fields": "title,abstract,year,authors,venue,citationCount,externalIds,url,openAccessPdf",
        },
        headers=headers,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    papers: List[Paper] = []
    for item in resp.json().get("data") or []:
        title = _clean(item.get("title") or "")
        if not title:
            continue
        ext = item.get("externalIds") or {}
        papers.append(Paper(
            title=title,
            authors=[_clean(a.get("name") or "") for a in (item.get("authors") or [])],
            year=item.get("year"),
            abstract=_clean(item.get("abstract") or ""),
            url=item.get("url") or "",
            source="semantic_scholar",
            venue=_clean(item.get("venue") or ""),
            citation_count=item.get("citationCount"),
            doi=ext.get("DOI") or "",
            arxiv_id=ext.get("ArXiv") or "",
            pdf_url=(item.get("openAccessPdf") or {}).get("url") or "",
        ))
    return papers


def _openalex_abstract(inverted: Optional[Dict[str, List[int]]]) -> str:
    """OpenAlex ships abstracts as an inverted index {word: [positions]}."""
    if not inverted:
        return ""
    positions: List[Tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    return " ".join(w for _, w in sorted(positions))


def search_openalex(query: str, limit: int) -> List[Paper]:
    params: Dict[str, Any] = {
        "search": query,
        "per-page": limit,
        "select": "id,doi,title,publication_year,authorships,cited_by_count,abstract_inverted_index,primary_location",
    }
    if getattr(settings, "openalex_api_key", ""):
        params["api_key"] = settings.openalex_api_key
    if getattr(settings, "openalex_email", ""):
        params["mailto"] = settings.openalex_email
    resp = requests.get(OPENALEX_URL, params=params, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
    resp.raise_for_status()
    papers: List[Paper] = []
    for item in resp.json().get("results") or []:
        title = _clean(item.get("title") or "")
        if not title:
            continue
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        papers.append(Paper(
            title=title,
            authors=[
                _clean((a.get("author") or {}).get("display_name") or "")
                for a in (item.get("authorships") or [])
            ],
            year=item.get("publication_year"),
            abstract=_clean(_openalex_abstract(item.get("abstract_inverted_index"))),
            url=location.get("landing_page_url") or item.get("doi") or item.get("id") or "",
            source="openalex",
            venue=_clean(source.get("display_name") or ""),
            citation_count=item.get("cited_by_count"),
            doi=doi,
            pdf_url=location.get("pdf_url") or "",
        ))
    return papers


SOURCES = {
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
    "openalex": search_openalex,
}


# --------------------------------------------------------------------------- #
# Disk cache of real responses (keeps demos reproducible and polite to the APIs)
# --------------------------------------------------------------------------- #

class _PaperCache:
    def __init__(self, path: Path, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._conn = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute("CREATE TABLE IF NOT EXISTS papers (key TEXT PRIMARY KEY, expiry REAL, payload TEXT)")
            self._conn.commit()
        except Exception as err:  # pragma: no cover
            logger.info(f"[PaperSearch] cache disabled ({err})")
            self._conn = None

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute("SELECT expiry, payload FROM papers WHERE key=?", (key,)).fetchone()
        if not row or row[0] < time.time():
            return None
        return json.loads(row[1])

    def put(self, key: str, papers: List[Paper]) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO papers(key, expiry, payload) VALUES(?,?,?)",
                (key, time.time() + self.ttl, json.dumps([p.to_dict() for p in papers])),
            )
            self._conn.commit()


_cache: Optional[_PaperCache] = None
_cache_lock = threading.Lock()


def _get_cache() -> Optional[_PaperCache]:
    global _cache
    if not getattr(settings, "paper_cache_enabled", True):
        return None
    with _cache_lock:
        if _cache is None:
            _cache = _PaperCache(settings.root_dir / ".cache" / "papers.sqlite", 7 * 24 * 3600)
    return _cache


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def merge_papers(groups: List[List[Paper]]) -> List[Paper]:
    """Dedupes by normalised title; keeps the record with the most metadata."""
    merged: Dict[str, Paper] = {}
    for group in groups:
        for paper in group:
            key = paper.key()
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = paper
                continue
            if paper.source not in existing.also_found_in and paper.source != existing.source:
                existing.also_found_in.append(paper.source)
            if not existing.abstract and paper.abstract:
                existing.abstract = paper.abstract
            if existing.citation_count is None and paper.citation_count is not None:
                existing.citation_count = paper.citation_count
            existing.doi = existing.doi or paper.doi
            existing.arxiv_id = existing.arxiv_id or paper.arxiv_id
            existing.pdf_url = existing.pdf_url or paper.pdf_url
            if (not existing.venue or existing.venue == "arXiv preprint") and paper.venue:
                existing.venue = paper.venue
    return list(merged.values())


def search_papers(queries: List[str], per_source: int = 8) -> PaperSearchResult:
    """Runs every query on every source in parallel and merges the results."""
    queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
    cache = _get_cache()
    cache_key = hashlib.sha256(json.dumps([queries, per_source]).encode()).hexdigest()
    if cache is not None:
        cached = cache.get(cache_key)
        if cached:
            papers = [Paper(**p) for p in cached]
            return PaperSearchResult(
                papers=papers, queries=queries,
                sources_ok=sorted({p.source for p in papers} | {s for p in papers for s in p.also_found_in}),
                sources_failed={}, from_cache=True,
            )

    jobs = [(name, fn, q) for q in queries for name, fn in SOURCES.items()]
    groups: List[List[Paper]] = []
    ok: set = set()
    failed: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(jobs) or 1), thread_name_prefix="papers") as pool:
        futures = [(name, pool.submit(fn, q, per_source)) for name, fn, q in jobs]
        for name, fut in futures:
            try:
                result = fut.result(timeout=_TIMEOUT + 5)
                groups.append(result)
                ok.add(name)
            except Exception as err:
                msg = str(err)
                if "429" in msg:
                    msg = "rate limited (429)"
                failed.setdefault(name, msg[:120])
    for name in ok:
        failed.pop(name, None)
    papers = merge_papers(groups)
    if papers and cache is not None:
        cache.put(cache_key, papers)
    return PaperSearchResult(papers=papers, queries=queries, sources_ok=sorted(ok), sources_failed=failed)


# --------------------------------------------------------------------------- #
# Reference formatting (deterministic)
# --------------------------------------------------------------------------- #

def _ieee_author(name: str) -> str:
    parts = [p for p in name.replace(",", " ").split() if p]
    if len(parts) < 2:
        return name
    initials = " ".join(f"{p[0]}." for p in parts[:-1])
    return f"{initials} {parts[-1]}"


def ieee_reference(paper: Paper, number: int) -> str:
    authors = [_ieee_author(a) for a in paper.authors if a]
    if len(authors) > 3:
        author_text = f"{authors[0]} et al."
    elif len(authors) > 1:
        author_text = ", ".join(authors[:-1]) + ", and " + authors[-1]
    else:
        author_text = authors[0] if authors else "Anonymous"
    venue = paper.venue or ("arXiv preprint" if paper.source == "arxiv" else "")
    if paper.arxiv_id and (not paper.venue or paper.venue == "arXiv preprint"):
        venue = f"arXiv preprint arXiv:{paper.arxiv_id}"
    bits = [f"[{number}] {author_text}, \"{paper.title},\""]
    if venue:
        bits.append(f"{venue},")
    bits.append(f"{paper.year or 'n.d.'}.")
    if paper.doi:
        bits.append(f"doi: {paper.doi}.")
    elif paper.url:
        bits.append(f"[Online]. Available: {paper.url}")
    return " ".join(bits)


def bibtex_entry(paper: Paper) -> str:
    first = re.sub(r"[^A-Za-z]", "", (paper.authors[0].split()[-1] if paper.authors and paper.authors[0].split() else "anon"))
    word = next((w for w in re.findall(r"[A-Za-z]+", paper.title) if len(w) > 3), "paper")
    key = f"{first.lower()}{paper.year or ''}{word.lower()}"
    fields = {
        "title": "{" + paper.title + "}",
        "author": " and ".join(a for a in paper.authors if a) or "Anonymous",
        "year": str(paper.year or ""),
    }
    entry_type = "article"
    if paper.arxiv_id:
        entry_type = "misc"
        fields["eprint"] = paper.arxiv_id
        fields["archivePrefix"] = "arXiv"
    elif paper.venue:
        fields["journal"] = paper.venue
    if paper.doi:
        fields["doi"] = paper.doi
    if paper.url:
        fields["url"] = paper.url
    # The title keeps its own extra braces so BibTeX preserves its capitalisation.
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{entry_type}{{{key},\n{body}\n}}"
