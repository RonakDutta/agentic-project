"""
Vector Semantic Search for Code Chunks.
Provides semantic embedding matching using sentence-transformers (all-MiniLM-L6-v2).
Includes an offline-resilient fallback using TF-IDF + Cosine Similarity
to ensure the system runs smoothly even on restricted college networks.
"""

import logging
import numpy as np
from typing import List, Tuple, Optional
from indexer.ast_parser import CodeChunk

logger = logging.getLogger(__name__)


class VectorCodeIndex:
    def __init__(self, chunks: List[CodeChunk], prefer_neural: bool = True):
        self.chunks = chunks
        self.embeddings: Optional[np.ndarray] = None
        self.backend = "none"
        self._transformer_model = None

        if not self.chunks:
            return

        corpus_texts = [self._chunk_to_text(c) for c in self.chunks]

        # 1. Attempt neural SentenceTransformer if preferred
        if prefer_neural:
            try:
                from sentence_transformers import SentenceTransformer
                # Use a fast local timeout/check
                self._transformer_model = SentenceTransformer("all-MiniLM-L6-v2")
                raw_embeds = self._transformer_model.encode(
                    corpus_texts, convert_to_numpy=True, show_progress_bar=False
                )
                # Normalize for cosine similarity via dot product
                norms = np.linalg.norm(raw_embeds, axis=1, keepdims=True)
                norms[norms == 0] = 1e-10
                self.embeddings = raw_embeds / norms
                self.backend = "sentence-transformers"
                logger.info("[VectorIndex] Loaded neural embedding index (all-MiniLM-L6-v2).")
            except Exception as e:
                logger.warning(
                    f"[VectorIndex] Neural model unavailable ({e}). Falling back to TF-IDF semantic vectorizer."
                )

        # 2. Fallback to scikit-learn TfidfVectorizer if neural model is not active
        if self.backend == "none":
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            self._tfidf_vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                sublinear_tf=True,
                max_features=5000,
            )
            self._tfidf_matrix = self._tfidf_vectorizer.fit_transform(corpus_texts)
            self.backend = "tfidf-fallback"
            logger.info("[VectorIndex] Loaded local TF-IDF semantic vectorizer.")

    def _chunk_to_text(self, chunk: CodeChunk) -> str:
        """Constructs a dense semantic summary representation of a code chunk."""
        qual_name = f"{chunk.parent_class}.{chunk.name}" if chunk.parent_class else chunk.name
        summary = (
            f"File: {chunk.file_path}. "
            f"Symbol: {qual_name}. "
            f"Signature: {chunk.signature}. "
            f"Description: {chunk.docstring}. "
            f"Calls: {', '.join(chunk.calls)}."
        )
        return summary

    def search(self, query: str, top_k: int = 10) -> List[Tuple[CodeChunk, float]]:
        """
        Executes semantic cosine search over indexed code chunks.
        Returns top_k chunks sorted by similarity score descending.
        """
        if not self.chunks or self.backend == "none":
            return []

        if self.backend == "sentence-transformers" and self._transformer_model is not None:
            query_embed = self._transformer_model.encode([query], convert_to_numpy=True)[0]
            norm = np.linalg.norm(query_embed)
            if norm > 0:
                query_embed = query_embed / norm
            scores = np.dot(self.embeddings, query_embed)
            
        elif self.backend == "tfidf-fallback":
            from sklearn.metrics.pairwise import cosine_similarity
            q_vec = self._tfidf_vectorizer.transform([query])
            sims = cosine_similarity(self._tfidf_matrix, q_vec).flatten()
            scores = sims
        else:
            return []

        ranked_indices = np.argsort(scores)[::-1]
        results = []
        for idx in ranked_indices[:top_k]:
            score = float(scores[idx])
            if score > 0.01:
                results.append((self.chunks[idx], round(score, 4)))

        return results
