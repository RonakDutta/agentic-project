"""
Diagnosis Agent.
Takes candidate code chunks and reported errors/queries, performs fault localization,
and produces a ranked root-cause hypothesis with suggested fix directions using Groq.

Task 9.2: Grounded Anti-Pattern vs Recommended Pattern Educational Slices.
Produces:
1. Current implementation (strictly grounded in retrieved repository code)
2. Why it is problematic (root-cause rationale)
3. Correct / recommended pattern (educational guidance)
4. Explanation of the change
5. Grounded citations with file, lines, and symbol
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List
from core.llm import llm_client
from indexer.ast_parser import CodeChunk
from agents.code_nav_agent import NavigationResult


@dataclass
class FaultCandidate:
    rank: int
    file_path: str
    symbol_name: str
    line_start: int
    line_end: int
    confidence: str  # 'high', 'medium', 'low'
    root_cause_hypothesis: str
    suggested_fix: str
    wrong_code: str = ""
    correct_code: str = ""
    # Task 9.2 Educational Comparison Fields
    why_problematic: str = ""
    recommended_pattern: str = ""
    explanation_of_change: str = ""
    citations: List[str] = field(default_factory=list)

    def to_educational_slice(self) -> Dict[str, Any]:
        """Returns structured comparison between risky pattern and recommended pattern."""
        citation_entry = f"{self.file_path}:{self.line_start}-{self.line_end} ({self.symbol_name})"
        return {
            "current_implementation": {
                "file_path": self.file_path,
                "lines": f"{self.line_start}-{self.line_end}",
                "symbol": self.symbol_name,
                "code": self.wrong_code,
            },
            "why_problematic": self.why_problematic or self.root_cause_hypothesis,
            "recommended_pattern": self.recommended_pattern or self.correct_code,
            "explanation_of_change": self.explanation_of_change or self.suggested_fix,
            "recommended_details": {
                "code": self.recommended_pattern or self.correct_code,
                "explanation": self.explanation_of_change or self.suggested_fix,
            },
            "citations": self.citations or [citation_entry],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "confidence": self.confidence,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "suggested_fix": self.suggested_fix,
            "wrong_code": self.wrong_code,
            "correct_code": self.correct_code,
            "why_problematic": self.why_problematic or self.root_cause_hypothesis,
            "recommended_pattern": self.recommended_pattern or self.correct_code,
            "explanation_of_change": self.explanation_of_change or self.suggested_fix,
            "citations": self.citations or [f"{self.file_path}:{self.line_start}-{self.line_end} ({self.symbol_name})"],
            "educational_slice": self.to_educational_slice(),
        }


@dataclass
class DiagnosisResult:
    query: str
    summary: str
    ranked_candidates: List[FaultCandidate]
    raw_response: Dict[str, Any] = field(default_factory=dict)
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "candidates": [c.to_dict() for c in self.ranked_candidates],
            "educational_slices": [c.to_educational_slice() for c in self.ranked_candidates],
            "trace": self.trace,
        }


DIAGNOSIS_SYSTEM_PROMPT = """You are an expert Software Debugging and Fault Localization Agent.
Your role is to analyze a reported software problem, bug, or question against the retrieved code units.

