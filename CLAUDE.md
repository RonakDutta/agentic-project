# CLAUDE.md

Guide for Claude (and other coding agents) working on this repo. Read it fully before changing anything; `AGENTS.md` points here. Keep it current: **every time you finish a piece of work, update the Status section, commit and push.**

---

## 1. The project in one minute

**Agentic Co-Pilot**: a B.Tech minor project (GGSIPU USAR) where cooperating AI agents help with two jobs:

| Pillar (UI name) | API intent | What it does |
|---|---|---|
| **Startup Assistance** | `idea_validation` | Checks an idea against the web, **real research papers**, and a devil's advocate; scores it with a fixed rubric; writes a PRD, diagrams and a roadmap. |
| **Codebase Evaluation** | `codebase_analysis` | Reads a Python repo (local path or GitHub URL), finds the code behind a bug or question, shows what a change would break, and has a critic verify every answer against the real files. Read-only. |

The user's goal: **impress teachers in a viva**. That only works if everything shown is real and checkable, so honesty is a hard rule (section 2).

---

## 2. Rules from the user (do not break these)

**Honesty**
- Never add hard-coded "results", fake citations, invented papers or invented fixes. Benchmarks compute what they print; report bad numbers as they are.
- Anything from a fallback is labelled (`generation_source: "fallback"`, trace `status="warning"`). Scores are computed in code, and the UI says so.

**The research-paper check is the headline feature.** Keep it prominent in every UI: closest paper with links (page / PDF / DOI), every matched paper with links, novelty index, similarity map, "where the paper is stronger" vs "what your idea adds", Related Work + BibTeX.

**UI style (the user rejects "AI-looking" design)**
- No pill shapes, no status dots, no pulsing or animated effects, no gradients, no uppercase letter-spaced labels, no fancy or serif display fonts, no arrows in buttons, no glow/shadows. Flat, square-ish corners (4-6px), one plain sans-serif (Inter) plus a mono font for code only.
- **Less text.** The teacher did not read long pages last time. Numbers and short labels first; details behind "Show more" / "How is this computed?".
- **Language:** easy to read but not childish. Keep a few real terms (AST, embeddings, call graph, novelty index) with a short explanation; no heavy jargon or buzzwords; no em dashes in user-facing text.
- **Do not show that the app uses an external API.** No "Groq", "free tier", "free tokens", "API key" or rate-limit wording in the new UI. Use neutral wording ("Engine ready", "AI model", "Engine busy"). Model ids are shown without the provider prefix (`modelName()` in `ui.jsx`); backend step text goes through `plainText()`.

