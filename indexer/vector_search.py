"""
Vector Semantic Search for Code Chunks.
Provides semantic embedding matching using sentence-transformers (all-MiniLM-L6-v2).
Includes an offline-resilient fallback using TF-IDF + Cosine Similarity
to ensure the system runs smoothly even on restricted college networks.
"""

import logging
import threading
import numpy as np
from typing import List, Tuple, Optional
from indexer.ast_parser import CodeChunk

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# The sentence-transformers model is loaded once per process (it takes seconds
# and ~90MB), and a failed load is remembered so offline machines do not retry
# the download on every request.
_model_lock = threading.Lock()
_shared_model = None
_model_failed = False


def get_embedding_model():
    """Returns the shared SentenceTransformer, or None when it cannot be loaded."""
    global _shared_model, _model_failed
    if _shared_model is not None or _model_failed:
        return _shared_model
    with _model_lock:
        if _shared_model is None and not _model_failed:
            try:
                from sentence_transformers import SentenceTransformer
                _shared_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                logger.info(f"[VectorIndex] Loaded neural embedding model ({EMBEDDING_MODEL_NAME}).")
            except Exception as e:
                _model_failed = True
                logger.warning(
                    f"[VectorIndex] Neural model unavailable ({e}). Using TF-IDF vectors for this process."
                )
    return _shared_model


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
            model = get_embedding_model()
            if model is not None:
                try:
                    raw_embeds = model.encode(corpus_texts, convert_to_numpy=True, show_progress_bar=False)
                    # Normalize for cosine similarity via dot product
                    norms = np.linalg.norm(raw_embeds, axis=1, keepdims=True)
                    norms[norms == 0] = 1e-10
                    self.embeddings = raw_embeds / norms
                    self._transformer_model = model
                    self.backend = "sentence-transformers"
                except Exception as e:
                    logger.warning(f"[VectorIndex] Embedding failed ({e}). Falling back to TF-IDF.")

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
        # The body matters too (error messages, condition names), but MiniLM only
        # reads ~256 tokens, so the metadata goes first and the code is clipped.
        body = " ".join((chunk.code or "").split())[:600]
        summary = (
            f"File: {chunk.file_path}. "
            f"Symbol: {qual_name}. "
            f"Signature: {chunk.signature}. "
            f"Description: {chunk.docstring}. "
            f"Calls: {', '.join(chunk.calls)}. "
            f"Code: {body}"
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
