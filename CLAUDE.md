# CLAUDE.md

Working notes for Claude sessions on this repo. Read this first, then `README.md`.

## What this project is

B.Tech minor project (GGSIPU USAR): a multi-agent "AI Co-Pilot" with two pillars.
- **Idea validation:** decompose -> market/web search -> kill agent -> reconciler -> deterministic scorecard -> PRD (+ Mermaid) -> roadmap. 13-section report.
- **Codebase diagnosis (read-only):** AST index -> hybrid retrieval (BM25 + MiniLM/TF-IDF, RRF) -> diagnosis (Groq) -> deterministic critic -> one critic-driven revision.

The goal is to impress teachers and evaluators in a viva, so every claim the UI or README makes must be true and checkable. Never add hard-coded "results", fake citations or invented fixes. When something is a fallback, label it.

Stack: FastAPI (`app.py`), Groq free tier (`core/llm.py`), LangGraph (`agents/graph.py`), SQLite (sessions, LLM cache, usage ledger). The UI served at `/` is still the legacy `web/templates/index.html` (Tailwind/Mermaid from CDNs). `web/react-app/` is a Vite port that is **not served yet** (dev server only, proxies `/api`).

## Commands

```bash
pip install -r requirements.txt
python app.py                                # http://127.0.0.1:8000
pytest -q                                    # 88 pass, 3 live-Groq smoke tests skip without GROQ_API_KEY
python evaluation/compare_baseline.py        # naive vs AST chunking (computed)
python evaluation/retrieval_benchmark.py     # BM25 / vector / hybrid Top-1, Top-3, MRR
python evaluation/free_tier_budget.py        # token plan vs Groq free-tier limits (no quota used)
```

`tests/conftest.py` disables the disk cache, the usage ledger and the run limiter, and points sessions at a temp DB. Keep tests hermetic: no network, no key.

## Map of the code

- `core/config.py`: all settings (env vars). Default models live in `DEFAULT_*_MODEL`. Free-tier limits: `FREE_TIER_RPM/RPD/TPM/TPD`.
- `core/llm.py`: Groq client. Model chain rotation, header-aware budgets, local `_UsageLedger` (RPM/TPM windows + daily totals), reasoning kwargs per model family, `<think>` stripping, memory + SQLite cache, `force_offline()` (thread-local) context manager, `AGENT_MAX_TOKENS` per agent.
- `agents/orchestrator.py`: `process()` = `new_state` -> `classify` -> `execute_track` -> `finalize` (these are the LangGraph nodes). Idea pipeline runs the roadmap on a worker thread. `_run_step` re-runs a crashed step with `force_offline()`.
- `agents/*_agent.py`: each result dataclass has `generation_source` ("llm"/"fallback") + `fallback_reason`.
- `agents/feasibility_scorecard.py`: deterministic rubric; only live citations count; `evidence_confidence`; verdict reconciled with the Reconciler.
- `agents/critic_agent.py`: file/symbol/line checks, retrieved-evidence check, quoted-code-vs-disk check (replaces invented code), `ast.parse` on fixes; per-candidate `verification` dict.
- `agents/diagnosis_agent.py`: line-numbered prompt, `feedback=` for static notes and critic revision, safe int parsing, honest fallback (no invented code).
- `agents/conversation_session.py`: follow-up engine + `SessionManager` (LRU + TTL, SQLite persistence, GitHub URL -> local clone).
- `indexer/index_cache.py`: per-repo cache of `CodebaseIndex` + `HybridRetriever`, keyed by file size/mtime.
- `indexer/vector_search.py`: MiniLM loaded once per process; failure remembered.
- `tools/search_tool.py`: Tavily -> `ddgs` -> DDG Instant Answer -> labelled offline references. `SearchResultItem.is_live`.
- `indexer/github_ingest.py`: shallow clone, `GIT_TERMINAL_PROMPT=0`, size limit, evicted clones deleted.

## Conventions (keep these)

