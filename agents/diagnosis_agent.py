"""
Diagnosis Agent.
Takes candidate code chunks and reported errors/queries, performs fault localization,
and produces a ranked root-cause hypothesis with suggested fix directions using Groq.
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
        }


@dataclass
class DiagnosisResult:
    query: str
    summary: str
    ranked_candidates: List[FaultCandidate]
    raw_response: Dict[str, Any]
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "candidates": [c.to_dict() for c in self.ranked_candidates],
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
      "suggested_fix": "Clear explanation of what needs to be changed or checked."
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
            f"Analyze the problem, evaluate the code chunks, and return the ranked diagnosis in the required JSON format."
        )

        trace.append("Calling Groq LLM for root-cause analysis and fault ranking...")
        json_output = self.llm.generate_json(
            messages=[
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # Low temperature for precise code analysis
        )

        summary = json_output.get("summary", "Fault localization completed.")
        raw_candidates = json_output.get("candidates", [])

        ranked_candidates: List[FaultCandidate] = []
        for item in raw_candidates:
            cand = FaultCandidate(
                rank=item.get("rank", len(ranked_candidates) + 1),
                file_path=item.get("file_path", ""),
                symbol_name=item.get("symbol_name", ""),
                line_start=int(item.get("line_start", 1)),
                line_end=int(item.get("line_end", 1)),
                confidence=item.get("confidence", "medium"),
                root_cause_hypothesis=item.get("root_cause_hypothesis", ""),
                suggested_fix=item.get("suggested_fix", ""),
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
