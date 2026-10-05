"""
BM25 Lexical Keyword Search for Source Code.
Specialized for exact identifier matching, symbol names, and error traces.
Includes code-aware tokenization (camelCase and snake_case splitting).
"""

import re
from typing import List, Tuple
from rank_bm25 import BM25Okapi
from indexer.ast_parser import CodeChunk


def tokenize_code(text: str) -> List[str]:
    """
    Code-aware tokenizer:
    Splits on punctuation and whitespace, expands camelCase and snake_case,
    and preserves both compound tokens and individual sub-words.
    """
    # Find all identifier-like tokens
    raw_tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    result_tokens: List[str] = []

    for token in raw_tokens:
        result_tokens.append(token)

        # Split snake_case
        if "_" in token:
            sub_tokens = [s for s in token.split("_") if s]
            result_tokens.extend(sub_tokens)

        # Split camelCase / numbers: e.g. "jwtAuthService" -> "jwt", "auth", "service"
        camel_parts = re.findall(r"[a-z]+|[A-Z][a-z]*|\d+", token)
        if len(camel_parts) > 1:
            result_tokens.extend([p.lower() for p in camel_parts])

    return [t for t in result_tokens if len(t) > 1]


class BM25CodeIndex:
    def __init__(self, chunks: List[CodeChunk]):
        self.chunks = chunks
        self.corpus_tokens: List[List[str]] = []

        for chunk in self.chunks:
            # Create a rich textual representation with priority weighting on symbol name
            doc_text = (
                f"{chunk.name} {chunk.name} {chunk.signature} {chunk.file_path} "
                f"{chunk.docstring} {' '.join(chunk.calls)} {chunk.code}"
            )
            tokens = tokenize_code(doc_text)
            self.corpus_tokens.append(tokens)

        if self.corpus_tokens:
            self.bm25 = BM25Okapi(self.corpus_tokens)
        else:
            self.bm25 = None

    def search(self, query: str, top_k: int = 10) -> List[Tuple[CodeChunk, float]]:
        """
        Searches the index using BM25Okapi.
        Returns top_k chunks sorted by score descending.
        """
        if not self.bm25 or not self.chunks:
            return []

        query_tokens = tokenize_code(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        # Pair with chunks and sort
        scored_chunks = list(zip(self.chunks, scores))
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # Filter out 0.0 scores
        results = [item for item in scored_chunks[:top_k] if item[1] > 0.0]
        return results
