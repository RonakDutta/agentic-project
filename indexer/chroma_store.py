"""Optional ChromaDB vector store with graceful fallback.

Synopsis Sec 9 lists ChromaDB. College machines may not have it, so this
adapter tries Chroma and falls back to the existing TF-IDF
`VectorCodeIndex` without changing call sites.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ChromaCodeStore:
    def __init__(self, collection: str = "codebase"):
        self.collection_name = collection
        self.backend = "unavailable"
        self._collection = None
        try:
            import chromadb  # type: ignore
            client = chromadb.Client()
            self._collection = client.get_or_create_collection(collection)
            self.backend = "chromadb"
        except Exception as err:
            logger.info(f"[chroma] not available, fallback active ({err})")

    def upsert(self, ids: List[str], texts: List[str]) -> Dict[str, Any]:
        if self._collection is None:
            return {"status": "fallback", "backend": self.backend, "count": len(ids)}
        try:
            self._collection.upsert(ids=ids, documents=texts)
            return {"status": "ok", "backend": "chromadb", "count": len(ids)}
        except Exception as err:
            return {"status": "error", "backend": "chromadb", "message": str(err)}

    def query(self, text: str, top_k: int = 4) -> Dict[str, Any]:
        if self._collection is None:
            return {"status": "fallback", "backend": self.backend, "hits": []}
        try:
            res = self._collection.query(query_texts=[text], n_results=top_k)
            return {"status": "ok", "backend": "chromadb", "hits": res}
        except Exception as err:
            return {"status": "error", "backend": "chromadb", "message": str(err)}


chroma_store = ChromaCodeStore()