**Process**
- Push finished work to the session branch quickly, and record it in this file (Status + Backlog).
- Never commit `.env` (it holds the user's real key; it is gitignored).

---

## 3. Commands

```bash
pip install -r requirements.txt
python app.py                                   # http://127.0.0.1:8000  (new UI at /, old UI at /legacy)
GROQ_API_KEY= pytest -q                         # 104 pass, 3 live smoke tests skip without a key
python evaluation/compare_baseline.py           # naive vs AST chunking (computed)
python evaluation/retrieval_benchmark.py        # BM25 / vector / hybrid Top-1, Top-3, MRR
python evaluation/free_tier_budget.py           # token plan vs the model limits (no quota used)

cd web/react-app && npm install && npm run build   # rebuild the UI into dist/ (committed, served by FastAPI)
cd web/react-app && npm run dev                    # dev server on :5173, proxies /api to :8000
```

- Run tests with `GROQ_API_KEY=` (empty): `python-dotenv` does not override a variable that is already set, so the real key in `.env` stays out of tests. `tests/conftest.py` also disables the disk cache, usage ledger, run limiter and live paper search (`PRIOR_ART_ENABLED=0`, `PAPER_CACHE=0`), and uses a temp sessions DB. Keep tests hermetic: no network, no key.
- `UI=legacy python app.py` serves the old single-file dashboard at `/` instead of the new UI.
- After any change under `web/react-app/src`, run `npm run build` and commit `dist/` too (the user runs `python app.py` without Node).

---

## 4. How it works

### Startup Assistance pipeline (`OrchestratorAgent._execute_idea_pipeline`)
```
Idea brief ─┬─ Market search (web) ── Devil's advocate ── Judge ──┐
            │        └──────── Roadmap (worker thread) ───────────┼── Scorecard (code) ── PRD + diagrams ── Report (14 sections)
            └─ Research papers (worker thread: arXiv · Semantic Scholar · OpenAlex) ──┘
```
7 LLM calls per run, about 15.9k tokens reserved (fits the pooled per-minute budget of 3 models). The scorecard is deterministic and takes prior-art novelty into Defensibility.

### Codebase Evaluation pipeline (`_execute_codebase_pipeline`)
```
(clone if GitHub URL) → AST index (cached) → hybrid retrieval (BM25 + MiniLM, RRF)
  → call-graph facts for the top symbol (blast radius + flow trace, no AI)
  → question mode (bug / impact / explain, regex) → Diagnosis (1 LLM call, line-numbered code)
  → Critic (no AI: file, symbol, lines, retrieved, quote-vs-disk, fix compiles) → at most one revision
```

### API (FastAPI, `app.py`)
| Endpoint | Purpose |
|---|---|
| `POST /api/run/stream` | **Used by the new UI.** Runs a pipeline and streams SSE events: `start`, `trace` (each agent step as it is recorded), `llm` (each model call: model, tokens, latency, cached), `heartbeat`, then `result` (full state) or `error`. |
| `POST /api/run/cancel` | `{run_id}` (from the `start` event): stops a streaming run before its next agent step. Closing the stream does the same. |
| `POST /api/query` | Same run, single JSON response (legacy UI, scripts). |
| `POST /api/followup` | Follow-up questions on a session (`@idea`, `@market`, `@roadmap`, `@critic`, `@planner`, `@navigate`, `@diagnose`). |
| `POST /api/inspect-repo` | Index a local folder or clone a GitHub URL; returns file/function counts. |
| `GET /api/health` | Engine status, model chain, call metrics, rate-limit state. |
| `GET /api/sample-repo-path`, `/api/graph`, `/api/graph/run`, `/api/agents`, `/api/session/{id}`, `/api/kb/lookup` | Helpers. |

### `final_output` data contract (what the UI reads)
- **Idea:** `project_title`, `problem_statement`, `core_value_prop`, `target_personas`, `mvp_features`, `competitors[]`, `tech_stack{layer: {choice, rationale, tradeoffs}}`, `citations[] (is_live)`, `scorecard{total_score, verdict, verdict_summary, categories[], evidence_confidence, ...}`, `kill_report{fatal_flaws[], bear_case_summary, ...}`, `reconciliation{verdict, must_have_mitigations, key_tradeoffs}`, `prd{product_vision, user_stories, functional_requirements, *_diagram_mermaid}`, `phases[]`, `risks[]`, **`prior_art`** (below), `provenance{section: llm|fallback|deterministic}`, `sections_13` (14 entries when prior art ran), `full_report_markdown`.
- **`prior_art`:** `papers[]{ref_id, title, authors, year, venue, abstract, url, pdf_url, doi, source, also_found_in, citation_count, similarity}`, `novelty_index`, `novelty_band`, `closest_similarity`, `evidence_confidence`, `similarity_backend`, `search_backend`, `queries`, `comparisons[]{ref, what_it_does, overlap, paper_is_stronger_at, idea_adds, overlap_level, abstract_support}`, `research_gap`, `positioning`, `related_work`, `ieee_references[]`, `bibtex`, `similarity_map[]{label, x, y, is_idea, similarity}`, `verification{comparisons_kept, invalid_refs_dropped, citations_removed, avg_abstract_support}`, `notes[]`, `generation_source`.
- **Code:** `summary`, `question_mode`, `candidates[]{rank, file_path, symbol_name, line_start, line_end, confidence, why_problematic, wrong_code, recommended_pattern, explanation_of_change, generated_by, verification{file_exists, symbol_exists, lines_in_bounds, in_retrieved_evidence, quote_matches_disk, fix_compiles}}`, `critic{grounding_score, is_valid, total_checked, total_verified, code_quote_matches, fixes_compiling, fixes_checked, flags}`, `impact{target_symbol, risk_level, blast_radius_score, direct_callers[], indirect_callers[], affected_tests, affected_entrypoints, mermaid_diagram, recommendations}`, `flow{hops[]}`, `retrieved_locations[]`, `indexed_summary`, `retrieval_backend`, `local_repo_path`.

---

## 5. Code map

**Backend**
- `app.py`: endpoints above; serves `web/react-app/dist` at `/` (assets at `/assets`), legacy at `/legacy`; per-client `RUNS_PER_MINUTE`; `ALLOWED_REPO_ROOTS`.
- `core/config.py`: every setting (env vars). Default models in `DEFAULT_*_MODEL`; limits `FREE_TIER_RPM/RPD/TPM/TPD`; prior-art keys `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_API_KEY`, `OPENALEX_EMAIL`, `PRIOR_ART_ENABLED`, `PAPER_CACHE`.
- `core/llm.py`: model client. Model-chain rotation, header-aware budgets, local `_UsageLedger`, reasoning kwargs per family, `<think>` stripping, memory + SQLite cache, `force_offline()` (**thread-local**: it does not reach worker threads), `AGENT_MAX_TOKENS`, `recent_calls` (feeds the SSE `llm` events).
- `agents/workflow_state.py`: `AgentWorkflowState.add_trace()` (thread-safe) calls `listener` (set via `orchestrator.process(on_trace=...)`) for live streaming; `cancel_event` + `RunCancelled` implement Stop (checked in `_run_step`).
- `agents/orchestrator.py`: `process()` = `new_state → classify → execute_track → finalize` (also the LangGraph nodes in `agents/graph.py`). `_run_step` re-runs a crashed step offline. `classify_code_question()`, `_structural_analysis()`, `_collect_prior_art()`, `_compile_13_sections()`.
- `agents/prior_art_agent.py` + `tools/paper_search.py`: queries from the idea (no LLM) → parallel search (arXiv relaxed AND → pair-OR variants; S2; OpenAlex) → title dedupe → 7-day cache `.cache/papers.sqlite` → MiniLM rerank (TF-IDF fallback) → novelty `100 x (1 - (0.6 x closest + 0.4 x mean top-3))` → PCA map → ONE LLM comparison over the top 5 abstracts → deterministic citation critic → IEEE refs + BibTeX. Never invents papers.
- `agents/feasibility_scorecard.py`: 7-category rubric, live citations only, evidence confidence, verdict reconciled with the Judge, prior-art penalty (-2 very close / -1 closely related, skipped when paper evidence is Low).
- `agents/diagnosis_agent.py`, `agents/critic_agent.py`, `agents/change_impact_agent.py`, `agents/flow_trace_agent.py`, `agents/code_nav_agent.py`: code track.
- `agents/idea_agent.py`, `market_agent.py`, `kill_agent.py` (+ reconciler), `prd_agent.py`, `roadmap_agent.py`: idea track. Every result has `generation_source` + `fallback_reason`.
- `agents/conversation_session.py`: follow-up engine, `SessionManager` (LRU + TTL + SQLite).
- `indexer/`: `ast_parser.py`, `bm25_search.py`, `vector_search.py` (MiniLM once per process), `hybrid_retriever.py`, `index_cache.py`, `github_ingest.py`.
- `tools/search_tool.py`: Tavily → `ddgs` → DDG Instant Answer → labelled offline references.

**New UI (`web/react-app/src`, React 18 + Vite, no Tailwind, fonts bundled via @fontsource)**
- `App.jsx`: header (pillar switch, engine status, theme toggle), `StartupPage`, `CodePage`, `useRun()` (SSE run state). Both pages stay mounted so a run survives switching.
- `api.js`: `streamRun()` (fetch + SSE parser), `getJSON`, `postJSON`.
- `pipelines.js`: graph definitions matched to trace `agent_name`s; `nodeStates()` derives done / working / fallback from real events and the dependency graph.
- `components/`: `PipelineGraph` (SVG agent graph), `RunPanel` (live graph + step log + AI calls), `TraceView` ("How it ran" tab), `FollowUp`, `ui.jsx` (Tag, Source, Bar, Score, More, Markdown via marked + DOMPurify, Mermaid lazy-loaded with `securityLevel: 'strict'`, `modelName`, `plainText`).
- `startup/StartupResult.jsx` (tabs: Overview, Research papers, Scorecard, Market, Risks, Plan, How it ran), `startup/Papers.jsx` (spotlight, novelty, similarity map, paper list, comparisons, gap/positioning, Related Work, BibTeX).
- `code/CodeResult.jsx` (tabs: Overview, Findings with verification checks and before/after code, Impact, How it ran).
- `styles.css`: design tokens (light default, dark via `data-theme`), flat components.
- Legacy UI: `web/templates/index.html` (kept at `/legacy`, not developed further).

---

## 6. Conventions

1. **Provenance:** new agent output gets `generation_source` and appears in `final_output["provenance"]`. Fallback trace steps use `status="warning"`.
2. **Budget:** a new LLM call needs an `AGENT_MAX_TOKENS` entry sized to its schema; `python evaluation/free_tier_budget.py` must still fit an idea run in the pooled per-minute budget (now ~15.9k of 24k). Prefer deterministic code over another LLM call. Do not route to `llama-3.1-8b-instant`.
3. **Trace steps:** the new UI matches nodes by `agent_name` (see `pipelines.js`); if you rename an agent or add a step, update `pipelines.js`. The legacy UI only shows steps with `details.thinking/findings`.
4. **Plain language:** prompts get `PLAIN_LANGUAGE_RULES`; no em dashes in user-facing text.
5. Agent-running endpoints are sync `def` (thread pool); the SSE endpoint runs the pipeline on its own thread.
6. Security: AI/web text is rendered as text, Markdown goes through DOMPurify, Mermaid runs in strict mode, links go through `SafeLink` (http/https only).

---

## 7. Status

### Phase 1: backend fixes (done, merged in PR #1)
Grounded prompts, deterministic critic with quote-vs-disk and compile checks, honest fallbacks, free-tier budgeting (ledger, per-agent max tokens, caches, model rotation), real search chain, scorecard counting live citations only, LangGraph running the real pipeline, computed evaluation scripts, 31 regression tests.

### Phase 3a: research papers + code-track fixes (done, branch `claude/happy-lamport-1iaat8`)
- Prior-art engine (sections 4-5), report section 14, scorecard novelty penalty, 11 tests (`tests/test_prior_art.py`).
- Code track was not broken in the backend (verified live on the sample repo and a GitHub clone). Fixed what looked broken: a demo prompt about code not in `sample_repo`, "blast radius" / "where is" questions forced into a bug answer (now question modes + call-graph facts), overflowing code panels.

### Phase 2: brand-new UI (done, same branch)
- New React app replaces the old Vite port (nothing kept from the old look); built `dist/` is committed and served at `/`.
- Real live progress over SSE (`/api/run/stream`): agent graph lights up from actual trace events; step log and per-call model/tokens/latency; no simulated delays.
- Startup: verdict screen (score, verdict, novelty, biggest risk, must-do, closest paper, score bars, provenance), Research papers tab (spotlight, links, PDF/DOI, novelty, similarity map, comparisons, gap/positioning, Related Work, BibTeX), Scorecard, Market, Risks, Plan (phases, Mermaid diagrams, requirements), How it ran.
- Code: verdict screen (grounding score, question mode, checks passed, top location, blast radius, repo size, critic bars), Findings (verification checks + before/after code with real line numbers), Impact (callers, flow, impact graph), How it ran.
- Follow-up chat on both. Light/dark theme. Works at 390px width (graph scrolls inside its box).
- DOMPurify + Mermaid strict mode (closes the old XSS gap). No CDN dependency in the new UI.
- Stable tab switching in Startup Assistance and Codebase Evaluation: removed `window.scrollTo({ top: 0 })` on tab changes so switching tabs (e.g. Overview to Research papers) updates content in place without jumping to the top of the page.
- Tests: `tests/test_run_stream.py`; total 104 pass.

### Phase 3b: fixes from the "must fix" list (done, branch `claude/lucid-newton-y54tpw`)
- Roadmap records its own trace step from its worker thread with its real duration (`_roadmap_worker`), so the live graph shows it done while the debate runs. The join is a new `Report Compiler` step (mapped in `pipelines.js` and `graph.py`). `add_trace` now holds a lock (worker threads record steps).
- Stop really stops: `/api/run/cancel` + cancel on stream close; the pipeline raises `RunCancelled` before the next agent step and the UI says "Run stopped. No further agent steps will run."
- Provider name removed from `/docs` text, `/v1/models` and the two legacy UI messages.
- Dark mode checked with screenshots (overview, research papers, scorecard, plan): readable, tags and bars have enough contrast.
- Tests: 104 pass (roadmap step order, unique step ids, cancel mid-run, cancel 404).

### Measured numbers (real runs, keep updated)
- Retrieval benchmark, 18 questions, MiniLM available: BM25 MRR 0.640 (Top-1 50%, Top-3 72%); vector 0.672 (56%, 78%); hybrid RRF 0.647 (44%, **83% Top-3**). Hybrid is best at Top-3, not at Top-1/MRR; say so if asked.
- AST vs naive chunking: 91% of 500-char chunks cut through a function; 100% of AST chunks parse.
- Water-meter idea (live): 8 arXiv papers, novelty 39/100 "Closely related work exists", 5/5 comparisons kept, 85% abstract support; full idea run ~60-70s uncached.
- Code run on `sample_repo`: 1 LLM call, ~2-9s, critic 100%.

---

## 8. What is left and what needs improvement (start here next session)

**Must fix / verify next**
- Market search sometimes falls back (seen once with the user's 10s timeout). Find the exact cause in the log (`logging.basicConfig(level=logging.INFO)`), then either raise the default timeout or shrink the market prompt.
- Follow-up chat in the new UI was not tested against a live answer yet; check Markdown rendering, `@agent` routing and the error state.
- Honesty gap seen offline: when the paper comparison falls back ("Not assessed"), the header still says "5/5 refer to a paper we found, 100% backed by abstracts". Show "not checked" when `prior_art.generation_source == "fallback"`.
- Fallback idea brief title is the first words of the prompt ("A Mobile App That"); build a better title in code (for example the noun phrase after "app that").
- Mermaid "dark" theme not yet checked with a live (non-fallback) PRD.
- Code comments and module docstrings in `app.py` still name the provider (not user-facing).

**UI polish (keep the flat, plain style)**
- Similarity map: labels overlap when papers cluster (P5/P7). Nudge labels apart or list close points beside the map.
- Live graph text is small on phones (graph scrolls sideways at 390px); consider a vertical layout under 640px.
- Findings: highlight changed lines between "Code now" and "Suggested version" (simple line diff, no library needed).
- Overview pages are already short; keep cutting text where a number or a link can replace a sentence.
- Empty and error states are minimal (one line). Give each a clear next step (for example "Scan a repo first").
- Add a small "copy link to this paper" / "copy reference" action next to each paper.

**Backend / data**
- Pre-warm the paper cache for the three demo ideas before the viva (run each once on the demo laptop with internet), and add free Semantic Scholar / OpenAlex keys to `.env` so all three sources answer.
- `sections_13` holds 14 sections; rename only together with the legacy UI and tests.
- Retrieval: hybrid RRF is best at Top-3 but not Top-1 on the benchmark; try weighting BM25 vs vectors or a cross-encoder rerank, and report the numbers honestly.

## 9. Open question from the user (do NOT build yet, discuss first)

> Can we add a new agent that **codes the idea** as well? It does not need to be good: a very small, basic version is enough. The same agent (or a sibling) would also **build and monitor the product**.

Notes for whoever picks this up (thinking only, nothing decided):
- Scope that would fit: from the PRD's top 2-3 "Must Have" requirements, generate a tiny runnable skeleton (for example a FastAPI app with one or two endpoints and a stub UI page), write it to a sandbox folder, never into the user's repos.
- "Build" could mean: generate files, run `python -m py_compile` / `pytest` on them, start the app in a subprocess and hit its health endpoint. "Monitor" could mean: show live status (running / crashed), request count and the last errors from its log in the UI.
- Reuse what exists: the Critic's compile checks, the Codebase Evaluation pipeline to review the generated code, the SSE stream to show build progress.
- Honesty rules still apply: label it as a generated prototype, show real build/test output, never claim it works if the checks failed.
- Risks to settle first: running generated code safely (subprocess, temp dir, time limit, no network), token budget (a code-writing call is large; check `free_tier_budget.py`), and whether the read-only promise of the project still holds (it would stay read-only for the user's code; only the sandbox is written).
- Ask the user before building: how small is "small", which stack, and whether the demo should run the prototype live.

## 10. Backlog (pick from here; keep everything computed and real)

From the user:
- Keep extending the research-paper check (it is the wow factor).

Ideas (Claude):
1. **Prior art+:** Semantic Scholar citation graph of the closest paper; "papers per year" chart (is the field growing?); let the Devil's advocate and Judge cite papers; pre-warm the paper cache for the 3 demo ideas; free S2/OpenAlex keys on the demo laptop.
2. **"Plain AI vs our pipeline" view:** same idea through one bare prompt, side by side with what the agents add (papers, citations, critic checks). Strong viva argument.
3. **PDF export** of the full report with IEEE references.
4. **Presentation mode** for the viva: a keyboard walkthrough of one saved real run, labelled "replay of a real run on <date>".
5. **Anchored scorecard:** the AI rates each category 0-4 against written anchors with quoted evidence (3 samples, median, spread shown); points computed in code; what-if sliders.
6. **Real benchmarks + trained model:** mutation bug benchmark (inject bugs, measure Top-1/Top-3/MRR per retriever and full agent); fine-tune MiniLM on CodeSearchNet Python (MRR before/after); SetFit intent router vs regex vs LLM; a Benchmarks page rendered from saved metrics JSON only.
7. **Code extras:** file risk heatmap (complexity x callers); repo health card for GitHub URLs; diff-style highlighting in Findings.
8. **Assumption evidence map:** each key assumption linked to the web result or paper that supports or contradicts it.

---

## 11. Gotchas

- The user's `.env` sets `REQUEST_TIMEOUT_SECONDS=10`. The market step has the largest prompt and occasionally fell back in testing; raise the timeout to 30 if "Too slow" appears in the log.
- Semantic Scholar and OpenAlex return 429 for unauthenticated requests from shared IPs (they did in the cloud sandbox); arXiv worked. Results are cached 7 days once a search succeeds; empty results are not cached.
- Novelty bands are fixed MiniLM cosine cut-offs (0.75 / 0.60 / 0.45; lower for TF-IDF). They are heuristic; say so if asked.
- `force_offline()` is thread-local. Code that runs on worker threads (prior art, roadmap, the SSE runner) is not covered by it; tests stub `llm_client.generate` instead.
- Cached runs finish in well under a second and show 0 tokens; that is correct (the cache is real), but run a fresh idea for a live demo.
- Mermaid adds ~2 MB of lazy chunks to `dist/`; they load only when a diagram is shown.
- Unused modules: `indexer/repo_map.py`, `indexer/chroma_store.py`, the ruff wrapper in `tools/lint_metrics.py`.
- `sections_13` keeps its name for compatibility even though it holds 14 sections when prior art ran.
