"""Web-search provider abstraction: Tavily (synopsis) with DuckDuckGo fallback.

- If TAVILY_API_KEY is set and `requests` works, query Tavily first.
- Otherwise delegate to the existing resilient `WebSearchTool` (DDG + offline stubs).
Returns the same SearchResultItem list shape so agents need no changes.
"""

import logging
import os
from typing import List

import requests
from tools.search_tool import SearchResultItem, WebSearchTool

logger = logging.getLogger(__name__)


class WebSearchProvider:
    def __init__(self, timeout: int = 6):
        self.timeout = timeout
        self.fallback = WebSearchTool(timeout=timeout)

    def search(self, query: str, max_results: int = 4) -> List[SearchResultItem]:
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if api_key:
            try:
                resp = requests.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query,
                          "max_results": max_results, "include_answer": False},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = [SearchResultItem(title=r.get("title", query)[:140],
                                              snippet=r.get("content", "")[:400],
                                              url=r.get("url", ""),
                                              source="tavily")
                             for r in data.get("results", [])[:max_results]]
                    if items:
                        return items
            except Exception as err:
                logger.info(f"[websearch] tavily failed, DDG fallback ({err})")
        return self.fallback.search(query, max_results=max_results)


web_search_provider = WebSearchProvider()
