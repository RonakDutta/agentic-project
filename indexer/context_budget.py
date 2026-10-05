"""
Context Budget Manager for Codebase Intelligence.
Inspired by CodeContextKit and bounded context packing principles.
Prevents context window overflow and token waste by:
1. Ranking candidate evidence (exact definitions > callers/callees > error lines > surrounding context)
2. Preserving symbol boundaries and line numbers
3. Enforcing a strict, configurable token budget
4. Logging candidate vs selected vs discarded evidence
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceItem:
    id: str
    file_path: str
    name: str
    chunk_type: str  # 'function', 'class', 'module_header', 'traceback'
    code: str
    start_line: int
    end_line: int
    relevance_score: float = 1.0
    priority: int = 2  # 1 = highest (exact symbol/error), 2 = direct evidence, 3 = caller/callee, 4 = context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PackedContext:
    selected_items: List[EvidenceItem]
    discarded_items: List[EvidenceItem]
    total_tokens: int
    token_budget: int
    formatted_prompt_text: str
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_count": len(self.selected_items),
            "discarded_count": len(self.discarded_items),
            "total_tokens": self.total_tokens,
            "token_budget": self.token_budget,
            "summary": self.summary,
        }


class ContextBudgetManager:
    """
    Manages bounded context packing for LLM prompts.
    Greedily selects highest-priority evidence items within a token budget.
    """

    def __init__(self, default_budget: int = 3500):
        self.default_budget = default_budget

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Fast token estimator without external dependency overhead.
        Rough rule of thumb: ~3.8 characters per token for source code.
        """
        if not text:
            return 0
        char_count = len(text)
        word_count = len(text.split())
        # Blended heuristic: words + punctuation overhead
        return max(1, int((char_count / 3.8 + word_count * 1.1) / 2))

    def pack_context(
        self,
        candidates: List[EvidenceItem],
        budget: Optional[int] = None,
        header_instruction: str = "Retrieved Codebase Evidence:",
    ) -> PackedContext:
        """
        Packs candidate evidence into a bounded token context.
        """
        active_budget = budget or self.default_budget
        
        # Sort candidates: primary sort by priority (1 is highest), secondary by relevance_score desc
        sorted_candidates = sorted(
            candidates,
            key=lambda item: (item.priority, -item.relevance_score)
        )

        selected: List[EvidenceItem] = []
        discarded: List[EvidenceItem] = []
        current_tokens = self.estimate_tokens(header_instruction) + 20

        formatted_blocks: List[str] = []

        for item in sorted_candidates:
            # Build item display block
            block = (
                f"### [Evidence #{len(selected) + 1}] {item.file_path}:{item.start_line}-{item.end_line} "
                f"({item.chunk_type}: {item.name})\n"
                f"```python\n{item.code.strip()}\n```\n"
            )
            item_tokens = self.estimate_tokens(block)

            if current_tokens + item_tokens <= active_budget:
                selected.append(item)
                formatted_blocks.append(block)
                current_tokens += item_tokens
            else:
                discarded.append(item)

        formatted_prompt = header_instruction + "\n\n" + "\n".join(formatted_blocks) if formatted_blocks else "No evidence selected."

        summary = {
            "total_candidates": len(candidates),
            "selected_count": len(selected),
            "discarded_count": len(discarded),
            "estimated_tokens": current_tokens,
            "budget": active_budget,
            "budget_utilized_percent": round((current_tokens / active_budget) * 100, 1) if active_budget > 0 else 0,
            "selected_symbols": [f"{it.name} ({it.file_path})" for it in selected],
            "discarded_symbols": [f"{it.name} ({it.file_path})" for it in discarded],
        }

        return PackedContext(
            selected_items=selected,
            discarded_items=discarded,
            total_tokens=current_tokens,
            token_budget=active_budget,
            formatted_prompt_text=formatted_prompt,
            summary=summary,
        )


# Global singleton instance
context_budget_manager = ContextBudgetManager()
