"""
Chunking Baseline Comparison: naive fixed-size text chunks vs AST chunks.

Measures, on real files, how often each chunking strategy cuts a Python
function or class in the middle. Every number is computed on this run.

- A naive chunk "breaks" a function when the chunk starts or ends strictly
  inside that function's line range (so neither piece holds the whole function).
- An AST chunk is "intact" when its code parses on its own with ast.parse.

Run: python evaluation/compare_baseline.py [repo_path]   (default: sample_repo + this project)
"""

import ast
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer  # noqa: E402


def naive_text_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Tuple[int, int]]:
    """Standard RAG character-window chunking. Returns (start_line, end_line) per chunk, 1-based."""
    spans = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        start_line = text.count("\n", 0, start) + 1
        end_line = text.count("\n", 0, max(start, end - 1)) + 1
        spans.append((start_line, end_line))
        if end == len(text):
            break
        start += chunk_size - overlap
    return spans


def function_spans(source: str) -> List[Tuple[int, int]]:
    tree = ast.parse(source)
    return [
        (node.lineno, node.end_lineno)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.end_lineno
    ]


def evaluate_repo(repo_path: Path) -> Dict[str, float]:
    index = ASTCodeIndexer(repo_path=str(repo_path), max_files=400).index()
    naive_total = naive_broken = 0
    funcs_total = funcs_split = 0

    for rel in index.file_list:
        source = (repo_path / rel).read_text(encoding="utf-8", errors="replace")
        try:
            spans = function_spans(source)
        except SyntaxError:
            continue
        chunks = naive_text_chunks(source)
        naive_total += len(chunks)
        for c_start, c_end in chunks:
            if any(f_start < c_start <= f_end or f_start <= c_end < f_end for f_start, f_end in spans):
                naive_broken += 1
        for f_start, f_end in spans:
            funcs_total += 1
            # Split = no single naive chunk contains the whole function.
            if not any(c_start <= f_start and f_end <= c_end for c_start, c_end in chunks):
                funcs_split += 1

    ast_total = ast_intact = 0
    for chunk in index.chunks:
        ast_total += 1
        code = textwrap.dedent(chunk.code or "")
        try:
            ast.parse(code)
            ast_intact += 1
        except SyntaxError:
            try:  # methods quoted without their class
                ast.parse("class _W:\n" + textwrap.indent(code, "    "))
                ast_intact += 1
            except SyntaxError:
                pass

    return {
        "files": len(index.file_list),
        "functions": funcs_total,
        "naive_chunks": naive_total,
        "naive_chunks_cutting_a_function": naive_broken,
        "functions_split_by_naive": funcs_split,
        "ast_chunks": ast_total,
        "ast_chunks_parsing_alone": ast_intact,
    }


def _pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def run_benchmark(paths: List[Path]) -> None:
    print("=" * 78)
    print("CHUNKING BENCHMARK: NAIVE 500-CHAR WINDOWS VS AST FUNCTION/CLASS CHUNKS")
    print("=" * 78)
    for path in paths:
        r = evaluate_repo(path)
        print(f"\nRepository: {path.name} ({r['files']} Python files, {r['functions']} functions/classes)")
        print(f"  Naive chunks that cut through a function: {r['naive_chunks_cutting_a_function']}/{r['naive_chunks']}"
              f" ({_pct(r['naive_chunks_cutting_a_function'], r['naive_chunks'])})")
        print(f"  Functions no naive chunk holds whole:     {r['functions_split_by_naive']}/{r['functions']}"
              f" ({_pct(r['functions_split_by_naive'], r['functions'])})")
        print(f"  AST chunks that parse on their own:       {r['ast_chunks_parsing_alone']}/{r['ast_chunks']}"
              f" ({_pct(r['ast_chunks_parsing_alone'], r['ast_chunks'])})")
    print("\nAST chunks also carry exact start/end lines and a symbol name, which the")
    print("Deterministic Critic uses to verify every citation; naive chunks carry neither.")
    print("=" * 78)


if __name__ == "__main__":
    targets = [Path(p).resolve() for p in sys.argv[1:]] or [ROOT_DIR / "sample_repo", ROOT_DIR]
    run_benchmark(targets)
