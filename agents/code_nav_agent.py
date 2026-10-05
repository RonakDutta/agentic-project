"""
Code Navigation Agent.
Specialized in navigating codebases using program structure (AST) and hybrid retrieval.
Narrows down from high-level queries or error traces to candidate files, classes, and functions.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Set
from indexer.ast_parser import CodeChunk, CodebaseIndex
from indexer.hybrid_retriever import HybridRetriever, SearchResult


@dataclass
class NavigationResult:
    query: str
    identified_symbols: List[str]
    candidate_chunks: List[CodeChunk]
    retrieval_metadata: List[Dict[str, Any]]
    trace: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "identified_symbols": self.identified_symbols,
            "total_candidates": len(self.candidate_chunks),
            "candidates": [
                {
                    "id": c.id,
                    "file_path": c.file_path,
                    "name": c.name,
                    "signature": c.signature,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                }
                for c in self.candidate_chunks
            ],
            "trace": self.trace,
        }


class CodeNavigationAgent:
    def __init__(self, codebase_index: CodebaseIndex, retriever: HybridRetriever):
        self.codebase_index = codebase_index
        self.retriever = retriever

    def navigate(self, query: str, top_k: int = 4) -> NavigationResult:
        """
        Narrows down from query / error message to candidate code chunks.
        Combines explicit symbol table lookup with hybrid BM25 + dense retrieval.
        """
        trace: List[str] = []
        identified_symbols: List[str] = []
        candidate_map: Dict[str, CodeChunk] = {}
        metadata_list: List[Dict[str, Any]] = []

        trace.append(f"Received query: '{query}'")

        # 1. Deterministic Symbol Extraction:
        # Check if any declared symbol in the repository is explicitly mentioned in the query
        for sym_name in self.codebase_index.symbol_table.keys():
            if sym_name.lower() in query.lower():
                identified_symbols.append(sym_name)
                # Fetch definition chunk
                entries = self.codebase_index.symbol_table[sym_name]
                for entry in entries:
                    chunk = self.codebase_index.get_chunk_by_id(entry.get("chunk_id", ""))
                    if chunk and chunk.id not in candidate_map:
                        candidate_map[chunk.id] = chunk
                        metadata_list.append({
                            "chunk_id": chunk.id,
                            "reason": f"Exact symbol '{sym_name}' matched in query",
                            "rrf_score": 1.0,
                        })

        if identified_symbols:
            trace.append(f"Identified explicit symbols via AST symbol table: {identified_symbols}")
        else:
            trace.append("No explicit symbol names found directly in query; relying on hybrid search.")

        # 2. Hybrid Retrieval (BM25 + Semantic Vector Fusion)
        trace.append("Executing hybrid RAG search (BM25 + Dense all-MiniLM-L6-v2)...")
        search_results: List[SearchResult] = self.retriever.search(query, top_k=top_k)

        for res in search_results:
            if res.chunk.id not in candidate_map:
                candidate_map[res.chunk.id] = res.chunk
                metadata_list.append({
                    "chunk_id": res.chunk.id,
                    "reason": f"Hybrid match ({res.match_type})",
                    "rrf_score": res.rrf_score,
                })
            trace.append(
                f"Candidate retrieved: {res.chunk.id} (RRF: {round(res.rrf_score, 4)}, Match: {res.match_type})"
            )

        candidate_chunks = list(candidate_map.values())[:top_k]
        trace.append(f"Context narrowed down to {len(candidate_chunks)} candidate code units.")

        return NavigationResult(
            query=query,
            identified_symbols=identified_symbols,
            candidate_chunks=candidate_chunks,
            retrieval_metadata=metadata_list,
            trace=trace,
        )