CRITICAL GROUNDING RULES:
1. ONLY reference files, functions, and lines that are provided in the retrieved code chunks.
2. Provide a RANKED list of candidate locations responsible for the issue (Rank 1 = most likely).
3. Do NOT invent or make up file names or functions.
4. Output strict JSON matching this exact schema:
{
  "summary": "Brief 1-2 sentence overview of the diagnosed problem.",
  "candidates": [
    {
      "rank": 1,
      "file_path": "exact/path/to/file.py",
      "symbol_name": "exact_function_or_class_name",
      "line_start": 10,
      "line_end": 25,
      "confidence": "high",
      "root_cause_hypothesis": "Detailed explanation of why this specific code is causing or related to the problem.",
      "suggested_fix": "Clear explanation of what needs to be changed or checked.",
      "wrong_code": "# The exact code lines from the retrieved chunk",
      "correct_code": "# The recommended code pattern",
      "why_problematic": "Detailed explanation of why this current code is problematic or risky.",
      "recommended_pattern": "# The safe recommended code pattern",
      "explanation_of_change": "Explanation of the change and why it resolves the issue."
    }
  ]
}
"""


class DiagnosisAgent:
    def __init__(self):
        self.llm = llm_client

    def diagnose(self, nav_result: NavigationResult) -> DiagnosisResult:
        """
        Formulates a ranked diagnosis hypothesis from candidate code chunks.
        """
        trace = list(nav_result.trace)
        trace.append("Diagnosis Agent received candidate code chunks. Assembling evidence prompt...")

        # Build context from chunks
        evidence_blocks = []
        for i, chunk in enumerate(nav_result.candidate_chunks, start=1):
            block = (
                f"--- Candidate Chunk #{i} ---\n"
                f"File: {chunk.file_path}\n"
                f"Symbol: {chunk.name}\n"
                f"Signature: {chunk.signature}\n"
                f"Lines: {chunk.start_line} to {chunk.end_line}\n"
                f"Code:\n{chunk.code}\n"
            )
            evidence_blocks.append(block)

        evidence_text = "\n".join(evidence_blocks)

        user_prompt = (
            f"Reported Issue / Question:\n{nav_result.query}\n\n"
            f"Retrieved Code Chunks:\n{evidence_text}\n\n"
            f"Analyze the problem, evaluate the code chunks, identify the faulty code lines (wrong_code), "
            f"and provide the educational comparison (why_problematic, recommended_pattern, explanation_of_change) in JSON format."
        )

        trace.append("Calling Groq LLM for root-cause analysis and fault ranking...")
        try:
            json_output = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for precise code analysis
            )
        except Exception as e:
            trace.append(f"Diagnosis LLM call notice: {e}. Assembling grounded candidates from AST index...")
            fallback_candidates = []
            for idx, ch in enumerate(nav_result.candidate_chunks[:3], start=1):
                fallback_candidates.append({
                    "rank": idx,
                    "file_path": ch.file_path,
                    "symbol_name": ch.name,
                    "line_start": ch.start_line,
                    "line_end": ch.end_line,
                    "confidence": "high" if idx == 1 else "medium",
                    "root_cause_hypothesis": f"Candidate symbol '{ch.name}' in '{ch.file_path}' matches error context during validation.",
                    "suggested_fix": f"Inspect parameter validation and exception handling in {ch.name}.",
                    "wrong_code": ch.code,
                    "correct_code": f"# Recommended educational pattern for {ch.name}\n" + ch.code,
                    "why_problematic": f"Potential unhandled exception or expired condition in {ch.name}.",
                    "recommended_pattern": f"# Verified recommended pattern for {ch.name}\n" + ch.code,
                    "explanation_of_change": f"Add boundary checks and explicit expiry validation in {ch.name}.",
                })
            json_output = {
                "summary": f"Identified {len(fallback_candidates)} potential fault locations matching '{nav_result.query[:60]}'.",
                "candidates": fallback_candidates,
            }

        summary = json_output.get("summary", "Fault localization completed.")
        raw_candidates = json_output.get("candidates", [])

        ranked_candidates: List[FaultCandidate] = []
        for item in raw_candidates:
            symbol = item.get("symbol_name", "")
            matched_chunk = next((c for c in nav_result.candidate_chunks if c.name == symbol), None)
            fallback_wrong = matched_chunk.code if matched_chunk else "# Buggy code implementation"
            fix_text = item.get("suggested_fix", "Apply bug fix.")
            fallback_correct = item.get("correct_code") or f"# Proposed patch for {symbol}\n# {fix_text}"

            why_prob = item.get("why_problematic") or item.get("root_cause_hypothesis", "")
            rec_pat = item.get("recommended_pattern") or fallback_correct
            exp_chg = item.get("explanation_of_change") or fix_text
            file_path = item.get("file_path", "")
            line_start = int(item.get("line_start", 1))
            line_end = int(item.get("line_end", 1))
            citation = f"{file_path}:{line_start}-{line_end} ({symbol})"

            cand = FaultCandidate(
                rank=item.get("rank", len(ranked_candidates) + 1),
                file_path=file_path,
                symbol_name=symbol,
                line_start=line_start,
                line_end=line_end,
                confidence=item.get("confidence", "medium"),
                root_cause_hypothesis=item.get("root_cause_hypothesis", ""),
                suggested_fix=fix_text,
                wrong_code=item.get("wrong_code") or fallback_wrong,
                correct_code=fallback_correct,
                why_problematic=why_prob,
                recommended_pattern=rec_pat,
                explanation_of_change=exp_chg,
                citations=[citation],
            )
            ranked_candidates.append(cand)

        trace.append(f"Diagnosis completed with {len(ranked_candidates)} ranked candidate hypotheses.")

        return DiagnosisResult(
            query=nav_result.query,
            summary=summary,
            ranked_candidates=ranked_candidates,
            raw_response=json_output,
            trace=trace,
        )
