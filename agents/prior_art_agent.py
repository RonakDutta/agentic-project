"""
Prior-Art Research Agent.

Checks a project idea against published research, so the report can say which
papers already do something similar, where they are stronger, and what is new.

Pipeline (one LLM call, everything else deterministic):
1. Search queries are built from the decomposed idea (no LLM).
2. arXiv + Semantic Scholar + OpenAlex are searched in parallel (tools/paper_search.py).
3. Papers are reranked by embedding similarity to the idea (MiniLM, TF-IDF fallback).
4. A novelty index and a 2D similarity map are computed from those embeddings.
5. One LLM call compares the idea with the top papers, using only their abstracts.
6. A deterministic critic drops comparisons that cite a paper that was not
   retrieved, removes out-of-range [n] citations from the Related Work text and
   measures how much of each claim is supported by the paper's own abstract.

IEEE references and BibTeX are formatted in code from the API metadata.
"""

import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.llm import llm_client, AGENT_MAX_TOKENS
from tools.paper_search import (
    Paper,
    PaperSearchResult,
    bibtex_entry,
    ieee_reference,
    search_papers,
)

logger = logging.getLogger(__name__)

TOP_FOR_REPORT = 8
TOP_FOR_LLM = 5
ABSTRACT_CHARS = 600

# Similarity bands for MiniLM cosine similarity between the idea and a paper.
# These are heuristic cut-offs, shown in the report as such.
BANDS = (
    (0.75, "Very close prior work exists"),
    (0.60, "Closely related work exists"),
    (0.45, "Related work exists, with room to differ"),
    (0.0, "Little directly related work found"),
)
# TF-IDF cosines run lower than MiniLM ones for the same pair of texts.
TFIDF_BANDS = ((0.35, BANDS[0][1]), (0.25, BANDS[1][1]), (0.15, BANDS[2][1]), (0.0, BANDS[3][1]))

_STOPWORDS = set(
    """a an and are as at be by can for from has have how in into is it its of on or that the this to
    using use used with without will which who what when where why their they them our your you we
    system systems platform app application tool tools based new real time real-time low cost low-cost
    detect detects detecting provide provides help helps allow allows user users feature features
    smart simple automated automatic ai mvp core build building built via each per also than more most
    like such data one two three daily current existing problem solution today across within make makes
    exact specific frustration bottleneck face gives product students student""".split()
)

PRIOR_ART_SYSTEM_PROMPT = """You are a Research Prior-Art Analyst.
You compare a project idea with research papers that were retrieved from arXiv, Semantic Scholar and OpenAlex.

Rules:
1. Use only what the given abstracts say. If an abstract does not state something, write "Not stated in the abstract".
2. Refer to papers only by the ref ids you are given (P1, P2, ...). Never mention a paper that is not in the list.
3. Be fair: say clearly where a paper is stronger than the idea (scale, rigour, evaluation, accuracy, theory).
4. In related_work, cite papers with IEEE numbers [1], [2], ... where [n] is the paper with ref Pn.

Return strict JSON:
{
  "comparisons": [
    {
      "ref": "P1",
      "what_it_does": "One sentence on what the paper does, from its abstract.",
      "overlap": "What the idea and the paper have in common.",
      "paper_is_stronger_at": "Where the paper is ahead of the idea.",
      "idea_adds": "What the idea does that the paper does not, or 'Nothing clear'.",
      "overlap_level": "high" or "medium" or "low"
    }
  ],
  "research_gap": "One or two sentences: the gap in this literature that the idea could fill.",
  "positioning": "Two or three sentences on how to position the project against this work.",
  "related_work": "An IEEE-style Related Work paragraph of 4 to 6 sentences citing [1], [2], ..."
}
"""


