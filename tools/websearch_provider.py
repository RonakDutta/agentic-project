"""Web-search provider (synopsis Sec 9): Tavily first, then DuckDuckGo.

The full chain now lives in `tools.search_tool.WebSearchTool` (Tavily ->
ddgs -> DuckDuckGo Instant Answer -> labelled offline references). This
module keeps the original import path working for existing callers.
"""

from typing import List

from tools.search_tool import SearchResultItem, WebSearchTool, web_search_tool


class WebSearchProvider:
    def __init__(self, timeout: int = 6):
        self.tool = WebSearchTool(timeout=timeout)

    def search(self, query: str, max_results: int = 4) -> List[SearchResultItem]:
        return self.tool.search(query, max_results=max_results)


web_search_provider = WebSearchProvider()

__all__ = ["WebSearchProvider", "web_search_provider", "web_search_tool"]
