# CLAUDE.md

Working notes for Claude sessions on this repo. Read this first, then `README.md`.

## What this project is

B.Tech minor project (GGSIPU USAR): a multi-agent "AI Co-Pilot". **New name (Oct 2026): the two pillars are now "Startup Assistance" and "Codebase Evaluation".** Use these names in the new UI, README headings and any new user-facing text. Code identifiers (`idea_validation`, `codebase_analysis`) stay as they are for API compatibility.
- **Startup Assistance (idea track):** decompose -> market/web search + **research prior-art search (arXiv / Semantic Scholar / OpenAlex)** in parallel -> kill agent -> reconciler -> deterministic scorecard (uses prior-art novelty) -> PRD (+ Mermaid) -> roadmap. 13-section report + section 14 "Research Prior Art & Novelty".
- **Codebase Evaluation (code track, read-only):** AST index -> hybrid retrieval (BM25 + MiniLM/TF-IDF, RRF) -> call-graph facts (blast radius + flow trace, deterministic) -> diagnosis (Groq, question-mode aware: bug / impact / explain) -> deterministic critic -> one critic-driven revision.

The goal is to impress teachers and evaluators in a viva, so every claim the UI or README makes must be true and checkable. Never add hard-coded "results", fake citations or invented fixes. When something is a fallback, label it.

**The research-paper comparison is the headline "wow" feature.** The user explicitly wants the evaluator to see that the idea was checked against real, linked research papers. Keep it prominent in every UI.

Stack: FastAPI (`app.py`), Groq free tier (`core/llm.py`), LangGraph (`agents/graph.py`), SQLite (sessions, LLM cache, usage ledger). The UI served at `/` is still the legacy `web/templates/index.html` (Tailwind/Mermaid from CDNs). `web/react-app/` is a Vite port that is **not served yet** (dev server only, proxies `/api`).

## Commands

```bash
pip install -r requirements.txt
python app.py                                # http://127.0.0.1:8000
pytest -q                                    # 99 pass, 3 live-Groq smoke tests skip without GROQ_API_KEY
python evaluation/compare_baseline.py        # naive vs AST chunking (computed)
python evaluation/retrieval_benchmark.py     # BM25 / vector / hybrid Top-1, Top-3, MRR
python evaluation/free_tier_budget.py        # token plan vs Groq free-tier limits (no quota used)
```

`tests/conftest.py` disables the disk cache, the usage ledger, the run limiter and the live paper search (`PRIOR_ART_ENABLED=0`, `PAPER_CACHE=0`), and points sessions at a temp DB. Keep tests hermetic: no network, no key. Run tests with `GROQ_API_KEY= pytest -q` if a local `.env` holds a real key (dotenv does not override an env var that is already set, even to empty).

## Map of the code

- `core/config.py`: all settings (env vars). Default models live in `DEFAULT_*_MODEL`. Free-tier limits: `FREE_TIER_RPM/RPD/TPM/TPD`.
- `core/llm.py`: Groq client. Model chain rotation, header-aware budgets, local `_UsageLedger` (RPM/TPM windows + daily totals), reasoning kwargs per model family, `<think>` stripping, memory + SQLite cache, `force_offline()` (thread-local) context manager, `AGENT_MAX_TOKENS` per agent.
- `agents/orchestrator.py`: `process()` = `new_state` -> `classify` -> `execute_track` -> `finalize` (these are the LangGraph nodes). Idea pipeline runs the roadmap and the prior-art research on worker threads (prior art joins before the scorecard via `_collect_prior_art`). `_run_step` re-runs a crashed step with `force_offline()`. Code pipeline: `classify_code_question()` (bug / impact / explain, regex) and `_structural_analysis()` (ChangeImpactAgent + FlowTraceAgent on the primary suspect) feed call-graph facts into the diagnosis prompt; `final_output` gains `question_mode`, `impact`, `flow`, `retrieved_locations`.
- `agents/*_agent.py`: each result dataclass has `generation_source` ("llm"/"fallback") + `fallback_reason`.
- `agents/feasibility_scorecard.py`: deterministic rubric; only live citations count; `evidence_confidence`; verdict reconciled with the Reconciler.
- `agents/critic_agent.py`: file/symbol/line checks, retrieved-evidence check, quoted-code-vs-disk check (replaces invented code), `ast.parse` on fixes; per-candidate `verification` dict.
- `agents/diagnosis_agent.py`: line-numbered prompt, `feedback=` for static notes and critic revision, safe int parsing, honest fallback (no invented code).
- `agents/conversation_session.py`: follow-up engine + `SessionManager` (LRU + TTL, SQLite persistence, GitHub URL -> local clone).
- `indexer/index_cache.py`: per-repo cache of `CodebaseIndex` + `HybridRetriever`, keyed by file size/mtime.
- `indexer/vector_search.py`: MiniLM loaded once per process; failure remembered.
- `tools/paper_search.py`: arXiv (Atom XML, relaxed AND -> pair-OR query variants), Semantic Scholar, OpenAlex searched in parallel; dedupe by normalised title; 7-day SQLite cache of real responses (`.cache/papers.sqlite`); IEEE reference + BibTeX formatting. Never returns placeholder papers.
- `agents/prior_art_agent.py`: keyword queries from the idea (no LLM) -> search -> MiniLM rerank (TF-IDF fallback) -> novelty index `100 x (1 - (0.6 x closest + 0.4 x mean top-3))` with heuristic bands -> 2D PCA similarity map -> ONE LLM call (`AGENT_MAX_TOKENS["prior_art"]`) comparing the idea with the top 5 abstracts (incl. where each paper is stronger) + research gap + positioning + IEEE Related Work paragraph -> deterministic critic (drops comparisons citing unretrieved refs, strips out-of-range `[n]`, `abstract_support` word-overlap ratio per claim). Fallback = shared key terms only, says "not assessed".
- `tools/search_tool.py`: Tavily -> `ddgs` -> DDG Instant Answer -> labelled offline references. `SearchResultItem.is_live`.
- `indexer/github_ingest.py`: shallow clone, `GIT_TERMINAL_PROMPT=0`, size limit, evicted clones deleted.

