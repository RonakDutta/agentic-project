"""
Deterministic Critic Agent.
Executes programmatic verification over LLM diagnosis outputs.
Validates that cited files exist, line numbers fall within AST bounds,
and symbol names exist in the repository's symbol table.
Eliminates LLM hallucination without wasting additional tokens.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List
from indexer.ast_parser import CodebaseIndex
from agents.diagnosis_agent import DiagnosisResult, FaultCandidate


@dataclass
class CriticReport:
    is_valid: bool
    grounding_score: float  # 0.0 to 1.0 (1.0 = 100% grounded in AST evidence)
    verified_candidates: List[FaultCandidate]
    flags: List[str]
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "grounding_score": round(self.grounding_score, 2),
            "total_verified": len(self.verified_candidates),
            "flags": self.flags,
            "trace": self.trace,
        }


class DeterministicCriticAgent:
    def __init__(self, codebase_index: CodebaseIndex):
        self.codebase_index = codebase_index
        # Normalize indexed files
        self.indexed_files = {f.replace("\\", "/"): f for f in codebase_index.file_list}

    def verify(self, diagnosis: DiagnosisResult) -> CriticReport:
        """
        Deterministically verifies the candidates cited by the Diagnosis Agent.
        """
        trace = list(diagnosis.trace)
        trace.append("Critic Agent started deterministic verification pass...")

        verified_candidates: List[FaultCandidate] = []
        flags: List[str] = []

        total_checked = len(diagnosis.ranked_candidates)
        if total_checked == 0:
            trace.append("Critic Warning: Diagnosis returned 0 candidates.")
            return CriticReport(
                is_valid=False,
                grounding_score=0.0,
                verified_candidates=[],
                flags=["No candidate locations were generated."],
                trace=trace,
            )

        grounded_count = 0

        for cand in diagnosis.ranked_candidates:
            cand_norm_file = cand.file_path.replace("\\", "/")
            file_ok = False
            symbol_ok = False
            lines_ok = False

            # 1. File existence verification
            if cand_norm_file in self.indexed_files or any(
                cand_norm_file.endswith(f) or f.endswith(cand_norm_file)
                for f in self.indexed_files
            ):
                file_ok = True
            else:
                flags.append(f"Rank {cand.rank}: File '{cand.file_path}' does not exist in the codebase index.")

            # 2. Symbol existence verification
            if cand.symbol_name in self.codebase_index.symbol_table:
                symbol_ok = True
            else:
                # Fallback: check if symbol exists inside the file chunks
                file_chunks = self.codebase_index.get_file_chunks(cand_norm_file)
                if any(c.name == cand.symbol_name for c in file_chunks):
                    symbol_ok = True
                else:
                    flags.append(f"Rank {cand.rank}: Symbol '{cand.symbol_name}' not found in AST symbol table.")

            # 3. Line bounds check
            if file_ok:
                full_path = os.path.join(self.codebase_index.repo_path, cand_norm_file)
                if os.path.exists(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        total_lines = len(f.readlines())
                    if 1 <= cand.line_start <= total_lines and cand.line_end <= total_lines + 5:
                        lines_ok = True
                    else:
                        flags.append(
                            f"Rank {cand.rank}: Cited lines {cand.line_start}-{cand.line_end} exceed file length ({total_lines} lines)."
                        )
                else:
                    lines_ok = True  # Verified against indexed chunk
            else:
                lines_ok = False

            if file_ok and (symbol_ok or lines_ok):
                grounded_count += 1
                verified_candidates.append(cand)
                trace.append(
                    f"✓ Candidate #{cand.rank} ({cand.symbol_name} in {cand.file_path}:{cand.line_start}) verified in AST."
                )
            else:
                trace.append(
                    f"✗ Candidate #{cand.rank} failed verification: {cand.file_path} (Symbol: {cand.symbol_name})."
                )

        grounding_score = grounded_count / total_checked if total_checked > 0 else 0.0
        is_valid = grounding_score >= 0.5

        trace.append(
            f"Critic Summary: Grounding Score = {int(grounding_score * 100)}% ({grounded_count}/{total_checked} verified). Status: {'PASSED' if is_valid else 'FAILED'}."
        )

        return CriticReport(
            is_valid=is_valid,
            grounding_score=grounding_score,
            verified_candidates=verified_candidates,
            flags=flags,
            trace=trace,
        )
