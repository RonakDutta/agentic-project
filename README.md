# Agentic AI Co-Pilot: Multi-Agent RAG System for Idea Validation & Codebase Analysis

> **Academic Project:** B.Tech (IIoT), 7th Semester Minor Project  
> **Student:** Ronak Dutta | Roll No: 01419051723  
> **Institution:** Guru Gobind Singh Indraprastha University (USAR, GGSIPU)  
> **Repository:** [https://github.com/RonakDutta/agentic-project](https://github.com/RonakDutta/agentic-project)

---

## 📌 Executive Summary
Standard Large Language Models generate answers in a single step and lack access to private project code or real-time market data. When asked to debug software or validate a startup idea, they often hallucinate unverifiable claims.

This project implements an **Agentic AI Co-Pilot** featuring a **Supervisory Multi-Agent Architecture** backed by an **AST-aware Retrieval-Augmented Generation (RAG)** pipeline.

The system is balanced into two 50-50 first-class pillars:
1. **Pillar 1: Codebase Diagnostic Co-Pilot:** Parses Python repositories into semantic Abstract Syntax Tree (AST) units, conducts hybrid lexical/dense retrieval, localizes fault locations with exact line numbers, and executes deterministic verification.
2. **Pillar 2: Idea Validation Co-Pilot:** Decomposes raw ideas into structured problem briefs, target user personas, market competitor intelligence, 3-phase chronological roadmaps, and technical risk matrices.

---

## 🏗️ System Architecture

```
                                  [ USER INPUT ]
                                        │
                           [ 1. Orchestrator Agent ]
                          (Intent Classifier & Planner)
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
   [ TRACK A: CODEBASE ANALYSIS ]                            [ TRACK B: IDEA VALIDATION ]
   ──────────────────────────────                            ────────────────────────────
   2. AST Codebase Indexer                                   2. Idea Decomposition Agent
      - Function & Class Chunks                                 - Problem Statement
      - Symbol Table & Call Graph                               - Target User Personas
      - Line Bounds Extraction                                  - MVP Scopes & Assumptions
   3. Hybrid Search Retriever                                3. Market & Tech Stack Agent
      - BM25 Lexical Matching                                   - DuckDuckGo Search Tool
      - Sentence-Transformers (CPU)                             - Competitor Comparison
      - Reciprocal Rank Fusion (RRF)                            - Architectural Tradeoffs
   4. Code Navigation Agent                                  4. Roadmap & Risk Agent
      - Context Narrowing                                       - 3-Phase Milestone Plan
   5. Diagnosis Agent                                           - Technical Risk Matrix
      - Ranked Fault Hypotheses                                 - Evaluation Defense Tips
   6. Deterministic Critic Agent                                        │
      - File & Line Bound Verification                                  │
           │                                                            │
           └────────────────────────────┬───────────────────────────────┘
                                        ▼
                         [ Interactive Browser Dashboard ]
                      (FastAPI + Tailwind CSS + Live Traces)
```

---

## ⚡ Key Technical Innovations

### 1. AST-Based Indexing vs. Naive Text Splitting
Standard RAG slices text every 500 characters, breaking functions in half and corrupting signatures. Inspired by *AutoCodeRover (ISSTA 2024)*, our indexer uses Python's standard `ast` module to index code at semantic boundaries:
* Every chunk is a complete function or class.
* Preserves exact start and end line numbers (`auth/jwt_handler.py: lines 21-50`).
* Maps module dependencies via an Import Graph.

### 2. Hybrid RAG with Reciprocal Rank Fusion (RRF)
Embeddings are effective for conceptual queries but fail on exact technical identifiers (`verify_token`, `KeyError`). We combine BM25 lexical search with local CPU dense embeddings (`all-MiniLM-L6-v2`) using standard RRF:
$$RRF(d) = \sum_{m \in \{\text{BM25}, \text{Dense}\}} \frac{1}{60 + r_m(d)}$$

### 3. Deterministic Critic (Zero-Hallucination Verification)
"Agents reason, tools compute." Rather than asking an LLM if a line exists, our Critic executes pure Python verification:
* Checks if the cited file physically exists on disk.
* Checks if the symbol exists in the AST Symbol Table.
* Checks if cited line ranges fall within the physical file bounds.

---

## 🚀 Quick Start Guide

### 1. Installation
Clone repository and install dependencies:
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
Ensure your free Groq API key is set in `.env`:
```ini
GROQ_API_KEY=your_groq_api_key_here
PRIMARY_MODEL=openai/gpt-oss-120b
FAST_MODEL=openai/gpt-oss-20b
```

### 3. Launch the Interactive Dashboard
Run the FastAPI web server:
```bash
python app.py
```
Open your browser and navigate to:
👉 **`http://127.0.0.1:8000`**

---

## 🧪 Automated Test Suites & Benchmarks

Run any of the standalone test suites to verify system components:

```bash
# 1. Groq Connectivity & Structured JSON Test
python tests/test_smoke.py

# 2. AST Parser & Symbol Table Extraction Test
python tests/test_ast_parser.py

# 3. Hybrid RAG (BM25 + Dense RRF) Search Test
python tests/test_hybrid_retriever.py

# 4. Code Navigation -> Diagnosis -> Critic Test
python tests/test_code_agents.py

# 5. Idea Decomposition -> Market -> Roadmap Test
python tests/test_idea_agents.py

# 6. Supervisory Orchestrator Multi-Agent Test
python tests/test_orchestrator.py

# 7. FastAPI Web Endpoints Test
python tests/test_app.py

# 8. Quantitative Baseline Benchmark (Naive RAG vs. AST RAG)
python evaluation/compare_baseline.py
```

---

## 💡 Architecture & Technical FAQ

### Q1: How is this system "Agentic" rather than a standard chatbot?
> *"A chatbot performs single-turn text completion. Our system is agentic because it performs goal decomposition, selects tools dynamically (AST indexer vs web search), executes iterative retrieval with confidence scoring, and features a deterministic Critic loop that rejects ungrounded claims."*

### Q2: Why use AST parsing instead of standard LangChain text splitters?
> *"Code has formal syntax. Standard text splitters slice code at character counts, cutting functions in half and losing indentation context. Our AST parser guarantees 100% boundary integrity, extracts exact line ranges, and constructs an explicit symbol call graph."*

### Q3: Why combine BM25 with Vector Search?
> *"Vector embeddings capture semantic concepts ('validate user session') but perform poorly on exact lexical tokens like error codes ('KeyError: user_id') and function names. BM25 guarantees exact keyword recall, and Reciprocal Rank Fusion merges both rankings."*

### Q4: Why is your Critic deterministic instead of an LLM prompt?
> *"LLM-based self-checking is susceptible to confirmation bias and wastes tokens. Our Critic uses deterministic Python logic (`os.path.exists` and AST symbol lookups) to verify that cited line numbers and files physically exist on disk."*