## Conventions (keep these)

1. **Provenance:** any new agent output gets `generation_source` and shows up in `final_output["provenance"]`. Fallback trace steps use `status="warning"`.
2. **Free-tier budget:** a new LLM call needs an entry in `AGENT_MAX_TOKENS` sized to its schema, and `python evaluation/free_tier_budget.py` must still show an idea run under the pooled TPM (currently ~15.9k of 24k with the prior-art call). Prefer deterministic code over another LLM call. Do not route to `llama-3.1-8b-instant`: it is reportedly no longer on the free tier (Aug 2026).
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

### Phase 3 (part 1): Prior-art engine + code-track fixes (done, branch `claude/happy-lamport-1iaat8`)
- Live check with the user's Groq key (gpt-oss-20b, qwen3.8-27b, gpt-oss-120b all valid): the code track was NOT broken in the backend (sample repo + GitHub clone both gave LLM diagnoses with 100% critic score). What looked broken: the "Orchestrator Intent Bug" sample chip asked about code that is not in `sample_repo` (0 findings, now replaced by "Duplicate Orders Bug"), blast-radius / "where is" questions were forced into a bug-fix answer (now question modes + call-graph facts), and code panels overflowed (`min-w-0`).
- Prior-art engine (see map above): `final_output["prior_art"]`, `provenance["prior_art"]`, report section 14, a 5th storyboard card ("Prior-Art Researcher", IDEA_AGENTS node_3), scorecard Defensibility -2 / -1 when very close / closely related papers exist (only when paper evidence is not "Low").
- Legacy UI got a "Research Prior Art & Novelty" panel: closest-paper spotlight (abstract, authors, venue, Open paper / PDF / DOI links), table of every matched paper with links + expandable abstracts + similarity bars, novelty gauge with the formula, SVG similarity map, head-to-head cards (what it does / overlap / where the paper is stronger / what your idea adds / abstract support %), research gap, positioning, IEEE Related Work + references, Copy BibTeX / Download .bib.
- Live result in the sandbox: arXiv works; Semantic Scholar and OpenAlex returned 429 (shared sandbox IP, no key) and are labelled as unreachable. Water-meter idea: 8 arXiv papers, novelty 39/100 "Closely related work exists", 5/5 comparisons kept, abstract support 85%.
- Budget: idea run now 7 calls, ~15.9k reserved of the pooled 24k TPM (~53 runs/day). Code run unchanged (1 call, ~4.2k).
- Tests: `tests/test_prior_art.py` (11 hermetic tests).

### Next phases (from the plan agreed with the user)
2. **UI rebuild (BRAND NEW, see "New UI requirements" below):** build `web/react-app` and serve `dist/` from FastAPI (drop CDN dependency); stream progress over SSE from real trace events (today the UI waits for the full response, then replays steps with fake 600ms delays); live agent graph (React Flow) with per-call model/tokens/latency from `llm_client.recent_calls`; show provenance/fallback badges, evidence confidence, critic `verification` per candidate; sanitize markdown (DOMPurify) and set Mermaid `securityLevel: 'strict'` (XSS risk with LLM/web text, still open); demo/replay mode; PDF export.
3. **Prior-art engine:** core DONE (above). Still open: Semantic Scholar citation graph of the closest paper (references/citations as a small network), "papers per year" chart for the topic (is the field heating up?), let the Kill Agent and Reconciler cite papers as evidence, optional `SEMANTIC_SCHOLAR_API_KEY` / `OPENALEX_API_KEY` in `.env` on the demo laptop to avoid 429s, pre-warm the paper cache for the demo ideas.
4. **Anchored scorecard:** LLM rates each category 0-4 against written anchors with quoted evidence (3 samples, median, spread shown), points computed in code; restore what-if sliders.
5. **Real benchmarks + "trained model":** mutation bug benchmark (inject bugs, measure Top-1/Top-3/MRR per retriever and full agent); fine-tune MiniLM on CodeSearchNet Python (report MRR before/after); SetFit intent router vs regex vs LLM; Model Lab + Benchmarks pages rendered from saved metrics JSON only.
6. Multi-round debate view, assumption evidence map, cost-of-run panel, ablation toggles.