@dataclass
class PaperComparison:
    ref: str
    title: str
    what_it_does: str
    overlap: str
    paper_is_stronger_at: str
    idea_adds: str
    overlap_level: str
    abstract_support: float  # share of claim words found in the paper's abstract

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PriorArtReport:
    queries: List[str]
    search_backend: str
    sources_failed: Dict[str, str]
    similarity_backend: str
    papers: List[Paper]
    novelty_index: Optional[int]
    novelty_band: str
    closest_similarity: float
    evidence_confidence: str
    comparisons: List[PaperComparison]
    research_gap: str
    positioning: str
    related_work: str
    ieee_references: List[str]
    bibtex: str
    similarity_map: List[Dict[str, Any]]
    verification: Dict[str, Any]
    notes: List[str] = field(default_factory=list)
    generation_source: str = "llm"
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["papers"] = [p.to_dict() for p in self.papers]
        data["comparisons"] = [c.to_dict() for c in self.comparisons]
        return data

    def to_markdown(self) -> str:
        if not self.papers:
            return (
                "No research papers could be retrieved for this idea "
                f"(sources: {self.search_backend}). " + " ".join(self.notes)
            )
        lines = [
            f"**Novelty index**: {self.novelty_index}/100 ({self.novelty_band}), "
            f"closest paper similarity {self.closest_similarity:.2f} ({self.similarity_backend}). "
            f"Evidence confidence: {self.evidence_confidence}.",
            f"**Searched**: {self.search_backend} with queries: " + "; ".join(f"`{q}`" for q in self.queries),
            "",
            "**Closest papers**:",
        ]
        for i, p in enumerate(self.papers, start=1):
            lines.append(f"- [{i}] *{p.title}* ({p.year or 'n.d.'}), similarity {p.similarity:.2f}. {p.url}")
        if self.comparisons:
            lines += ["", "**Head-to-head comparison**:"]
            for c in self.comparisons:
                lines.append(
                    f"- **{c.ref}: {c.title}**. Does: {c.what_it_does} Overlap ({c.overlap_level}): {c.overlap} "
                    f"Paper is stronger at: {c.paper_is_stronger_at} Our idea adds: {c.idea_adds}"
                )
        if self.research_gap:
            lines += ["", f"**Research gap**: {self.research_gap}"]
        if self.positioning:
            lines += ["", f"**Positioning**: {self.positioning}"]
        if self.related_work:
            lines += ["", "**Related Work (draft, IEEE style)**:", "", self.related_work]
        lines += ["", "**References**:"] + [f"{r}" for r in self.ieee_references]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Deterministic helpers
# --------------------------------------------------------------------------- #

def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]+", (text or "").lower()) if w not in _STOPWORDS and len(w) > 2]


def build_queries(idea: Any) -> List[str]:
    """Two short keyword queries from the idea (title, then the most repeated domain terms)."""
    title = re.sub(r"[^A-Za-z0-9 ]+", " ", getattr(idea, "project_title", "") or "")
    title_terms = [w for w in title.split() if w.lower() not in _STOPWORDS and len(w) > 2]
    body = " ".join([
        getattr(idea, "raw_idea", "") or "",
        getattr(idea, "problem_statement", "") or "",
        getattr(idea, "core_value_prop", "") or "",
        " ".join(getattr(idea, "mvp_features", []) or []),
    ])
    counts = Counter(_words(body))
    # Words in the raw idea count double: the user chose them.
    for w in _words(getattr(idea, "raw_idea", "") or ""):
        counts[w] += 1
    top = [w for w, _ in counts.most_common(12)]
    queries = []
    if len(title_terms) >= 2:
        queries.append(" ".join(title_terms[:7]))
    if top:
        queries.append(" ".join(top[:6]))
    if not queries:
        raw = " ".join(_words(getattr(idea, "raw_idea", "") or ""))[:120]
        if raw:
            queries.append(raw)
    return queries


def idea_text(idea: Any) -> str:
    return " ".join([
        getattr(idea, "project_title", "") or "",
        getattr(idea, "raw_idea", "") or "",
        getattr(idea, "problem_statement", "") or "",
        getattr(idea, "core_value_prop", "") or "",
        " ".join(getattr(idea, "mvp_features", []) or []),
    ]).strip()


