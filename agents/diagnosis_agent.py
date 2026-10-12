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

import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from core.llm import llm_client, AGENT_MAX_TOKENS
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
    # "llm" or "fallback" (retrieval + static analysis only)
    generated_by: str = "llm"
    # Filled in by the Critic: does wrong_code match the file, does the fix parse.
    verification: Dict[str, Any] = field(default_factory=dict)

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
            "generated_by": self.generated_by,
            "verification": self.verification,
            "educational_slice": self.to_educational_slice(),
        }


@dataclass
class DiagnosisResult:
    query: str
    summary: str
    ranked_candidates: List[FaultCandidate]
    raw_response: Dict[str, Any] = field(default_factory=dict)
    trace: List[str] = field(default_factory=list)
    generation_source: str = "llm"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "candidates": [c.to_dict() for c in self.ranked_candidates],
            "educational_slices": [c.to_educational_slice() for c in self.ranked_candidates],
            "trace": self.trace,
            "generation_source": self.generation_source,
        }


DIAGNOSIS_SYSTEM_PROMPT = """You are an expert Software Debugging and Fault Localization Agent.
Your role is to analyze a reported software problem, bug, or question against the retrieved code units.

CRITICAL GROUNDING & CLARITY RULES:
1. ONLY reference files, functions, and lines that are provided in the retrieved code chunks.
2. Provide a RANKED list of candidate locations responsible for the issue (Rank 1 = most likely).
3. Do NOT invent or make up file names or functions.
4. "wrong_code" MUST be the exact problematic code lines as they exist currently.
5. "recommended_pattern" MUST be the REWRITTEN / FIXED code showing the corrected implementation (e.g. adding error handling, boundary checks, or correct API usage). It MUST NOT be identical to wrong_code.
6. Use clear, everyday English: keep it technical and direct, but avoid overly dense academic jargon.
7. Output strict JSON matching this exact schema:
{
  "summary": "Brief 1-2 sentence overview of the diagnosed problem in clear language.",
  "candidates": [
    {
      "rank": 1,
      "file_path": "exact/path/to/file.py",
      "symbol_name": "exact_function_or_class_name",
      "line_start": 10,
      "line_end": 25,
      "confidence": "high",
      "root_cause_hypothesis": "Clear explanation of why this specific code causes the problem.",
      "suggested_fix": "Clear explanation of what needs to be changed.",
      "wrong_code": "# The exact original code lines from the retrieved file",
      "correct_code": "# The corrected code implementation with fix applied",
      "why_problematic": "Plain-English explanation of why the current code fails or is risky.",
      "recommended_pattern": "# The rewritten, fixed code snippet with defensive checks or error handling",
      "explanation_of_change": "Simple, direct explanation of what the change does and why it works."
    }
  ]
}
"""


