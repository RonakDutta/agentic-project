# Synopsis alignment (branch `muse`, Eval-1)

This branch keeps every `mimo` pipeline working and adds the synopsis
Sec 9 stack as **optional, fallback-safe** layers so the viva diagram and
the code agree.

| Synopsis requirement | Where it now lives | Fallback when dep missing |
|---|---|---|
| LangGraph explicit graph (Fig 1) | `agents/graph.py`: real `StateGraph` whose nodes run the orchestrator steps (`classify -> codebase_pipeline / idea_pipeline -> finalize`) | sequential executor, same API |
| 6 canonical agents (Table 2) | `agents/synopsis_agents.py` | maps to existing specialists |
| Knowledge-base index (Sec 6.3) | `indexer/knowledge_base.py` | BM25/TF-IDF, offline |
| ChromaDB vector DB | `indexer/chroma_store.py` (adapter only; retrieval uses `VectorCodeIndex`) | existing `VectorCodeIndex` |
| SQLite sessions + eval logs | `agents/session_store.py` (`sessions.db`); every follow-up turn is saved and restored after restart | stdlib sqlite3, always on |
| GitPython history/blame | `tools/git_tools.py`; blame of each candidate goes into the diagnosis prompt | git-CLI, then unavailable marker |
| Ruff + Radon | `tools/lint_metrics.py`; radon rank goes into the diagnosis prompt (ruff wrapper exists, not yet used by an agent) | built-in `StaticCodeAnalyzer` |
| Tavily web search | `tools/search_tool.py` chain used by the Market agent (`TAVILY_API_KEY`) | `ddgs` DuckDuckGo, then Instant Answer, then labelled offline references |
| React + Vite + Tailwind UI | `web/react-app/` (calls same `/api/*`) | existing `web/templates/index.html` stays default |

New API (all read-only, same scope limits Sec 6.4):

- `GET /api/graph` — nodes/edges + active backend
- `POST /api/graph/run` — full pipeline via graph layer
- `GET /api/synopsis/agents` — canonical Table 2 catalog
- `GET /api/kb/lookup?q=` — curated knowledge-base hits
- `GET /api/session-store/{id}` — SQLite session

React dev: `cd web/react-app && npm install && npm run dev`
(proxies `/api` to FastAPI on 8000).