def embed_texts(texts: List[str]) -> Tuple[np.ndarray, str]:
    """Row-normalised embeddings, MiniLM when it can be loaded, else TF-IDF."""
    from indexer.vector_search import get_embedding_model, EMBEDDING_MODEL_NAME

    model = get_embedding_model()
    if model is not None:
        try:
            vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1e-10
            return vecs / norms, f"MiniLM ({EMBEDDING_MODEL_NAME})"
        except Exception as err:  # pragma: no cover
            logger.warning(f"[PriorArt] MiniLM encode failed ({err}); using TF-IDF.")
    from sklearn.feature_extraction.text import TfidfVectorizer

    matrix = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english").fit_transform(texts)
    vecs = matrix.toarray()
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1e-10
    return vecs / norms, "TF-IDF"


def novelty_from_similarities(sims: List[float], backend: str) -> Tuple[Optional[int], str]:
    """
    Novelty index = 100 x (1 - (0.6 x closest + 0.4 x mean of top 3)).
    It falls when one paper is very close or when several papers are close.
    """
    if not sims:
        return None, "Not computed (no papers retrieved)"
    ordered = sorted(sims, reverse=True)
    closest = ordered[0]
    top3 = ordered[:3]
    blended = 0.6 * closest + 0.4 * (sum(top3) / len(top3))
    index = int(round(100 * max(0.0, min(1.0, 1.0 - blended))))
    bands = TFIDF_BANDS if backend == "TF-IDF" else BANDS
    band = next(label for cut, label in bands if closest >= cut)
    return index, band


def similarity_map(vectors: np.ndarray, labels: List[str], sims: List[float]) -> List[Dict[str, Any]]:
    """2D PCA projection of the idea (row 0) and the papers, scaled to 0..1."""
    if vectors.shape[0] < 3:
        return []
    centred = vectors - vectors.mean(axis=0, keepdims=True)
    try:
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:  # pragma: no cover
        return []
    coords = centred @ vt[:2].T
    mins, maxs = coords.min(axis=0), coords.max(axis=0)
    span = np.where(maxs - mins == 0, 1.0, maxs - mins)
    scaled = (coords - mins) / span
    points = []
    for i, (x, y) in enumerate(scaled.tolist()):
        points.append({
            "label": labels[i],
            "x": round(float(x), 4),
            "y": round(float(y), 4),
            "is_idea": i == 0,
            "similarity": 1.0 if i == 0 else round(float(sims[i - 1]), 3),
        })
    return points


def support_ratio(claim: str, abstract: str) -> float:
    """Share of a claim's content words that appear in the paper's abstract (or title)."""
    claim_words = set(_words(claim))
    if not claim_words:
        return 0.0
    abstract_words = set(_words(abstract))
    stems = {w[:6] for w in abstract_words}
    hits = sum(1 for w in claim_words if w in abstract_words or w[:6] in stems)
    return round(hits / len(claim_words), 2)


_CITE_RE = re.compile(r"\[(\d+(?:\s*[,–\-]\s*\d+)*)\]")


def clean_citations(text: str, max_ref: int) -> Tuple[str, int, List[int]]:
    """Removes [n] citations that point outside 1..max_ref. Returns (text, removed, cited)."""
    removed = 0
    cited: List[int] = []

    def fix(match: "re.Match[str]") -> str:
        nonlocal removed
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        keep = [n for n in nums if 1 <= n <= max_ref]
        removed += len(nums) - len(keep)
        cited.extend(keep)
        return "[" + "], [".join(str(n) for n in keep) + "]" if keep else ""

    cleaned = _CITE_RE.sub(fix, text or "")
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    return cleaned.strip(), removed, sorted(set(cited))


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #

class PriorArtAgent:
    def __init__(self, searcher=search_papers):
        self.llm = llm_client
        self.searcher = searcher

    def research(self, idea: Any) -> PriorArtReport:
        queries = build_queries(idea)
        notes: List[str] = []
        try:
            search: PaperSearchResult = self.searcher(queries)
        except Exception as err:
            logger.warning(f"[PriorArt] paper search failed: {err}")
            search = PaperSearchResult(papers=[], queries=queries, sources_ok=[], sources_failed={"all": str(err)[:120]})
        if search.from_cache:
            notes.append("Paper search results came from the 7-day cache of an earlier live search.")
        for source, reason in search.sources_failed.items():
            notes.append(f"{source} was not reachable ({reason}).")

        papers = [p for p in search.papers if p.title]
        if not papers:
            return self._empty(queries, search, notes)

        # Rerank by similarity to the idea.
        texts = [idea_text(idea)] + [f"{p.title}. {p.abstract[:1500]}" for p in papers]
        vectors, backend = embed_texts(texts)
        sims = (vectors[1:] @ vectors[0]).tolist()
        for paper, sim in zip(papers, sims):
            paper.similarity = round(float(sim), 3)
        order = sorted(range(len(papers)), key=lambda i: papers[i].similarity, reverse=True)[:TOP_FOR_REPORT]
        top = [papers[i] for i in order]
        for n, paper in enumerate(top, start=1):
            paper.ref_id = f"P{n}"
        top_vectors = np.vstack([vectors[0:1]] + [vectors[i + 1:i + 2] for i in order])

        novelty, band = novelty_from_similarities([p.similarity for p in top], backend)
        with_abstract = sum(1 for p in top if p.abstract)
        if len(top) >= 6 and len(search.sources_ok) >= 2 and with_abstract >= 4:
            confidence = "High"
        elif len(top) >= 3 and with_abstract >= 2:
            confidence = "Medium"
        else:
            confidence = "Low"
            notes.append("Few papers with abstracts were found, so the novelty index is a rough signal.")
        if backend == "TF-IDF":
            notes.append("MiniLM was unavailable, so similarity used TF-IDF; scores run lower than with MiniLM.")

        comparisons, gap, positioning, related, verification, source, reason = self._compare(idea, top)

        return PriorArtReport(
            queries=queries,
            search_backend=search.backend_label,
            sources_failed=search.sources_failed,
            similarity_backend=backend,
            papers=top,
            novelty_index=novelty,
            novelty_band=band,
            closest_similarity=top[0].similarity,
            evidence_confidence=confidence,
            comparisons=comparisons,
            research_gap=gap,
            positioning=positioning,
            related_work=related,
            ieee_references=[ieee_reference(p, n) for n, p in enumerate(top, start=1)],
            bibtex="\n\n".join(bibtex_entry(p) for p in top),
            similarity_map=similarity_map(top_vectors, ["Your idea"] + [p.ref_id for p in top], [p.similarity for p in top]),
            verification=verification,
            notes=notes,
            generation_source=source,
            fallback_reason=reason,
        )

    def _empty(self, queries: List[str], search: PaperSearchResult, notes: List[str]) -> PriorArtReport:
        notes.append("No papers were retrieved, so no novelty index was computed. Nothing was invented in their place.")
        return PriorArtReport(
            queries=queries, search_backend=search.backend_label, sources_failed=search.sources_failed,
            similarity_backend="none", papers=[], novelty_index=None,
            novelty_band="Not computed (no papers retrieved)", closest_similarity=0.0,
            evidence_confidence="Low", comparisons=[], research_gap="", positioning="", related_work="",
            ieee_references=[], bibtex="", similarity_map=[],
            verification={"comparisons_kept": 0, "comparisons_returned": 0, "invalid_refs_dropped": 0,
                          "citations_removed": 0, "papers_cited_in_related_work": 0, "avg_abstract_support": 0.0},
            notes=notes, generation_source="fallback", fallback_reason="No papers retrieved",
        )

    def _compare(self, idea: Any, top: List[Paper]):
        """One LLM call over the top papers, then deterministic grounding checks."""
        llm_papers = top[:TOP_FOR_LLM]
        listing = "\n\n".join(
            f"{p.ref_id}: \"{p.title}\" ({p.year or 'n.d.'}, {p.venue or p.source})\n"
            f"Abstract: {(p.abstract or 'No abstract available.')[:ABSTRACT_CHARS]}"
            for p in llm_papers
        )
        user_prompt = (
            f"Project idea: {getattr(idea, 'project_title', '')}\n"
            f"Problem: {getattr(idea, 'problem_statement', '')}\n"
            f"Value proposition: {getattr(idea, 'core_value_prop', '')}\n"
            f"MVP features: {'; '.join(getattr(idea, 'mvp_features', []) or [])}\n\n"
            f"Retrieved papers (ref ids {', '.join(p.ref_id for p in llm_papers)}):\n{listing}\n\n"
            "Compare the idea with each paper and return the JSON."
        )
        by_ref = {p.ref_id: p for p in llm_papers}
        try:
            data = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": PRIOR_ART_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=AGENT_MAX_TOKENS["prior_art"],
            )
        except Exception as err:
            logger.info(f"[PriorArt] comparison LLM unavailable ({err}).")
            return self._fallback_comparisons(idea, llm_papers, str(err)[:160])

        raw = data.get("comparisons") if isinstance(data.get("comparisons"), list) else []
        comparisons: List[PaperComparison] = []
        dropped = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref") or "").strip().upper()
            paper = by_ref.get(ref)
            if paper is None or any(c.ref == ref for c in comparisons):
                dropped += 1
                continue
            what = str(item.get("what_it_does") or "Not stated in the abstract")
            level = str(item.get("overlap_level") or "medium").lower()
            comparisons.append(PaperComparison(
                ref=ref,
                title=paper.title,
                what_it_does=what,
                overlap=str(item.get("overlap") or ""),
                paper_is_stronger_at=str(item.get("paper_is_stronger_at") or "Not stated in the abstract"),
                idea_adds=str(item.get("idea_adds") or "Nothing clear"),
                overlap_level=level if level in ("high", "medium", "low") else "medium",
                abstract_support=support_ratio(what, f"{paper.title} {paper.abstract}"),
            ))
        comparisons.sort(key=lambda c: int(c.ref[1:]))

        related, removed, cited = clean_citations(str(data.get("related_work") or ""), len(top))
        supports = [c.abstract_support for c in comparisons]
        verification = {
            "comparisons_returned": len(raw),
            "comparisons_kept": len(comparisons),
            "invalid_refs_dropped": dropped,
            "citations_removed": removed,
            "papers_cited_in_related_work": len(cited),
            "avg_abstract_support": round(sum(supports) / len(supports), 2) if supports else 0.0,
            "weakly_supported": [c.ref for c in comparisons if c.abstract_support < 0.3],
        }
        if not comparisons:
            fallback = self._fallback_comparisons(idea, llm_papers, "LLM reply had no usable comparisons")
            return fallback[0], fallback[1], fallback[2], related or fallback[3], {**fallback[4], **verification}, "fallback", fallback[6]
        return (
            comparisons,
            str(data.get("research_gap") or ""),
            str(data.get("positioning") or ""),
            related,
            verification,
            "llm",
            "",
        )

    @staticmethod
    def _fallback_comparisons(idea: Any, papers: List[Paper], reason: str):
        """Without the LLM: shared key terms only. No claims about strengths are made up."""
        idea_words = set(_words(idea_text(idea)))
        comparisons = []
        for p in papers:
            shared = sorted(idea_words & set(_words(f"{p.title} {p.abstract}")))[:8]
            level = "high" if p.similarity >= 0.6 else "medium" if p.similarity >= 0.45 else "low"
            comparisons.append(PaperComparison(
                ref=p.ref_id, title=p.title,
                what_it_does=(p.abstract.split(". ")[0][:240] if p.abstract else "No abstract available."),
                overlap=("Shared terms: " + ", ".join(shared)) if shared else "No shared key terms.",
                paper_is_stronger_at="Not assessed (LLM unavailable).",
                idea_adds="Not assessed (LLM unavailable).",
                overlap_level=level,
                abstract_support=1.0 if p.abstract else 0.0,
            ))
        verification = {
            "comparisons_returned": 0, "comparisons_kept": len(comparisons), "invalid_refs_dropped": 0,
            "citations_removed": 0, "papers_cited_in_related_work": 0, "avg_abstract_support": 1.0,
            "weakly_supported": [],
        }
        return comparisons, "", "", "", verification, "fallback", reason


prior_art_agent = PriorArtAgent()