def _to_int(value: Any, default: int) -> int:
    """LLM line numbers can arrive as 12, "12", "12-20", "L12" or null."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else default


def number_lines(code: str, start_line: int) -> str:
    """Prefixes each line with its real file line number so the model can cite exact lines."""
    return "\n".join(f"{start_line + i:>5} | {line}" for i, line in enumerate((code or "").splitlines()))


def _fallback_candidate(rank: int, chunk: CodeChunk, query: str) -> Dict[str, Any]:
    """
    Candidate built without the LLM: the retrieved location plus real static
    analysis and knowledge-base notes. It does not invent a fix; it says plainly
    that the location was ranked by retrieval and needs human review.
    """
    from tools.static_analyzer import static_analyzer
    from indexer.knowledge_base import knowledge_base

    metrics = static_analyzer.analyze_code_snippet(textwrap.dedent(chunk.code or ""), chunk.name)
    kb_hits = knowledge_base.lookup(query, top_k=1)
    observations = [
        f"Cyclomatic complexity {metrics.cyclomatic_complexity}, {metrics.lines_of_code} lines (grade {metrics.maintainability_grade})."
    ] + metrics.findings
    if kb_hits:
        observations.append(f"Known pattern ({kb_hits[0].topic}): {kb_hits[0].text}")
    why = (
        f"'{chunk.name}' was ranked as a likely location by hybrid retrieval for this report. "
        "No LLM diagnosis was available, so the root cause has not been confirmed. "
        + " ".join(observations)
    )
    guidance = (
        f"# No fix was generated for {chunk.name} (LLM unavailable).\n"
        "# Review this function against the reported error:\n"
        + "\n".join(f"#  - {o}" for o in observations)
    )
    return {
        "rank": rank,
        "file_path": chunk.file_path,
        "symbol_name": chunk.name,
        "line_start": chunk.start_line,
        "line_end": chunk.end_line,
        "confidence": "low",
        "root_cause_hypothesis": why,
        "suggested_fix": "Review this location manually; re-run when the LLM is available for a full diagnosis.",
        "wrong_code": chunk.code,
        "correct_code": guidance,
        "why_problematic": why,
        "recommended_pattern": guidance,
        "explanation_of_change": "No change proposed: this candidate comes from retrieval and static analysis only.",
        "generated_by": "fallback",
    }


class DiagnosisAgent:
    def __init__(self):
        self.llm = llm_client

    def diagnose(self, nav_result: NavigationResult, feedback: Optional[Dict[str, Any]] = None) -> DiagnosisResult:
        """
        Formulates a ranked diagnosis hypothesis from candidate code chunks.

        `feedback` carries the Critic's flags and repair hints from a failed
        verification, so the revision pass is a different prompt (and not a
        cache hit on the first answer).
        """
        trace = list(nav_result.trace)
        trace.append("Diagnosis Agent received candidate code chunks. Assembling evidence prompt...")

        # Build context from chunks, with real line numbers on every code line.
        evidence_blocks = []
        for i, chunk in enumerate(nav_result.candidate_chunks, start=1):
            block = (
                f"--- Candidate Chunk #{i} ---\n"
                f"File: {chunk.file_path}\n"
                f"Symbol: {chunk.name}\n"
                f"Signature: {chunk.signature}\n"
                f"Lines: {chunk.start_line} to {chunk.end_line}\n"
                f"Code (line number | source):\n{number_lines(chunk.code, chunk.start_line)}\n"
            )
            extra = (feedback or {}).get("static_notes", {}).get(chunk.id)
            if extra:
                block += f"Static analysis: {extra}\n"
            evidence_blocks.append(block)

        evidence_text = "\n".join(evidence_blocks)
        allowed = ", ".join(f"{c.file_path}:{c.name}" for c in nav_result.candidate_chunks)

        user_prompt = (
            f"Reported Issue / Question:\n{nav_result.query}\n\n"
            f"Retrieved Code Chunks:\n{evidence_text}\n\n"
            f"You may only cite these file:symbol pairs: {allowed}.\n"
            f"Use the line numbers shown in the code for line_start and line_end. "
            f"wrong_code must be copied exactly from those lines, without the line-number prefix.\n"
            f"Analyze the problem, evaluate the code chunks, identify the faulty code lines (wrong_code), "
            f"and provide the educational comparison (why_problematic, recommended_pattern, explanation_of_change) in JSON format. "
            f"Ensure recommended_pattern is the actual corrected code and is NOT identical to wrong_code. Use clear English."
        )
        if feedback and (feedback.get("flags") or feedback.get("repair_hints")):
            user_prompt += (
                "\n\nYOUR PREVIOUS ANSWER FAILED VERIFICATION. Fix these problems:\n"
                + "\n".join(f"- {f}" for f in feedback.get("flags", []))
                + ("\nHints:\n" + "\n".join(f"- {h}" for h in feedback.get("repair_hints", [])) if feedback.get("repair_hints") else "")
            )
            trace.append(f"Revision pass with {len(feedback.get('flags', []))} critic flags in the prompt.")

        trace.append("Calling Groq LLM for root-cause analysis and fault ranking...")
        generation_source = "llm"
        try:
            json_output = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for precise code analysis
                max_tokens=AGENT_MAX_TOKENS["diagnosis"],
            )
        except Exception as e:
            trace.append(f"Diagnosis LLM call notice: {e}. Ranking retrieved locations with static analysis only.")
            generation_source = "fallback"
            fallback_candidates = [
                _fallback_candidate(idx, ch, nav_result.query)
                for idx, ch in enumerate(nav_result.candidate_chunks[:3], start=1)
            ]
            json_output = {
                "summary": (
                    f"LLM diagnosis unavailable. {len(fallback_candidates)} likely locations were ranked by "
                    f"hybrid retrieval for '{nav_result.query[:60]}'; review them manually."
                ),
                "candidates": fallback_candidates,
            }

        summary = str(json_output.get("summary") or "Fault localization completed.")
        raw_candidates = json_output.get("candidates") or []
        if not isinstance(raw_candidates, list):
            raw_candidates = []

        ranked_candidates: List[FaultCandidate] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol_name") or "")
            matched_chunk = next((c for c in nav_result.candidate_chunks if c.name == symbol), None)
            fallback_wrong = matched_chunk.code if matched_chunk else "# Buggy code implementation"
            fix_text = str(item.get("suggested_fix") or "Apply bug fix.")
            fallback_correct = item.get("correct_code") or f"# Proposed patch for {symbol}\n# {fix_text}"

            why_prob = item.get("why_problematic") or item.get("root_cause_hypothesis", "")
            rec_pat = item.get("recommended_pattern") or fallback_correct
            exp_chg = item.get("explanation_of_change") or fix_text
            file_path = str(item.get("file_path") or (matched_chunk.file_path if matched_chunk else ""))
            default_start = matched_chunk.start_line if matched_chunk else 1
            line_start = _to_int(item.get("line_start"), default_start)
            line_end = _to_int(item.get("line_end"), matched_chunk.end_line if matched_chunk else line_start)
            if line_end < line_start:
                line_start, line_end = line_end, line_start
            citation = f"{file_path}:{line_start}-{line_end} ({symbol})"
            confidence = str(item.get("confidence") or "medium").lower()
            if confidence not in ("high", "medium", "low"):
                confidence = "medium"

            cand = FaultCandidate(
                rank=_to_int(item.get("rank"), len(ranked_candidates) + 1),
                file_path=file_path,
                symbol_name=symbol,
                line_start=line_start,
                line_end=line_end,
                confidence=confidence,
                root_cause_hypothesis=str(item.get("root_cause_hypothesis") or ""),
                suggested_fix=fix_text,
                wrong_code=_strip_line_prefixes(str(item.get("wrong_code") or fallback_wrong)),
                correct_code=str(fallback_correct),
                why_problematic=str(why_prob),
                recommended_pattern=str(rec_pat),
                explanation_of_change=str(exp_chg),
                citations=[citation],
                generated_by=str(item.get("generated_by") or generation_source),
            )
            ranked_candidates.append(cand)

        ranked_candidates.sort(key=lambda c: c.rank)
        trace.append(f"Diagnosis completed with {len(ranked_candidates)} ranked candidate hypotheses.")

        return DiagnosisResult(
            query=nav_result.query,
            summary=summary,
            ranked_candidates=ranked_candidates,
            raw_response=json_output,
            trace=trace,
            generation_source=generation_source,
        )


_LINE_PREFIX_RE = re.compile(r"^\s*\d+\s*\|\s?", re.MULTILINE)


def _strip_line_prefixes(code: str) -> str:
    """Removes '  12 | ' prefixes if the model copied them from the numbered prompt."""
    lines = code.splitlines()
    if lines and sum(1 for l in lines if _LINE_PREFIX_RE.match(l)) >= max(1, len(lines) // 2):
        return _LINE_PREFIX_RE.sub("", code)
    return code
