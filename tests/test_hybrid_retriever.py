"""
Phase 3 Test Suite: Verifies BM25 lexical search, semantic vector search,
and Reciprocal Rank Fusion (RRF) on both exact symbol queries and conceptual queries.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer
from indexer.hybrid_retriever import HybridRetriever
from tests.test_ast_parser import create_mock_repository


def test_hybrid_retriever():
    temp_dir = tempfile.mkdtemp(prefix="agentic_hybrid_test_")
    try:
        create_mock_repository(temp_dir)

        print("[1/4] Indexing mock repository with AST parser...")
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        codebase_index = indexer.index()
        assert len(codebase_index.chunks) > 0

        print("[2/4] Initializing HybridRetriever (BM25 + Neural all-MiniLM-L6-v2)...")
        retriever = HybridRetriever(codebase_index=codebase_index, prefer_neural=True)
        print(f"      Retriever active backend: {retriever.vector_index.backend}")

        # Test Case 1: Exact symbol query
        print("[3/4] Testing Exact Symbol Query: 'verify_token'...")
        results = retriever.search("verify_token", top_k=3)
        assert len(results) > 0
        top = results[0]
        print(f"      Rank 1: {top.chunk.id} (RRF: {top.rrf_score}, BM25 Rank: {top.bm25_rank}, Type: {top.match_type})")
        assert top.chunk.name == "verify_token"
        assert top.bm25_rank == 1

        # Test Case 2: Conceptual semantic query
        print("[4/4] Testing Conceptual Query: 'check if user session has expired'...")
        results_concept = retriever.search("check if user session has expired", top_k=3)
        assert len(results_concept) > 0
        top_concept = results_concept[0]
        print(f"      Rank 1: {top_concept.chunk.id} (RRF: {top_concept.rrf_score}, Match: {top_concept.match_type})")
        assert "verify_token" in top_concept.chunk.name or "JWTAuthService" in top_concept.chunk.name

        print("\nAll Phase 3 Hybrid Retriever tests passed successfully!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_hybrid_retriever()