### New UI requirements (from the user, Oct 2026)
- **Completely new UI. Nothing from the current `index.html` look should survive** (layout, colours, cards, wording). Treat the legacy UI only as a reference for which API fields exist.
- Pillar names: **Startup Assistance** and **Codebase Evaluation**.
- **Much less text.** Last time the teacher did not read everything. Visual first: one verdict screen with the few numbers that matter, short one-line labels, details collapsed behind "show more". Cut long paragraphs, repeated explanations and per-step prose.
- **Language level:** easy to read but not childish. Keep a few real technical terms where they earn their place (AST, embeddings, call graph, novelty index) and explain them in a few words; cut heavy jargon and buzzwords everywhere else. Put formulas and method details behind "How is this computed?" toggles instead of in the main text. Same rule for prompts (`PLAIN_LANGUAGE_RULES`), README and report text.
- **Research papers stay and stay prominent**: closest paper with link/PDF, the list of matched papers with links, novelty index, similarity map, "where the paper is stronger" vs "what your idea adds". Everything else should be trimmed.
- Show as much *evidence* as possible in small space: provenance badges (AI / fallback / deterministic), critic verification ticks, live call stats (model, tokens, latency), links.
- Still honest: label fallbacks, never fake progress (stream real trace events over SSE instead of the 650ms replay).

### Feature ideas backlog (user + Claude; pick from here in later sessions)
From the user: research-paper comparison (done, extend it), show the matched papers with links in the UI (done in legacy UI, carry over), brand-new UI, less text, rename to Startup Assistance / Codebase Evaluation.
From Claude (all must stay computed/real, no fake numbers):
- **10-second verdict card** at the top of each report: score, verdict, novelty index, closest paper, top fatal flaw, evidence confidence. This is what the teacher reads.
- **"Plain LLM vs our pipeline" ablation view:** run the same idea through one bare prompt and show side by side what the multi-agent pipeline adds (citations, papers, critic checks). Strong viva argument.
- **Live agent graph** (React Flow) driven by SSE trace events, with per-call model, tokens and latency from `llm_client.recent_calls`.
- **Code: blast-radius graph** from `final_output["impact"]["mermaid_diagram"]` and flow hops from `final_output["flow"]`, plus a file risk heatmap (complexity x callers).
- **Code: repo health card** for GitHub URLs (files, symbols, avg complexity, last commit, test files found).
- **PDF export** of the full report including IEEE references and BibTeX.
- **Viva / presentation mode:** keyboard-driven walkthrough of one cached real run (labelled "replay of a real run on <date>").
- **Citation graph + papers-per-year chart** for the prior-art topic (Semantic Scholar / OpenAlex counts).
- **Assumption evidence map:** each key assumption linked to the web result or paper that supports or contradicts it.
- **Cost-of-run panel:** tokens used vs free-tier limits for this run.

### Known gaps / gotchas
- The sandbox proxy blocks DuckDuckGo, Hugging Face and console.groq.com, so live search and MiniLM were not exercised here; they fall back cleanly. On the user's machine they should work.
- Free-tier numbers come from secondary sources; the user should confirm on their Groq limits page.
- With TF-IDF vectors, hybrid retrieval did not beat BM25 on the 18-question benchmark (BM25 MRR 0.618, hybrid 0.580). Re-run with MiniLM before quoting numbers; Phase 5 retriever work should improve this.
- `tools/repo_map.py` and `indexer/chroma_store.py` are not used by the pipeline; the ruff wrapper is unused.
- Frontend: Phase 1 did not touch it; Phase 3 added the prior-art panel, the 5-node idea storyboard, the new code sample chip and the code-panel overflow fix to the legacy `index.html` only (the React app was not updated).
- Semantic Scholar / OpenAlex rate-limit unauthenticated requests per IP (429). Results are cached 7 days once a search succeeds; empty results are not cached.
- Prior-art novelty bands are heuristic MiniLM cosine cut-offs (0.75 / 0.60 / 0.45); TF-IDF uses lower cut-offs. Say so if asked.
- The user's `.env` uses `REQUEST_TIMEOUT_SECONDS=10`; live calls took 2-10s so it works, but raise it to 30 if timeouts appear in the log ("Too slow").
