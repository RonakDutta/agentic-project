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
6. The quoted "current code" really exists in the cited file (it is replaced with the
   real lines from disk when it does not, and the candidate is flagged).
7. The recommended pattern compiles as Python (ast.parse, after dedent).
8. Generates deterministic repair hints if revision is required.
"""

import ast
import os
import re
import textwrap
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
    total_checked: int = 0
    # Counts behind the trace text, so the UI never has to assert anything unchecked.
    code_quote_matches: int = 0
    fixes_compiling: int = 0
    fixes_checked: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "grounding_score": round(self.grounding_score, 2),
            "total_checked": self.total_checked,
            "total_verified": len(self.verified_candidates),
            "code_quote_matches": self.code_quote_matches,
            "fixes_compiling": self.fixes_compiling,
            "fixes_checked": self.fixes_checked,
            "flags": self.flags,
            "repair_hints": self.repair_hints,
            "trace": self.trace,
        }


def _normalize_code(code: str) -> str:
    """Whitespace-insensitive form used to compare quoted code with the file."""
    return re.sub(r"\s+", "", code or "")


def compiles_as_python(code: str) -> Optional[bool]:
    """
    True/False when the snippet does/does not parse as Python; None when it is
    not code at all (only comments or blank), so prose is not counted as a failure.
    """
    body = [l for l in (code or "").splitlines() if l.strip() and not l.strip().startswith("#")]
    if not body:
        return None
    text = textwrap.dedent(code)
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        pass
    # Method bodies are often quoted without their class: retry wrapped in one.
    try:
        ast.parse("class _Wrapper:\n" + textwrap.indent(text, "    "))
        return True
    except SyntaxError:
        return False


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

        file_cache: Dict[str, List[str]] = {}
        quote_matches = 0
        fixes_compiling = 0
        fixes_checked = 0
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
                # Prefer the definition in the cited file (names like __init__ or
                # run exist in many files), then the one nearest the cited lines.
                same_name = [c for c in self.codebase_index.chunks if c.name == cand.symbol_name]
                in_file = [c for c in same_name if matched_file_key and c.file_path.replace("\\", "/") == matched_file_key]
                pool = in_file or same_name
                if pool:
                    matched_chunk = min(pool, key=lambda c: abs(c.start_line - cand.line_start))
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
                    if full_path not in file_cache:
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            file_cache[full_path] = f.read().splitlines()
                    total_lines = len(file_cache[full_path])
                    if cand.line_end < cand.line_start:
                        flags.append(f"Rank {cand.rank}: Cited range {cand.line_start}-{cand.line_end} ends before it starts.")
                    elif 1 <= cand.line_start <= total_lines and cand.line_end <= total_lines + 5:
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

            # 4b. Quoted code must exist in the file. If it does not, show the real
            # lines from disk instead of the model's version, and flag it.
            quote_ok = None
            full_path = os.path.join(self.codebase_index.repo_path, matched_file_key) if matched_file_key else ""
            file_lines = file_cache.get(full_path)
            if file_lines is None and full_path and os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    file_lines = file_cache[full_path] = f.read().splitlines()
            if file_lines and cand.wrong_code and not cand.wrong_code.lstrip().startswith("# Buggy"):
                quote_ok = _normalize_code(cand.wrong_code) in _normalize_code("\n".join(file_lines))
                if quote_ok:
                    quote_matches += 1
                else:
                    lo = max(1, min(cand.line_start, len(file_lines)))
                    hi = max(lo, min(cand.line_end, len(file_lines)))
                    if matched_chunk and (hi - lo > 80 or not lines_ok):
                        lo, hi = matched_chunk.start_line, matched_chunk.end_line
                    cand.wrong_code = "\n".join(file_lines[lo - 1:hi])
                    flags.append(
                        f"Rank {cand.rank}: Quoted code was not found in '{cand.file_path}'; replaced with the real lines {lo}-{hi} from disk."
                    )
                    repair_hints.append(f"Copy wrong_code exactly from {cand.file_path} lines {lo}-{hi}.")

            # 4c. The recommended fix must compile.
            fix_ok = compiles_as_python(cand.recommended_pattern)
            if fix_ok is not None:
                fixes_checked += 1
                if fix_ok:
                    fixes_compiling += 1
                else:
                    flags.append(f"Rank {cand.rank}: Recommended pattern for '{cand.symbol_name}' is not valid Python.")
                    repair_hints.append(f"Return syntactically valid Python for the {cand.symbol_name} fix.")
            cand.verification = {
                "file_exists": file_ok,
                "symbol_exists": symbol_ok,
                "lines_in_bounds": lines_ok,
                "quote_matches_disk": quote_ok,
                "fix_compiles": fix_ok,
            }

            # 5. Retrieved Evidence Grounding
            if retrieved_chunks:
                # Verify that either the symbol or the file was in the retrieved evidence passed to the model
                if cand.symbol_name not in retrieved_symbol_set and cand_norm_file not in retrieved_file_set:
                    flags.append(
                        f"Rank {cand.rank}: Citation for '{cand.symbol_name}' was not present in the retrieved evidence set."
                    )
                    evidence_ok = False

            # Final candidate verdict
            cand.verification["in_retrieved_evidence"] = evidence_ok
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
            total_checked=total_checked,
            code_quote_matches=quote_matches,
            fixes_compiling=fixes_compiling,
            fixes_checked=fixes_checked,
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
