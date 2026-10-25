# Agentic AI Co-Pilot: Multi-Agent RAG System for Idea Validation & Codebase Analysis

> **Academic Project:** B.Tech (IIoT), 7th Semester Minor Project  
> **Institution:** Guru Gobind Singh Indraprastha University (USAR, GGSIPU)  
> **Repository:** [https://github.com/RonakDutta/agentic-project](https://github.com/RonakDutta/agentic-project)

---

## 📌 Executive Summary
Standard Large Language Models generate answers in a single step and lack access to private project code or real-time market data. When asked to debug software or validate a startup idea, they often hallucinate unverifiable claims.

This project implements an **Agentic AI Co-Pilot** featuring a **Supervisory Multi-Agent Architecture** backed by an **AST-aware Retrieval-Augmented Generation (RAG)** pipeline and deterministic verification tooling.

The system is balanced into two 50-50 first-class pillars, shown in the app as **Startup Assistance** and **Codebase Evaluation**:
1. **Pillar 1: Codebase Evaluation (Codebase Diagnostic Co-Pilot):** Parses Python repositories into semantic Abstract Syntax Tree (AST) units, conducts hybrid lexical/dense retrieval, localizes fault locations with exact line numbers, and executes deterministic verification. Strictly operates in read-only mode to produce root-cause hypotheses and fix directions with human review (no automated or unsupervised code editing).
2. **Pillar 2: Startup Assistance (Idea Validation Co-Pilot):** Decomposes raw ideas into structured problem briefs, target user personas, live competitor intelligence, adversarial devil's advocate stress tests, deterministic feasibility scoring, formal PRDs with Mermaid models, and 3-phase delivery roadmaps.

---

## 🏗️ System Architecture

```
                                      [ USER INPUT ]
                                            │
                               [ 1. Orchestrator Agent ]
                             (Intent Classifier & Planner)
                                            │
            ┌───────────────────────────────┴───────────────────────────────┐
            ▼                                                               ▼
    [ TRACK A: CODEBASE ANALYSIS ]                                  [ TRACK B: IDEA VALIDATION ]
    ──────────────────────────────                                  ────────────────────────────
    2. AST Codebase Indexer                                         2. Idea Decomposition Agent
       - Function & Class Chunks                                       - Problem Statement & Personas
       - Alias-Aware Import Graph                                      - MVP Scopes & Assumptions
       - Call Confidence & Graphs                                   3. Market & Stack Specialist
    3. Static Code Analyzer                                            - Tavily / DuckDuckGo Search
       - McCabe Complexity & SLOC                                      - Competitors & Tradeoffs
    4. Code Navigation Agent                                        4. Adversarial Kill Agent
       - Hybrid Search (BM25 + Dense)                                  - Devil's Advocate Flaws
       - Reciprocal Rank Fusion                                        - Incumbent Replication Risks
    5. Flow Trace & Impact Agents                                   5. Impartial Systems Arbiter
       - Request Path & Mermaids                                       - Thesis vs Antithesis Synthesis
       - Blast Radius Calculator                                       - Non-Negotiable Preconditions
    6. Diagnosis Agent (Fix Direction)                              6. Feasibility Scorecard Engine
       - Educational Pattern Slices                                    - Deterministic 7-Category Rubric
       - Current vs Recommended Code                                   - Academic Rubric Disclaimer
    7. Programmatic Critic Agent                                    7. PRD & Architecture Engine
       - Physical Disk & AST Check                                     - User Stories & Functional Reqs
       - Grounded Line Verification                                    - Interactive Mermaid Models
            │                                                       8. Roadmap & Risk Assessor
            │                                                          - 3-Phase Milestone Plan
            │                                                          - 13-Section Report Compiler
            │                                                               │
            └───────────────────────────────┬───────────────────────────────┘
                                            ▼
                             [ Deterministic Tool Layer ]
                       (AST Parser, Call Graph, Token Budget,
                        Critic Validator, Rubric Scorecard)
                                            │
                                            ▼
                            [ Web Interface (React + Vite) ]
                     (Live agent graph over Server-Sent Events,
                      research papers, verdict screens, follow-ups)
```

---

## ⚡ Key Technical Capabilities

### 1. AST Codebase Parsing & Alias-Aware Call Graphs
Standard text chunking breaks functions in half. Inspired by *AutoCodeRover (ISSTA 2024)*, the indexer uses Python's `ast` module:
* Indexes code at class and function boundaries; module headers stop before the first definition.
* Resolves imported aliases (such as `from auth import login as do_login`).
* Maps caller and callee relationships with explicit confidence levels (`CERTAIN`, `HIGH`, `LOW`, `UNRESOLVED`).
* Indexes are cached per repository and rebuilt only when a `.py` file changes (`indexer/index_cache.py`).

Measured by `python evaluation/compare_baseline.py` on this repository: **91% of naive 500-character chunks cut through a function** and 68% of functions are never held whole by any naive chunk, while **100% of AST chunks parse as complete Python** (462/462).

### 2. Hybrid Retrieval (BM25 + Vectors, Reciprocal Rank Fusion)
* BM25 with a code-aware tokenizer (`jwtAuthService` -> `jwt`, `auth`, `service`).
* Dense vectors from `all-MiniLM-L6-v2` (loaded once per process), with a TF-IDF fallback for offline machines.
* Exact symbol mentions are matched as whole identifiers, so short names like `get` or `id` do not match everything.
* `python evaluation/retrieval_benchmark.py` scores BM25, vector and hybrid retrieval (Top-1, Top-3, MRR) on 18 plain-English questions about this codebase. With MiniLM: BM25 MRR 0.640 (Top-3 72%), vectors 0.672 (78%), hybrid RRF 0.647 with the best Top-3 (83%). Hybrid wins on Top-3 but not on Top-1, and we report it that way.

### 3. Grounded Diagnosis with a Deterministic Critic
"Agents reason, tools compute." The Diagnosis Agent receives line-numbered code plus static analysis (complexity via the built-in analyzer and `radon`, last commit via `git blame` when available). The Critic then checks, without an LLM:
* the cited file exists and the symbol is in the AST symbol table (preferring the definition in the cited file);
* the cited line range is inside the file and overlaps the symbol;
* the citation was in the evidence actually retrieved for this query;
* the quoted "current code" really exists in the file (if not, it is replaced by the real lines from disk and flagged);
* the recommended fix compiles (`ast.parse`).

Before the diagnosis, the call graph is computed for the primary suspect (blast radius: direct and indirect callers, affected entry points and tests, risk level; plus a static flow trace). The question is classified as a bug report, a change-impact question or a "where / how" question, and the diagnosis prompt gets the call-graph facts and the matching instructions, so "what breaks if I change `verify_token`?" ranks the dependent callers instead of inventing a bug.

If verification fails, the Critic's flags and repair hints are sent back to the Diagnosis Agent for **one revision with a different prompt**, and the better-grounded answer is kept. The trace reports real counts (for example "3/3 quoted code blocks match the file").

The system is read-only by design: it explains the root cause and shows a recommended pattern for human review; it never edits code. Without an LLM it ranks locations by retrieval and static analysis and says so, instead of inventing a fix.

### 4. Adversarial Kill Agent & Evidence Reconciler
* **Kill Agent (Devil's Advocate):** fatal flaws, incumbent threats, distribution traps and over-engineering risks. Severity and category labels from the model are normalised (`critical`, `HIGH`, `severe` -> Critical/High/Medium).
* **Evidence Reconciler:** weighs the thesis against the critique and gives one of three verdicts. If the model gives none, the verdict is derived from the number of critical flaws instead of defaulting to "Proceed".

### 5. Deterministic Feasibility Scorecard
A transparent 100-point rubric across 7 categories (Problem Validation 20, Market Demand 20, Defensibility 15, Technical Feasibility 15, Go-To-Market 10, Resources 10, Risk 10), framed as `"Feasibility Score: X/100 based on the defined project rubric."`
* Only **live** web search results count as citations; offline references and model knowledge do not.
* Resource Requirements reads the actual stack and idea (hardware, paid managed services, number of layers, feature count).
* The verdict cannot contradict the Reconciler: a GO is capped at PIVOT when the Reconciler finds high rejection risk.
* Every scorecard carries an **evidence confidence** (High / Medium / Low) that drops when fallbacks were used or no live search was reachable.

### 6. Research Prior-Art Check (Related Work, computed)
Every idea is checked against published research, live:
* **Search:** arXiv, Semantic Scholar and OpenAlex in parallel, deduplicated by title (`tools/paper_search.py`). No key is needed; results are cached for 7 days.
* **Rerank:** `all-MiniLM-L6-v2` embeddings of the idea and each paper's title and abstract (TF-IDF fallback).
* **Novelty index:** `100 x (1 - (0.6 x closest similarity + 0.4 x mean of the top 3))`, computed in code, with the similarity backend and evidence confidence shown. The scorecard's Defensibility category loses points when very close papers exist.
* **Head-to-head comparison:** one LLM call reads only the abstracts and says, per paper, what it does, the overlap, **where the paper is stronger**, and what the idea adds, then writes a research gap, positioning and an IEEE-style Related Work paragraph.
* **Critic:** comparisons that cite a paper that was not retrieved are dropped, out-of-range `[n]` citations are removed, and each claim's word overlap with the paper's own abstract is reported.
* **Outputs:** linked paper list (paper page, PDF, DOI), closest-paper spotlight, 2D similarity map (PCA), IEEE references and a downloadable `.bib` file. If no source answers, the report says so and shows no novelty index; no paper is ever invented.

### 7. PRD & Architecture Engine
User stories, prioritized functional requirements, non-functional requirements, and three Mermaid diagrams generated from **this idea's** stack, persona and MVP features (labels are escaped so model text cannot break the diagram).

### 8. Prototype Builder (codes, tests, runs and monitors the idea)
From the PRD's top requirements, one AI call writes a tiny FastAPI app with one web page and its tests. Code then checks it before anything runs (import allowlist, no `eval`/`exec`/`open`, no outside scripts), compiles it, runs `pytest`, lets the AI fix it once using the real error output, starts it on `127.0.0.1` and calls every GET endpoint. The Prototype tab shows a live preview and a monitor (requests, errors, response time) read from the app's own log. It never writes into your projects; prototypes live in `~/.agentic-copilot/prototypes/` (outside the project, so the auto-reloading server does not restart when one is written) and stop by themselves after 20 minutes. If the AI cannot produce safe, compiling code, a labelled built-in prototype is used instead.

### 9. Honest Provenance on Every Section
Each agent output records `generation_source` (`llm` or `fallback`) and a reason. The final report includes a `provenance` map, `used_fallback`, the web search backend used and the number of live citations. Trace steps that used a fallback are marked `warning`. A step that crashes is re-run on its own built-in fallback, so one bad model reply never fails the whole run.

### 10. Explicit LangGraph State Graph
`agents/graph.py` compiles a real LangGraph `StateGraph` whose nodes run the orchestrator's actual steps: `classify -> (codebase_pipeline | idea_pipeline) -> finalize`, with a conditional edge on the classified intent. `GET /api/graph` reports the active backend and `POST /api/graph/run` returns the nodes visited. Without `langgraph` installed, the same steps run in sequence.

### 11. Persistent Conversational Follow-Ups
* Multi-turn sessions with anaphora resolution ("What calls that function?").
* Sessions are saved to SQLite after every turn and restored after a server restart; memory is bounded (LRU + idle TTL).
* Follow-ups on a GitHub repository use its local clone, so caller, impact and flow-trace routers work on remote repos too.
* `@mention` a specialist: idea track `@idea`, `@market`, `@roadmap`, `@critic`; code track `@planner`, `@navigate`, `@diagnose`, `@critic`. These replies are built from the session's stored evidence with zero LLM quota.

---

## 🧮 Built for the Groq Free Tier

Each model in the chain has its own free-tier budget. Secondary sources (September 2026) list **30 requests/min, 1,000 requests/day, 8,000 tokens/min and 200,000 tokens/day** for `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and `qwen/qwen3.8-27b`. Check your own limits at console.groq.com/settings/limits and set `FREE_TIER_*` in `.env` if they differ.

How the client stays inside them (`core/llm.py`):
* **Local ledger:** per-model sliding 60-second windows (requests and tokens, including calls in flight) and per-day totals, enforced from the very first call. Daily totals are saved to `.cache/llm_usage.sqlite`.
* **Right-sized answers:** each agent asks only for the tokens its JSON needs (`AGENT_MAX_TOKENS`). A truncated JSON answer is retried once with 1,024 more tokens.
* **Reasoning controls:** `reasoning_effort=low` for gpt-oss and hidden reasoning for Qwen3, so thinking tokens do not eat the answer budget or leak `<think>` text into JSON.
* **Header-aware routing:** reads `x-ratelimit-*` headers, spreads short prompts across models, keeps long prompts on the strongest model with budget, and parses `retry-after` hints (including long daily waits like `14m22s`).
* **Parallel steps:** the roadmap runs alongside the debate steps, on a different model's window.
* **Caching:** identical prompts are free for 10 minutes in memory and for 7 days on disk (`.cache/llm_cache.sqlite`), so re-running a demo idea costs nothing.
* **Wrong model ids** (`model_not_found`, `decommissioned`) are parked for an hour instead of retried.

`python evaluation/free_tier_budget.py` measures the real prompts without spending quota. Current result: an idea run makes 7 calls (including the prior-art comparison) and reserves about **15.9k tokens** (fits the pooled 24k tokens/min of three models), uses about 11.2k tokens in practice, which allows roughly **53 idea runs per day**. A code run makes 1-2 calls of about 4k tokens. `GET /api/health` shows live per-model usage and an estimate of idea runs left today.

---

## 🚀 Quick Start Guide

### 1. Installation
```bash
git clone https://github.com/RonakDutta/agentic-project.git
cd agentic-project
pip install -r requirements.txt
```

### 2. Environment Configuration
```bash
cp .env.example .env
```
Set your free Groq key in `.env` (`GROQ_API_KEY=...`). Optional: `TAVILY_API_KEY` for better web search (DuckDuckGo via `ddgs` is used otherwise).

The app starts without a key: AST indexing, retrieval, the Critic, the scorecard and the deterministic follow-up routers work offline, and LLM-backed agents fall back to clearly labelled built-in output.

### 3. Launch the App
```bash
python app.py
```
Open **`http://127.0.0.1:8000`**. The interface is prebuilt in `web/react-app/dist`, so Node is not needed to run it. To change the UI: `cd web/react-app && npm install && npm run build`.

**What you see:** pick *Startup Assistance* or *Codebase Evaluation*, run the agents, and watch the agent graph light up live as each step really finishes (streamed from the server, nothing replayed). Each report opens on a short verdict screen; details sit in tabs (research papers, scorecard, market, risks, plan, findings, impact, and "How it ran" with every AI call's model, tokens and time). Before exposing the app to other people, set `ALLOWED_REPO_ROOTS` (which local folders may be indexed) and keep `RUNS_PER_MINUTE` low, since every visitor shares your Groq key.

---

## 🧪 Tests & Benchmarks

```bash
GROQ_API_KEY= pytest -q                     # 101 tests; 3 live smoke tests skip without a key
python -m pytest tests/test_backend_fixes.py -v   # regression tests for the Phase 1 fixes

python evaluation/compare_baseline.py       # naive vs AST chunking, computed on real files
python evaluation/retrieval_benchmark.py    # BM25 vs vector vs hybrid retrieval accuracy
python evaluation/free_tier_budget.py       # token plan vs Groq free-tier limits
```

---

## 💡 Architecture & Technical FAQ

### Q1: How is this system "Agentic" rather than a standard chatbot?
> *"It decomposes the goal, routes it through an explicit state graph, picks tools per step (AST index, hybrid retrieval, web search, static analysis, git history), runs an adversarial debate (Kill Agent vs Reconciler), and a deterministic Critic sends ungrounded answers back for revision with concrete feedback."*

### Q2: Why use AST parsing instead of naive text splitting?
> *"On this repository, 91% of 500-character chunks cut through a function. AST chunks are whole functions or classes with exact line numbers, which is what lets the Critic verify every citation."*

### Q3: Why is the Feasibility Scorecard framed as a project rubric rather than an absolute truth?
> *"An LLM cannot compute the probability that a startup succeeds. The score is a transparent, deterministic rubric over the agents' evidence, it shows how confident it is in that evidence, and it says so on every report."*

### Q4: Why does the system not apply patches automatically?
> *"The approved synopsis mandates read-only scope. The system explains the cause and shows a recommended pattern; a human decides. The Critic even checks that the recommended code compiles before it is shown."*

### Q5: Why combine BM25 with vector search?
> *"Embeddings capture meaning ('validate the user token') but miss exact identifiers ('ValueError', 'verify_token'); BM25 catches those. Reciprocal Rank Fusion combines both. Our retrieval benchmark measures each one separately so the trade-off is visible."*

### Q6: What happens when the free Groq tier runs out mid-demo?
> *"The client enforces the limits itself, rotates across three models, and caches answers on disk. If everything is exhausted, each agent falls back to labelled built-in output and the report marks those sections and lowers its evidence confidence, instead of failing or pretending."*
