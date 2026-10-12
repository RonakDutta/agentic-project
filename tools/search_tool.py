"""
Resilient Web Search Tool.

Search chain, best first (each step only runs if the one before it found too little):
1. Tavily search API, when TAVILY_API_KEY is set (free tier, built for agents).
2. `ddgs` (DuckDuckGo/Bing/Brave metasearch, free, no key) when the package is installed.
3. DuckDuckGo Instant Answer API (Wikipedia-style abstracts; often empty for niche ideas).
4. Offline references: a few real, well-known products for common domains.

Every result carries its `source`, and `is_live` tells callers whether it came
from a live search. Offline references are never presented as search evidence:
the market agent and the scorecard only count live results as citations.
"""

import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

OFFLINE_SOURCE = "offline_reference"
LIVE_SOURCES = {"tavily", "ddgs", "duckduckgo_api"}


@dataclass
class SearchResultItem:
    title: str
    snippet: str
    url: str
    source: str = "web"

    @property
    def is_live(self) -> bool:
        return self.source in LIVE_SOURCES

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["is_live"] = self.is_live
        return data


# Domain keywords for the offline references, matched as whole words so "ai"
# does not fire on "email", "retail" or "train".
_IOT_RE = re.compile(r"\b(iot|sensors?|esp32|energy|smart meter|mqtt|lorawan|telemetry)\b", re.IGNORECASE)
_AI_CODE_RE = re.compile(r"\b(ai|llm|agents?|agentic|rag|code review|codebase|debugging)\b", re.IGNORECASE)


