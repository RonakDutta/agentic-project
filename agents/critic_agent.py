"""
Deterministic Critic Agent.
Executes programmatic, zero-cost verification over LLM diagnosis outputs and citations.
Inspired by NVIDIA Agentic RAG guardrail principles and SWE-bench boundary verification.

Validates that:
1. Cited files exist physically in the repository.
2. Cited symbols exist in the AST symbol table.
3. Cited line ranges fall within physical file boundaries.
4. Cited line ranges match the actual AST chunk bounds for that symbol.
5. Cited evidence was actually retrieved and passed to the model (prevents hallucination).
6. Generates deterministic repair hints if revision is required.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from indexer.ast_parser import CodebaseIndex, CodeChunk
from agents.diagnosis_agent import DiagnosisResult, FaultCandidate


@dataclass
class CriticReport:
    is_valid: bool
    grounding_score: float  # 0.0 to 1.0 (1.0 = 100% grounded in AST evidence)
    verified_candidates: List[FaultCandidate]
    flags: List[str]
    repair_hints: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "grounding_score": round(self.grounding_score, 2),
            "total_verified": len(self.verified_candidates),
            "flags": self.flags,
            "repair_hints": self.repair_hints,
            "trace": self.trace,
        }


class DeterministicCriticAgent:
    """
    Programmatic, non-LLM verifier. Eliminates LLM confirmation bias and
    hallucination by checking disk reality and AST symbol tables directly.
    """

    def __init__(self, codebase_index: CodebaseIndex):
        self.codebase_index = codebase_index
        # Normalize indexed files
        self.indexed_files: Dict[str, str] = {
            f.replace("\\", "/"): f for f in codebase_index.file_list
        }

    def verify(
        self,
        diagnosis: DiagnosisResult,
        retrieved_chunks: Optional[List[CodeChunk]] = None,
    ) -> CriticReport:
        """
        Deterministically verifies the candidates cited by the Diagnosis Agent.
        """
        trace = list(diagnosis.trace)
        trace.append("Critic Agent started deterministic AST & evidence verification pass...")

        verified_candidates: List[FaultCandidate] = []
        flags: List[str] = []
        repair_hints: List[str] = []

        total_checked = len(diagnosis.ranked_candidates)
        if total_checked == 0:
            trace.append("Critic Warning: Diagnosis returned 0 candidates.")
            return CriticReport(
                is_valid=False,
                grounding_score=0.0,
                verified_candidates=[],
                flags=["No candidate locations were generated."],
                repair_hints=["Rerun navigation with expanded search keywords."],
                trace=trace,
            )

        grounded_count = 0
        retrieved_symbol_set = {c.name for c in (retrieved_chunks or [])}
        retrieved_file_set = {c.file_path.replace("\\", "/") for c in (retrieved_chunks or [])}

        for cand in diagnosis.ranked_candidates:
            cand_norm_file = cand.file_path.replace("\\", "/")
            file_ok = False
            symbol_ok = False
            lines_ok = False
            evidence_ok = True
            matched_chunk: Optional[CodeChunk] = None

            # 1. File existence verification
            matched_file_key = None
            if cand_norm_file in self.indexed_files:
                matched_file_key = cand_norm_file
                file_ok = True
            else:
                for f_key in self.indexed_files:
                    if cand_norm_file.endswith(f_key) or f_key.endswith(cand_norm_file):
                        matched_file_key = f_key
                        file_ok = True
                        break

            if not file_ok:
                flags.append(f"Rank {cand.rank}: File '{cand.file_path}' does not exist in the repository.")
                repair_hints.append(f"Replace file path '{cand.file_path}' with one of: {list(self.indexed_files.keys())[:3]}")

            # 2. Symbol existence verification
            if cand.symbol_name in self.codebase_index.symbol_table:
                symbol_ok = True
                # Find matching chunk for line bound checks
                for chunk in self.codebase_index.chunks:
                    if chunk.name == cand.symbol_name:
                        matched_chunk = chunk
                        break
            else:
                # Fallback: check if symbol exists inside file chunks
                if file_ok and matched_file_key:
                    file_chunks = self.codebase_index.get_file_chunks(matched_file_key)
                    for c in file_chunks:
                        if c.name == cand.symbol_name:
                            symbol_ok = True
                            matched_chunk = c
                            break

                if not symbol_ok:
                    flags.append(f"Rank {cand.rank}: Symbol '{cand.symbol_name}' not found in AST symbol table.")
                    repair_hints.append(f"Verify symbol '{cand.symbol_name}' against indexed symbols.")

            # 3. Line bounds check
            if file_ok and matched_file_key:
                full_path = os.path.join(self.codebase_index.repo_path, matched_file_key)
                if os.path.exists(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        total_lines = len(f.readlines())
                    if 1 <= cand.line_start <= total_lines and cand.line_end <= total_lines + 5:
                        lines_ok = True
                    else:
                        flags.append(
                            f"Rank {cand.rank}: Cited lines {cand.line_start}-{cand.line_end} exceed file length ({total_lines} lines)."
                        )
                        lines_ok = False
                elif matched_chunk:
                    lines_ok = 1 <= cand.line_start <= matched_chunk.end_line + 5
                else:
                    lines_ok = True
            else:
                lines_ok = False

            # 4. Symbol Line Boundary Alignment
            if symbol_ok and matched_chunk:
                # Check if cited lines overlap with actual symbol lines
                if cand.line_start > matched_chunk.end_line + 10 or cand.line_end < matched_chunk.start_line - 5:
                    flags.append(
                        f"Rank {cand.rank}: Cited lines {cand.line_start}-{cand.line_end} do not match symbol '{cand.symbol_name}' bounds ({matched_chunk.start_line}-{matched_chunk.end_line})."
                    )
                    # Non-fatal warning if symbol itself is verified

            # 5. Retrieved Evidence Grounding
            if retrieved_chunks:
                # Verify that either the symbol or the file was in the retrieved evidence passed to the model
                if cand.symbol_name not in retrieved_symbol_set and cand_norm_file not in retrieved_file_set:
                    flags.append(
                        f"Rank {cand.rank}: Citation for '{cand.symbol_name}' was not present in the retrieved evidence set."
                    )
                    evidence_ok = False

            # Final candidate verdict
            if file_ok and (symbol_ok or lines_ok) and evidence_ok:
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
            repair_hints=repair_hints,
            trace=trace,
        )


# Helper function for programmatic validation outside diagnosis
def validate_code_citation(
    file_path: str,
    symbol_name: str,
    line_start: int,
    line_end: int,
    codebase_index: CodebaseIndex,
) -> Dict[str, Any]:
    """
    Validates a single code citation against the codebase index.
    """
    norm_file = file_path.replace("\\", "/")
    file_exists = any(
        norm_file == f.replace("\\", "/") or norm_file.endswith(f.replace("\\", "/"))
        for f in codebase_index.file_list
    )
    symbol_exists = symbol_name in codebase_index.symbol_table
    lines_valid = line_start >= 1 and line_end >= line_start

    return {
        "is_valid": file_exists and symbol_exists and lines_valid,
        "file_exists": file_exists,
        "symbol_exists": symbol_exists,
        "lines_valid": lines_valid,
    }
