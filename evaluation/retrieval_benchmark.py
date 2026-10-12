"""
Code Retrieval Benchmark (BM25 vs Vector vs Hybrid RRF).

Indexes this project's own source code and asks plain-English questions that
describe a function WITHOUT naming it. Each question has one gold answer
(file + function name). Every number printed here is computed on this run;
nothing is hard-coded.

Metrics:
- Top-1 / Top-3 accuracy: gold function is the first / in the first three results.
- MRR (mean reciprocal rank): average of 1/rank of the gold function (0 if not in top 10).

Run:  python evaluation/retrieval_benchmark.py            (prints a table)
      python evaluation/retrieval_benchmark.py --json out.json
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer  # noqa: E402
from indexer.bm25_search import BM25CodeIndex  # noqa: E402
from indexer.vector_search import VectorCodeIndex  # noqa: E402
from indexer.hybrid_retriever import HybridRetriever  # noqa: E402

# (question, gold file suffix, gold function name). Questions avoid the function name.
QUERIES: List[Tuple[str, str, str]] = [
    ("parse the wait time out of a Groq rate limit error message", "core/llm.py", "_cooldown_from_error"),
    ("turn durations like 5m45s or 622ms into seconds", "core/llm.py", "_parse_duration"),
    ("remove em dashes and filler sign-offs from model text", "core/llm.py", "clean_prose"),
    ("pick the model with the most remaining token budget first", "core/llm.py", "_rank_models"),
    ("split camelCase and snake_case identifiers into search tokens", "indexer/bm25_search.py", "tokenize_code"),
    ("merge keyword and embedding rankings using reciprocal rank fusion", "indexer/hybrid_retriever.py", "search"),
    ("check that cited files, symbols and line numbers really exist on disk", "agents/critic_agent.py", "verify"),
    ("shallow clone a GitHub repository into a temporary folder and index it", "indexer/github_ingest.py", "ingest"),
    ("count branches to measure McCabe complexity of a function", "tools/static_analyzer.py", "calculate_complexity"),
    ("list every place in the repository that calls a given symbol", "indexer/ast_parser.py", "get_callers"),
    ("decide whether a question is about code or a startup idea without an LLM", "agents/orchestrator.py", "_classify_intent_deterministically"),
    ("replace words like 'that function' with the last discussed symbol", "agents/conversation_session.py", "resolve_anaphora"),
    ("score an idea on a 100 point rubric with seven categories", "agents/feasibility_scorecard.py", "evaluate"),
    ("map severity labels such as critical, HIGH or severe onto three levels", "agents/kill_agent.py", "normalize_severity"),
    ("estimate how many weeks one roadmap phase lasts", "agents/orchestrator.py", "_phase_weeks"),
    ("make free text safe to put inside a mermaid diagram label", "agents/prd_agent.py", "mermaid_label"),
    ("work out the blast radius and risk level of changing a function", "agents/change_impact_agent.py", "analyze_impact"),
    ("prefix each code line with its real line number for the prompt", "agents/diagnosis_agent.py", "number_lines"),
]


def _rank_of(results, gold_file: str, gold_name: str) -> int:
    for rank, chunk in enumerate(results, start=1):
        if chunk.name == gold_name and chunk.file_path.endswith(gold_file):
            return rank
    return 0


def _score(ranks: List[int]) -> Dict[str, float]:
    n = len(ranks) or 1
    return {
        "top1": round(sum(1 for r in ranks if r == 1) / n, 3),
        "top3": round(sum(1 for r in ranks if 1 <= r <= 3) / n, 3),
        "mrr": round(sum(1.0 / r for r in ranks if r) / n, 3),
    }


def run(prefer_neural: bool = True) -> Dict:
    started = time.time()
    index = ASTCodeIndexer(repo_path=str(ROOT_DIR), max_files=400).index()
    # Only the application code, not tests (tests mention the gold names verbatim).
    chunks = [c for c in index.chunks if not c.file_path.startswith(("tests/", "evaluation/"))]
    index.chunks = chunks

    bm25 = BM25CodeIndex(chunks)
    vector = VectorCodeIndex(chunks, prefer_neural=prefer_neural)
    hybrid = HybridRetriever(index, prefer_neural=prefer_neural)

    systems: Dict[str, Callable[[str], list]] = {
        "BM25 only": lambda q: [c for c, _ in bm25.search(q, top_k=10)],
        f"Vector only ({vector.backend})": lambda q: [c for c, _ in vector.search(q, top_k=10)],
        "Hybrid RRF (ours)": lambda q: [r.chunk for r in hybrid.search(q, top_k=10)],
    }

    per_query = []
    ranks: Dict[str, List[int]] = {name: [] for name in systems}
    for question, gold_file, gold_name in QUERIES:
        row = {"question": question, "gold": f"{gold_file}:{gold_name}"}
        for name, fn in systems.items():
            r = _rank_of(fn(question), gold_file, gold_name)
            ranks[name].append(r)
            row[name] = r
        per_query.append(row)

    return {
        "corpus": {"files": len({c.file_path for c in chunks}), "chunks": len(chunks)},
        "queries": len(QUERIES),
        "vector_backend": vector.backend,
        "results": {name: _score(r) for name, r in ranks.items()},
        "per_query": per_query,
        "seconds": round(time.time() - started, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--json", help="write full results to this JSON file")
    parser.add_argument("--no-neural", action="store_true", help="force TF-IDF vectors instead of MiniLM")
    args = parser.parse_args()

    out = run(prefer_neural=not args.no_neural)
    print("=" * 72)
    print(f"CODE RETRIEVAL BENCHMARK: {out['queries']} queries over {out['corpus']['chunks']} code chunks "
          f"in {out['corpus']['files']} files")
    print("=" * 72)
    print(f"{'System':<40} {'Top-1':>8} {'Top-3':>8} {'MRR':>8}")
    for name, m in out["results"].items():
        print(f"{name:<40} {m['top1']:>8.0%} {m['top3']:>8.0%} {m['mrr']:>8.3f}")
    print("-" * 72)
    print("Rank of the gold function per query (0 = not in top 10):")
    names = list(out["results"].keys())
    for row in out["per_query"]:
        print(f"  {row['gold']:<58} " + " ".join(f"{row[n]:>3}" for n in names))
    print(f"\nCompleted in {out['seconds']}s (vector backend: {out['vector_backend']}).")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"Saved results to {args.json}")


if __name__ == "__main__":
    main()