1. **Provenance:** any new agent output gets `generation_source` and shows up in `final_output["provenance"]`. Fallback trace steps use `status="warning"`.
2. **Free-tier budget:** a new LLM call needs an entry in `AGENT_MAX_TOKENS` sized to its schema, and `python evaluation/free_tier_budget.py` must still show an idea run under the pooled TPM (currently ~12.8k of 24k). Prefer deterministic code over another LLM call. Do not route to `llama-3.1-8b-instant`: it is reportedly no longer on the free tier (Aug 2026).
3. **Honest evaluation:** benchmark scripts compute everything they print. Report bad numbers as they are.
4. **UI storyboard:** the current UI shows trace steps whose `details` have `thinking` or `findings`, mapped onto 4 nodes per track. Extra steps should keep their data under other keys (see the scorecard step's `rubric`/`notes`) until the Phase 2 UI rewrite.
5. **Plain language:** prompts get `PLAIN_LANGUAGE_RULES`; no em dashes in user-facing text.
6. Endpoints that run agents are sync `def` (FastAPI thread pool). Don't make them `async def` unless the work is truly async.

## Status

### Phase 1: backend fixes (done, branch `claude/affectionate-pascal-7eby9a`)
- LLM: 30s timeout, reasoning params (gpt-oss low / qwen hidden), `<think>` stripping, no double retry in `generate_json`, wrong model ids parked 1h, retry hints parse `14m22s`, thread-safe state, SQLite cache, local free-tier ledger, per-agent `max_tokens` (idea run reserves ~12.8k instead of ~20k).
- Search: real search chain, whole-word offline references, live vs offline labelled, multiple queries.
- Idea: provenance everywhere, label normalisation, null-safe parsing, step guards, roadmap in parallel, section 12 computed, idea-specific Mermaid with escaped labels, scorecard counts live citations only, resource score from the real stack, evidence confidence, verdict conflict rule, roadmap no longer asks the LLM for a second score.
- Code: line-numbered prompts, critic gets retrieved chunks, quote-vs-disk check, fix compile check, real revision with feedback, whole-identifier symbol matching, BM25 camelCase fix, MiniLM loaded once, index/retriever cache, static analysis + radon + git blame in the prompt, honest fallback, `radon` rank bug fixed, AST module-header and class-chunk truncation bugs fixed (100% of chunks now parse).
- Server: sync endpoints, `ALLOWED_REPO_ROOTS`, per-client `RUNS_PER_MINUTE`, health shows free-tier usage, GitHub follow-ups use the local clone, bounded + persisted sessions, clone cleanup and size cap.
- LangGraph graph now runs the real pipeline; evaluation scripts compute real numbers; README/.env.example/synopsis doc updated; `tests/test_backend_fixes.py` (31 regression tests).

### Next phases (from the plan agreed with the user)
2. **UI rebuild:** build `web/react-app` and serve `dist/` from FastAPI (drop CDN dependency); stream progress over SSE from real trace events (today the UI waits for the full response, then replays steps with fake 600ms delays); live agent graph (React Flow) with per-call model/tokens/latency from `llm_client.recent_calls`; show provenance/fallback badges, evidence confidence, critic `verification` per candidate; sanitize markdown (DOMPurify) and set Mermaid `securityLevel: 'strict'` (XSS risk with LLM/web text, still open); demo/replay mode; PDF export.
3. **Prior-art engine:** arXiv + OpenAlex + Semantic Scholar search, local MiniLM rerank, one comparison call (incl. where papers are stronger), critic check that every claim cites a retrieved paper, embedding-based novelty score, 2D similarity map, IEEE Related Work + BibTeX.
4. **Anchored scorecard:** LLM rates each category 0-4 against written anchors with quoted evidence (3 samples, median, spread shown), points computed in code; restore what-if sliders.
5. **Real benchmarks + "trained model":** mutation bug benchmark (inject bugs, measure Top-1/Top-3/MRR per retriever and full agent); fine-tune MiniLM on CodeSearchNet Python (report MRR before/after); SetFit intent router vs regex vs LLM; Model Lab + Benchmarks pages rendered from saved metrics JSON only.
6. Multi-round debate view, assumption evidence map, cost-of-run panel, ablation toggles.

### Known gaps / gotchas
- The sandbox proxy blocks DuckDuckGo, Hugging Face and console.groq.com, so live search and MiniLM were not exercised here; they fall back cleanly. On the user's machine they should work.
- Free-tier numbers come from secondary sources; the user should confirm on their Groq limits page.
- With TF-IDF vectors, hybrid retrieval did not beat BM25 on the 18-question benchmark (BM25 MRR 0.618, hybrid 0.580). Re-run with MiniLM before quoting numbers; Phase 5 retriever work should improve this.
- `tools/repo_map.py` and `indexer/chroma_store.py` are not used by the pipeline; the ruff wrapper is unused.
- Frontend files were not changed in Phase 1.
