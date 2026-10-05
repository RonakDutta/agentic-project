# Agentic AI Co-Pilot: Multi-Agent RAG System for Idea Validation & Codebase Analysis

> **Academic Project:** B.Tech (IIoT), 7th Semester Minor Project  
> **Student:** Ronak Dutta | Roll No: 01419051723  
> **Institution:** Guru Gobind Singh Indraprastha University (USAR, GGSIPU)  
> **Repository:** [https://github.com/RonakDutta/agentic-project](https://github.com/RonakDutta/agentic-project)

---

## 📌 Executive Summary
Standard Large Language Models generate answers in a single step and lack access to private project code or real-time market data. When asked to debug software or validate a startup idea, they often hallucinate unverifiable claims.

This project implements an **Agentic AI Co-Pilot** featuring a **Supervisory Multi-Agent Architecture** backed by an **AST-aware Retrieval-Augmented Generation (RAG)** pipeline and deterministic verification tooling.

The system is balanced into two 50-50 first-class pillars:
1. **Pillar 1: Codebase Diagnostic Co-Pilot:** Parses Python repositories into semantic Abstract Syntax Tree (AST) units, conducts hybrid lexical/dense retrieval, localizes fault locations with exact line numbers, and executes deterministic verification. Strictly operates in read-only mode to produce root-cause hypotheses and fix directions with human review (no automated or unsupervised code editing).
2. **Pillar 2: Idea Validation Co-Pilot:** Decomposes raw ideas into structured problem briefs, target user personas, live competitor intelligence, adversarial devil's advocate stress tests, deterministic feasibility scoring, formal PRDs with Mermaid models, and 3-phase delivery roadmaps.

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
    3. Static Code Analyzer                                            - DuckDuckGo Web Search
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
                            [ Interactive Browser Dashboard ]
                       (FastAPI + Tailwind CSS + Mermaid.js +
                        Sequential Storyboard + Session Memory)
```

---

## ⚡ Key Technical Capabilities & Innovations (Phase 9)

### 1. AST Codebase Parsing & Alias-Aware Call Graphs
Standard text chunking breaks functions in half and destroys lexical context. Inspired by *AutoCodeRover (ISSTA 2024)* and *Tree-sitter RAG*, our indexer uses Python's standard `ast` module:
* Indexes code at class and function boundaries.
* Resolves imported aliases (such as `from auth import login as do_login`).
* Maps caller and callee relationships with explicit confidence levels (`CERTAIN`, `HIGH`, `LOW`, `UNRESOLVED`).
* Dynamic dispatches and external library calls are explicitly marked as `UNRESOLVED` rather than guessing.

### 2. Static Code Analysis & Blast Radius Impact
* **Static Analyzer (`tools/static_analyzer.py`):** Calculates McCabe cyclomatic complexity, source lines of code (SLOC), and maintainability grades for indexed symbols.
* **Flow Trace Agent (`agents/flow_trace_agent.py`):** Traces execution pathways across files, generating Mermaid sequence models and highlighting unresolved external boundaries.
* **Change Impact Agent (`agents/change_impact_agent.py`):** Evaluates transitive blast radius (2 to 3 call levels), discovers associated unit tests, and computes a composite risk score (LOW, MEDIUM, HIGH, CRITICAL).

### 3. Strict Read-Only Educational Code Guidance (Task 9.2)
In accordance with our project synopsis, the system never applies unsupervised patches or edits user code:
* **Current / Risky Implementation:** Displays the exact retrieved lines from disk with file and symbol citations.
* **Why It Is Problematic:** Explains the root cause mechanism clearly.
* **Correct / Recommended Pattern:** Shows the educational fix pattern for human review.
* **Explanation of Change:** Details why the recommended approach resolves the fault.

### 4. Adversarial Kill Agent & Evidence Reconciler (Task 9.3)
Inspired by *Idea-Research*:
* **Adversarial Kill Agent (Devil's Advocate):** Specifically searches for reasons the idea may fail, including unproven user assumptions, incumbent replication threats, and distribution traps.
* **Evidence Reconciler:** Impartially balances the thesis (Value Proposition) against the antithesis (Adversarial Critique), extracting key tradeoffs and non-negotiable success preconditions.

### 5. Deterministic Feasibility Scorecard Engine (Task 9.5)
A transparent 100-point evaluation system across 7 project-defined categories:
* Problem Validation (Max 20 pts)
* Market Demand (Max 20 pts)
* Defensibility & Moat (Max 15 pts)
* Technical Feasibility (Max 15 pts)
* Go-To-Market Execution (Max 10 pts)
* Resource Efficiency (Max 10 pts)
* Risk Profile (Max 10 pts)
* **Academic Framing Disclaimer:** Emitted explicitly on all scorecards:
  `"Feasibility Score: X/100 based on the defined project rubric."`

### 6. MetaGPT-Style PRD & Architecture Engine (Task 9.4)
Generates structured Agile specifications:
* Formal User Stories (`US-01`, `US-02`) with role, goal, business benefit, and acceptance criteria.
* Prioritized Functional Requirements (`FR-01`, `FR-02` with Must Have, Should Have, Nice to Have).
* Non-Functional Requirements covering performance, security, scalability, and observability.
* 3 Interactive Mermaid Diagrams: High-Level System Architecture, Component Topology, and End-to-End Dataflow Sequence.

### 7. Persistent Conversational Follow-Up Session Engine (Task 9.1)
* Preserves multi-turn conversation history and repository context using a persistent session manager.
* Resolves anaphoric references (such as "What calls that function?" or "What is its blast radius?").
* Automatically dispatches to specialized tools (`symbol_lookup`, `callers`, `callees`, `blast_radius`, `flow_trace`).
* Uses bounded greedy token budgeting (`indexer/context_budget.py`) to respect `CONTEXT_TOKEN_BUDGET=4000`.

### 8. Programmatic Fact & Code Critic (Task 9.10)
"Agents reason, tools compute." Rather than asking an LLM to verify code lines, our Critic executes pure Python deterministic logic:
* Checks if cited files physically exist on disk.
* Verifies symbols against the AST symbol table.
* Verifies that start and end line bounds match actual physical file boundaries.

---

## 🚀 Quick Start Guide

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/RonakDutta/agentic-project.git
cd agentic-project
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file from the provided template:
```bash
cp .env.example .env
```
Ensure your free Groq API key is configured in `.env`:
```ini
GROQ_API_KEY=your_groq_api_key_here
PRIMARY_MODEL=openai/gpt-oss-120b
FAST_MODEL=openai/gpt-oss-20b
CONTEXT_TOKEN_BUDGET=4000
```

### 3. Launch the Interactive Dashboard
Start the FastAPI server:
```bash
python app.py
```
Open your web browser and visit:
👉 **`http://127.0.0.1:8000`**

---

## 🧪 Automated Test Suites & Benchmarks

Run the complete test suite (28+ automated tests):

```bash
# Run all unit and integration tests
pytest -v
```

Individual test suites:
```bash
# Phase 9A: Context Budget, Repo Map & Critic Citations
python -m pytest tests/test_phase9a.py -v

# Phase 9B: GitHub Ingest, Static Analysis, Call Graphs, Flow Trace & Blast Radius
python -m pytest tests/test_phase9b.py -v

# Phase 9C: Conversational Session, Educational Slices & Trace Schema
python -m pytest tests/test_phase9c.py -v

# Phase 9D: Feasibility Scorecard, Kill Agent, PRD & 13-Section Report
python -m pytest tests/test_phase9d.py -v

# Core Engine Tests
python -m pytest tests/test_smoke.py -v
python -m pytest tests/test_ast_parser.py -v
python -m pytest tests/test_hybrid_retriever.py -v
python -m pytest tests/test_code_agents.py -v
python -m pytest tests/test_idea_agents.py -v
python -m pytest tests/test_orchestrator.py -v
python -m pytest tests/test_app.py -v

# Quantitative Baseline Benchmark (Naive RAG vs AST RAG)
python evaluation/compare_baseline.py
```

---

## 💡 Architecture & Technical FAQ

### Q1: How is this system "Agentic" rather than a standard chatbot?
> *"A chatbot performs single-turn text completion without introspection. Our system is agentic because it performs autonomous goal decomposition, selects tools dynamically (AST indexer vs live web search), executes multi-agent debate (Kill Agent vs Reconciler), and runs a programmatic Critic that rejects ungrounded claims."*

### Q2: Why use AST parsing instead of naive text splitting?
> *"Code has rigorous grammar and indentation structure. Standard text splitters slice files at arbitrary character boundaries, corrupting class scopes and function signatures. Our AST parser preserves semantic units, extracts exact physical line numbers, and maps call graphs."*

### Q3: Why is the Feasibility Scorecard framed as a project rubric rather than an absolute truth?
> *"LLMs cannot scientifically compute startup success probabilities. To remain academically sound and transparent, our scorecard is explicitly framed as: 'Feasibility Score: X/100 based on the defined project rubric.' The score evaluates 7 concrete categories deterministically rather than making ungrounded predictions."*

### Q4: Why does the system not apply patches automatically?
> *"Our approved Minor Project synopsis mandates a strict read-only scope. Blind automatic code modifications can introduce regressions or security vulnerabilities. Our co-pilot operates as an educational advisor, presenting root-cause diagnoses, recommended patterns, and blast radius impact for human engineer review."*

### Q5: Why combine BM25 with Vector Search?
> *"Vector embeddings capture high-level conceptual similarity ('validate user token') but frequently miss exact technical identifiers like error types ('ValueError') or function names. BM25 guarantees exact keyword matching, and Reciprocal Rank Fusion combines both candidate rankings."*
