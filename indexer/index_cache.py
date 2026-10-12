"""
Process-wide cache of parsed repositories and their retrievers.

Indexing a repository (AST parse) and building its retriever (BM25 + embeddings)
used to happen again on every request. Both are now cached per repository and
reused until a Python file is added, removed or modified (checked via file
size and mtime, which is cheap compared to re-parsing).
"""

import os
import threading
from collections import OrderedDict
from typing import Optional, Tuple

from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex

_MAX_REPOS = 8
_lock = threading.Lock()
# abs_path -> (signature, index, retriever-or-None)
_cache: "OrderedDict[str, Tuple[tuple, CodebaseIndex, object]]" = OrderedDict()


def _signature(repo_path: str, max_files: int) -> tuple:
    """Cheap fingerprint of the repo's Python files, using the indexer's own file walk."""
    indexer = ASTCodeIndexer(repo_path=repo_path, max_files=max_files)
    parts = []
    for path in indexer._collect_python_files():
        try:
            stat = os.stat(path)
            parts.append((path, stat.st_size, int(stat.st_mtime)))
        except OSError:
            continue
    return tuple(parts)


def get_index(repo_path: str, max_files: int = 400) -> CodebaseIndex:
    """Returns a cached CodebaseIndex, re-indexing only when the repo changed."""
    key = os.path.abspath(repo_path)
    sig = _signature(key, max_files)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] == sig:
            _cache.move_to_end(key)
            return cached[1]
    index = ASTCodeIndexer(repo_path=key, max_files=max_files).index()
    with _lock:
        _cache[key] = (sig, index, None)
        _cache.move_to_end(key)
        while len(_cache) > _MAX_REPOS:
            _cache.popitem(last=False)
    return index


def put_index(repo_path: str, index: CodebaseIndex, max_files: int = 400) -> None:
    """Stores an index built elsewhere (e.g. by the GitHub ingest service)."""
    key = os.path.abspath(repo_path)
    sig = _signature(key, max_files)
    with _lock:
        _cache[key] = (sig, index, None)
        _cache.move_to_end(key)
        while len(_cache) > _MAX_REPOS:
            _cache.popitem(last=False)


def get_retriever(index: CodebaseIndex, prefer_neural: bool = True):
    """Returns a HybridRetriever for this index, built once per indexed version."""
    from indexer.hybrid_retriever import HybridRetriever

    key = os.path.abspath(index.repo_path)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] is index and cached[2] is not None:
            return cached[2]
    retriever = HybridRetriever(codebase_index=index, prefer_neural=prefer_neural)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] is index:
            _cache[key] = (cached[0], index, retriever)
    return retriever


def clear() -> None:
    with _lock:
        _cache.clear()


def cached_repo_count() -> int:
    with _lock:
        return len(_cache)


def lookup(repo_path: str) -> Optional[CodebaseIndex]:
    with _lock:
        cached = _cache.get(os.path.abspath(repo_path))
        return cached[1] if cached else None
