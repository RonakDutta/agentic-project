"""
Hybrid Code Retriever using Reciprocal Rank Fusion (RRF).
Merges BM25 lexical search with dense vector similarity to provide
robust retrieval for both exact symbol names and high-level conceptual questions.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from indexer.ast_parser import CodeChunk, CodebaseIndex
from indexer.bm25_search import BM25CodeIndex
from indexer.vector_search import VectorCodeIndex


@dataclass
class SearchResult:
    chunk: CodeChunk
    rrf_score: float
    bm25_score: float
    vector_score: float
    bm25_rank: Optional[int]
    vector_rank: Optional[int]
    match_type: str  # 'hybrid', 'exact_lexical', 'semantic'

    def to_dict(self):
        return {
            "chunk_id": self.chunk.id,
            "file_path": self.chunk.file_path,
            "name": self.chunk.name,
            "signature": self.chunk.signature,
            "start_line": self.chunk.start_line,
            "end_line": self.chunk.end_line,
            "docstring": self.chunk.docstring,
            "rrf_score": round(self.rrf_score, 5),
            "bm25_score": round(self.bm25_score, 3),
            "vector_score": round(self.vector_score, 3),
            "bm25_rank": self.bm25_rank,
            "vector_rank": self.vector_rank,
            "match_type": self.match_type,
        }


class HybridRetriever:
    def __init__(self, codebase_index: CodebaseIndex, prefer_neural: bool = True):
        self.codebase_index = codebase_index
        self.chunks = codebase_index.chunks

        # Initialize lexical and vector indices
        self.bm25_index = BM25CodeIndex(self.chunks)
        self.vector_index = VectorCodeIndex(self.chunks, prefer_neural=prefer_neural)

    def search(
        self, query: str, top_k: int = 5, rrf_k: int = 60
    ) -> List[SearchResult]:
        """
        Executes hybrid search using Reciprocal Rank Fusion:
        RRF(d) = sum(1 / (k + rank_i(d)))
        """
        if not self.chunks:
            return []

        # 1. Retrieve candidates from both sources
        bm25_results = self.bm25_index.search(query, top_k=top_k * 2)
        vector_results = self.vector_index.search(query, top_k=top_k * 2)

        chunk_map: Dict[str, CodeChunk] = {c.id: c for c in self.chunks}
        rrf_scores: Dict[str, float] = {}
        bm25_scores: Dict[str, float] = {}
        vector_scores: Dict[str, float] = {}
        bm25_ranks: Dict[str, int] = {}
        vector_ranks: Dict[str, int] = {}

        # 2. Score BM25 candidates
        for rank, (chunk, score) in enumerate(bm25_results, start=1):
            chunk_id = chunk.id
            bm25_scores[chunk_id] = score
            bm25_ranks[chunk_id] = rank
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + rank))

        # 3. Score Vector candidates
        for rank, (chunk, score) in enumerate(vector_results, start=1):
            chunk_id = chunk.id
            vector_scores[chunk_id] = score
            vector_ranks[chunk_id] = rank
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + rank))

        # 4. Symbol Definition Boost:
        # If the query matches the chunk's exact symbol name, prioritize the definition over callers.
        clean_query = query.strip().lower()
        for cid, chunk in chunk_map.items():
            if chunk.name.lower() == clean_query:
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.5 / rrf_k)

        # 4. Sort by RRF score descending
        sorted_chunk_ids = sorted(
            rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True
        )

        results: List[SearchResult] = []
        for cid in sorted_chunk_ids[:top_k]:
            b_rank = bm25_ranks.get(cid)
            v_rank = vector_ranks.get(cid)

            if b_rank and v_rank:
                match_type = "hybrid"
            elif b_rank:
                match_type = "exact_lexical"
            else:
                match_type = "semantic"

            res = SearchResult(
                chunk=chunk_map[cid],
                rrf_score=rrf_scores[cid],
                bm25_score=bm25_scores.get(cid, 0.0),
                vector_score=vector_scores.get(cid, 0.0),
                bm25_rank=b_rank,
                vector_rank=v_rank,
                match_type=match_type,
            )
            results.append(res)

        return results
