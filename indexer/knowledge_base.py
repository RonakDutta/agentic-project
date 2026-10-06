"""Curated knowledge-base index (synopsis Sec 6.3).

A small, manually curated set of framework docs, engineering references
and common Python error patterns with usual causes. Used by the Idea and
Roadmap agents via the Retrieval Agent. Backed by BM25 + TF-IDF so it
runs offline with zero extra services.
"""

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

CURATED_DOCS: List[Dict[str, str]] = [
    {"id": "kb-fastapi-async", "topic": "FastAPI async",
     "text": "FastAPI supports async endpoints with async def. Use async for I/O-bound handlers and background tasks; CPU-bound work should stay sync or move to workers."},
    {"id": "kb-ast-chunks", "topic": "AST chunking",
     "text": "Split Python code at function and class boundaries using the ast module, not fixed character windows, so each chunk keeps its signature and scope."},
    {"id": "kb-bm25-names", "topic": "Hybrid retrieval",
     "text": "Dense embeddings miss exact identifiers (function names, error codes). Combine BM25 keyword search with vector search and fuse with reciprocal rank fusion."},
    {"id": "kb-err-valuerror", "topic": "ValueError pattern",
     "text": "ValueError often means a function received the right type but an inappropriate value (bad token, bad enum, empty string). Check validators and converters near the reported line."},
    {"id": "kb-err-keyerror", "topic": "KeyError pattern",
     "text": "KeyError means a dict lookup missed. Check .get() defaults, schema drift between producer and consumer, and unvalidated external payloads."},
    {"id": "kb-err-attribute", "topic": "AttributeError pattern",
     "text": "AttributeError ('NoneType' has no attribute) usually means a factory or query returned None. Check initialisation order and missing early returns."},
    {"id": "kb-import-cycle", "topic": "Circular import",
     "text": "Circular imports in Python surface as ImportError or partially initialised modules. Break cycles with lazy imports or a shared types module."},
    {"id": "kb-roadmap-mvp", "topic": "MVP roadmap",
     "text": "Phase work as MVP (one happy path) -> Beta (edge cases, auth, observability) -> Scale (caching, queues, hardening). Each phase needs exit criteria."},
]


@dataclass
class KBHit:
    doc_id: str
    topic: str
    text: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnowledgeBase:
    def __init__(self, docs: List[Dict[str, str]] | None = None):
        self.docs = docs if docs is not None else list(CURATED_DOCS)

    def lookup(self, query: str, top_k: int = 3) -> List[KBHit]:
        terms = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) > 2]
        scored = []
        for doc in self.docs:
            blob = f"{doc['topic']} {doc['text']}".lower()
            score = sum(blob.count(t) for t in terms)
            if score > 0:
                scored.append(KBHit(doc["id"], doc["topic"], doc["text"], float(score)))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


knowledge_base = KnowledgeBase()