class WebSearchTool:
    def __init__(self, timeout: int = 6):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        # Last backend that produced results, for traces ("Tavily", "DuckDuckGo"...).
        self.last_backend = "none"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def search(self, query: str, max_results: int = 4, allow_offline: bool = True) -> List[SearchResultItem]:
        """Runs the search chain and returns at most max_results de-duplicated items."""
        results: List[SearchResultItem] = []
        self.last_backend = "none"

        for backend, fn in (
            ("Tavily", self._search_tavily),
            ("DuckDuckGo (ddgs)", self._search_ddgs),
            ("DuckDuckGo Instant Answer", self._search_ddg_instant),
        ):
            if len(results) >= max_results:
                break
            try:
                found = fn(query, max_results)
            except Exception as err:
                logger.info(f"[WebSearchTool] {backend} unavailable: {err}")
                found = []
            if found and self.last_backend == "none":
                self.last_backend = backend
            results = _merge(results, found)

        if not results and allow_offline:
            results = self._offline_references(query, count=max_results)
            if results:
                self.last_backend = "offline references (no live search reachable)"

        return results[:max_results]

    def search_many(self, queries: List[str], max_results: int = 5) -> List[SearchResultItem]:
        """Runs several queries, merges and de-duplicates by URL."""
        merged: List[SearchResultItem] = []
        backends = []
        for q in queries:
            if not q or len(merged) >= max_results:
                continue
            merged = _merge(merged, self.search(q, max_results=max_results, allow_offline=False))
            if self.last_backend != "none":
                backends.append(self.last_backend)
        if not merged:
            merged = self._offline_references(" ".join(queries), count=max_results)
            self.last_backend = "offline references (no live search reachable)" if merged else "none"
        else:
            self.last_backend = backends[0] if backends else "none"
        return merged[:max_results]

    # ------------------------------------------------------------------ #
    # Backends
    # ------------------------------------------------------------------ #

    def _search_tavily(self, query: str, max_results: int) -> List[SearchResultItem]:
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            return []
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results, "include_answer": False},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            return []
        return [
            SearchResultItem(
                title=(r.get("title") or query)[:140],
                snippet=(r.get("content") or "")[:400],
                url=r.get("url", ""),
                source="tavily",
            )
            for r in resp.json().get("results", [])[:max_results]
            if r.get("url")
        ]

    def _search_ddgs(self, query: str, max_results: int) -> List[SearchResultItem]:
        try:
            from ddgs import DDGS  # type: ignore
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # type: ignore  # older package name
            except ImportError:
                return []
        rows = DDGS(timeout=self.timeout).text(query, max_results=max_results) or []
        return [
            SearchResultItem(
                title=(r.get("title") or query)[:140],
                snippet=(r.get("body") or "")[:400],
                url=r.get("href") or r.get("url") or "",
                source="ddgs",
            )
            for r in rows
            if (r.get("href") or r.get("url"))
        ]

    def _search_ddg_instant(self, query: str, max_results: int) -> List[SearchResultItem]:
        encoded = urllib.parse.quote_plus(query)
        api_url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        response = requests.get(api_url, headers=self.headers, timeout=self.timeout)
        if response.status_code != 200:
            return []
        data = response.json()
        results: List[SearchResultItem] = []
        if data.get("AbstractText") and data.get("AbstractURL"):
            results.append(
                SearchResultItem(
                    title=data.get("Heading") or query,
                    snippet=data.get("AbstractText"),
                    url=data.get("AbstractURL"),
                    source="duckduckgo_api",
                )
            )
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
                text = topic["Text"]
                results.append(
                    SearchResultItem(
                        title=text[:60] + ("..." if len(text) > 60 else ""),
                        snippet=text,
                        url=topic["FirstURL"],
                        source="duckduckgo_api",
                    )
                )
            if len(results) >= max_results:
                break
        return results

    # ------------------------------------------------------------------ #
    # Offline references (clearly labelled, never counted as live evidence)
    # ------------------------------------------------------------------ #

    def _offline_references(self, query: str, count: int = 3) -> List[SearchResultItem]:
        if _IOT_RE.search(query):
            items = [
                SearchResultItem(
                    title="ThingsBoard Open-Source IoT Platform",
                    snippet="Device management, telemetry collection and real-time dashboards for IoT sensors.",
                    url="https://thingsboard.io",
                    source=OFFLINE_SOURCE,
                ),
                SearchResultItem(
                    title="Home Assistant Energy Management",
                    snippet="Open-source home automation with ESPHome, energy monitoring and consumption alerts.",
                    url="https://www.home-assistant.io/home-energy-management/",
                    source=OFFLINE_SOURCE,
                ),
                SearchResultItem(
                    title="AWS IoT Core",
                    snippet="Managed MQTT ingestion and device fleet management for connected sensors.",
                    url="https://aws.amazon.com/iot-core/",
                    source=OFFLINE_SOURCE,
                ),
            ]
        elif _AI_CODE_RE.search(query):
            items = [
                SearchResultItem(
                    title="AutoCodeRover: Autonomous Program Improvement",
                    snippet="NUS research using AST-aware context retrieval to localise bugs on SWE-bench.",
                    url="https://arxiv.org/abs/2404.05427",
                    source=OFFLINE_SOURCE,
                ),
                SearchResultItem(
                    title="CodeRabbit AI Code Review",
                    snippet="Commercial pull-request review assistant with repository context gathering.",
                    url="https://coderabbit.ai",
                    source=OFFLINE_SOURCE,
                ),
                SearchResultItem(
                    title="LangGraph",
                    snippet="Framework for stateful multi-agent workflows as explicit graphs.",
                    url="https://langchain-ai.github.io/langgraph/",
                    source=OFFLINE_SOURCE,
                ),
            ]
        else:
            # No honest generic reference exists: return nothing rather than invent one.
            items = []
        return items[:count]


def _merge(existing: List[SearchResultItem], new: List[SearchResultItem]) -> List[SearchResultItem]:
    seen = {_url_key(r.url) for r in existing}
    merged = list(existing)
    for item in new:
        key = _url_key(item.url)
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _url_key(url: str) -> str:
    return (url or "").strip().lower().rstrip("/").replace("://www.", "://")


# Global singleton instance
web_search_tool = WebSearchTool()
