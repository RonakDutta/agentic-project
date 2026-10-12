"""
Adversarial Devil's Advocate (Kill Agent) and Evidence Reconciler Engine.
Inspired by Idea-Research and MetaGPT adversarial review patterns.

Task 9.3:
1. KillAgent: Proactively investigates reasons an idea could fail, identifying fatal flaws,
   incumbent moats, distribution traps, and technical over-engineering risks.
2. ReconcilerAgent: Impartially balances the thesis (FOR: value prop & differentiators)
   against the antithesis (AGAINST: fatal flaws & failure modes) to produce a calibrated verdict.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from core.llm import llm_client, AGENT_MAX_TOKENS

SEVERITIES = ("Critical", "High", "Medium")
CATEGORIES = ("Fatal Flaw", "Market & Distribution", "Competitive Moat", "Technical Bottleneck", "Regulatory & Trust")
RECONCILER_VERDICTS = ("Proceed with Defined Mitigations", "Strategic Pivot Recommended", "High Rejection Risk")


def normalize_severity(value: Any) -> str:
    """Maps 'critical', 'HIGH', 'severe', 'low' etc. onto Critical/High/Medium."""
    text = str(value or "").strip().lower()
    if text.startswith("crit") or text in ("severe", "fatal", "existential"):
        return "Critical"
    if text.startswith("high") or text == "major":
        return "High"
    return "Medium"


def normalize_category(value: Any) -> str:
    text = str(value or "").strip().lower()
    for cat in CATEGORIES:
        if text == cat.lower():
            return cat
    if "market" in text or "distribution" in text or "cac" in text:
        return "Market & Distribution"
    if "moat" in text or "compet" in text or "incumbent" in text:
        return "Competitive Moat"
    if "tech" in text or "scal" in text or "engineer" in text:
        return "Technical Bottleneck"
    if "regul" in text or "trust" in text or "legal" in text or "privacy" in text:
        return "Regulatory & Trust"
    return "Fatal Flaw"


def normalize_verdict(value: Any) -> str:
    """Maps the reconciler's free-text verdict onto one of the three allowed labels."""
    text = str(value or "").strip().lower()
    for verdict in RECONCILER_VERDICTS:
        if text == verdict.lower():
            return verdict
    if "reject" in text or "no-go" in text or "no go" in text or "abandon" in text:
        return "High Rejection Risk"
    if "pivot" in text or "refine" in text:
        return "Strategic Pivot Recommended"
    return "Proceed with Defined Mitigations"


def _str_list(value: Any, default: List[str]) -> List[str]:
    """LLM lists can come back as null, a string or a list of dicts."""
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return list(default)
    items = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("text") or item.get("title") or item.get("description") or " ".join(str(v) for v in item.values())
        if item:
            items.append(str(item))
    return items or list(default)
from agents.idea_agent import DecomposedIdea
from agents.market_agent import MarketAnalysis


@dataclass
class KillArgument:
    title: str
    category: str  # 'Fatal Flaw', 'Market & Distribution', 'Competitive Moat', 'Technical Bottleneck', 'Regulatory & Trust'
    severity: str  # 'Critical', 'High', 'Medium'
    argument: str
    counter_evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class KillReport:
    project_title: str
    fatal_flaws: List[KillArgument]
    incumbent_threats: List[str]
    distribution_traps: List[str]
    overengineering_risks: List[str]
    bear_case_summary: str
    trace: List[str] = field(default_factory=list)
    generation_source: str = "llm"
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "fatal_flaws": [f.to_dict() for f in self.fatal_flaws],
            "incumbent_threats": self.incumbent_threats,
            "distribution_traps": self.distribution_traps,
            "overengineering_risks": self.overengineering_risks,
            "bear_case_summary": self.bear_case_summary,
            "trace": self.trace,
            "generation_source": self.generation_source,
            "fallback_reason": self.fallback_reason,
        }


@dataclass
class ReconciliationResult:
    project_title: str
    verdict: str  # 'Proceed with Defined Mitigations', 'Strategic Pivot Recommended', 'High Rejection Risk'
    arguments_for: List[str]
    arguments_against: List[str]
    key_tradeoffs: List[str]
    must_have_mitigations: List[str]
    synthesis_rationale: str
    trace: List[str] = field(default_factory=list)
    generation_source: str = "llm"
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "verdict": self.verdict,
            "arguments_for": self.arguments_for,
            "arguments_against": self.arguments_against,
            "key_tradeoffs": self.key_tradeoffs,
            "must_have_mitigations": self.must_have_mitigations,
            "synthesis_rationale": self.synthesis_rationale,
            "trace": self.trace,
            "generation_source": self.generation_source,
            "fallback_reason": self.fallback_reason,
        }


KILL_AGENT_SYSTEM_PROMPT = """You are a ruthless Devil's Advocate and VC Investment Committee Critic (Kill Agent).
Your sole purpose is to ruthlessly critique a proposed startup or project idea and find every reason why it could FAIL.
Do NOT offer praise or encouragement. Challenge every unproven assumption, competitive threat, and operational trap.

CRITICAL INSTRUCTIONS:
1. Identify 2-3 specific, high-impact Fatal Flaws (existential threats to product viability) with realistic severity ('Critical', 'High', 'Medium').
2. Detail how established incumbents or open-source solutions can easily copy or crush this product (incumbent_threats).
3. Identify Customer Acquisition Cost (CAC) traps and user distribution bottlenecks (distribution_traps).
4. Flag potential technical over-engineering or hardware/scaling sinkholes (overengineering_risks).
5. Do NOT call tools, browser commands, or functions. Output pure JSON only.
6. Keep descriptions concise and punchy to minimize token usage.
7. Output strict JSON with this exact schema:
{
  "bear_case_summary": "2-3 sentences explaining the overarching existential threat to this project in clear language.",
  "fatal_flaws": [
    {
      "title": "Short title of the fatal flaw",
      "category": "Competitive Moat or Market & Distribution or Technical Bottleneck or Regulatory & Trust",
      "severity": "Critical or High or Medium",
      "argument": "Detailed 2-3 sentence argument on why this kills the product.",
      "counter_evidence": "What real-world dynamic makes this difficult to overcome."
    }
  ],
  "incumbent_threats": [
    "Threat 1: e.g. Major cloud providers or established software vendors already have native distribution.",
    "Threat 2: e.g. Existing open-source alternatives have superior developer velocity."
  ],
  "distribution_traps": [
    "Trap 1: e.g. High customer acquisition cost (CAC) with low recurring willingness to pay.",
    "Trap 2: e.g. Lengthy organizational procurement cycles outlast development runway."
  ],
  "overengineering_risks": [
    "Risk 1: e.g. Custom multi-model pipeline introduces prohibitive inference latency and cost.",
    "Risk 2: e.g. Premature distributed architecture adds unneeded operational debt."
  ]
}
"""


RECONCILER_SYSTEM_PROMPT = """You are an impartial Systems Arbiter and Product Reconciler.
Your task is to weigh the evidence FOR the project (Value Proposition, Target Personas, Key Differentiators)
against the adversarial evidence AGAINST the project (Fatal Flaws, Incumbent Threats, Distribution Traps from the Kill Agent).

Synthesize a balanced, objective verdict and define non-negotiable preconditions for success.
Do NOT call tools or browser commands. Output pure JSON only. Keep points concise.

Output strict JSON with this exact schema:
{
  "verdict": "Proceed with Defined Mitigations or Strategic Pivot Recommended or High Rejection Risk",
  "arguments_for": [
    "Core strength 1 from thesis",
    "Core strength 2 from thesis"
  ],
  "arguments_against": [
    "Primary adversarial risk 1 from Kill Agent",
    "Primary adversarial risk 2 from Kill Agent"
  ],
  "key_tradeoffs": [
    "Key engineering/business tradeoff 1",
    "Key engineering/business tradeoff 2"
  ],
  "must_have_mitigations": [
    "Concrete mitigation 1 required to survive",
    "Concrete mitigation 2 required to survive"
  ],
  "synthesis_rationale": "2-3 sentences providing an impartial summary of the debate and final recommendation."
}
"""


class KillAgent:
    """
    Adversarial Devil's Advocate identifying fatal flaws and failure modes.
    """

    def __init__(self):
        self.llm = llm_client

    def critique(self, decomposed: DecomposedIdea, market: MarketAnalysis) -> KillReport:
        trace = [f"KillAgent activated: Initiating adversarial stress-test for '{decomposed.project_title}'"]

        user_content = (
            f"Project Title: {decomposed.project_title}\n"
            f"Problem Statement: {decomposed.problem_statement}\n"
            f"Core Value Prop: {decomposed.core_value_prop}\n"
            f"Key Assumptions: {', '.join(decomposed.key_assumptions)}\n"
            f"MVP Features: {', '.join(decomposed.mvp_features)}\n"
            f"Competitors: {[c.get('name') for c in market.competitors]}\n"
            f"Differentiators: {', '.join(market.key_differentiators)}\n\n"
            "Subject this idea to a rigorous adversarial critique. Search for fatal flaws and reason why it will fail."
        )

        trace.append("Querying Groq LLM with Kill Agent Devil's Advocate persona...")
        generation_source, fallback_reason = "llm", ""
        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": KILL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=AGENT_MAX_TOKENS["kill"],
            )
        except Exception as err:
            trace.append(f"Kill Agent LLM note ({err}). Using structured adversarial stress-test fallback.")
            generation_source, fallback_reason = "fallback", f"LLM unavailable: {err}"
            res = {}

        raw_flaws = res.get("fatal_flaws") or []
        flaws: List[KillArgument] = []
        for rf in raw_flaws if isinstance(raw_flaws, list) else []:
            if not isinstance(rf, dict):
                continue
            flaws.append(
                KillArgument(
                    title=str(rf.get("title") or "Unaddressed Vulnerability"),
                    category=normalize_category(rf.get("category")),
                    severity=normalize_severity(rf.get("severity")),
                    argument=str(rf.get("argument") or "Potential failure mode in execution or defensibility."),
                    counter_evidence=str(rf.get("counter_evidence") or "Incumbents possess structural distribution advantages."),
                )
            )

        if not flaws:
            if generation_source == "llm":
                generation_source, fallback_reason = "fallback", "Model returned no fatal flaws."
            # Fallback flaws if LLM returns empty list or offline
            flaws = [
                KillArgument(
                    title="Incumbent Distribution Moat",
                    category="Competitive Moat",
                    severity="Critical",
                    argument="Dominant enterprise platforms have native integrations with customer databases and can copy core features at zero marginal cost.",
                    counter_evidence="New market entrants face high customer acquisition friction and sales resistance.",
                ),
                KillArgument(
                    title="Unit Economics & CAC Disparity",
                    category="Market & Distribution",
                    severity="High",
                    argument="Customer acquisition cost exceeds lifetime customer value during initial onboarding phases.",
                    counter_evidence="Target personas exhibit price sensitivity and low recurring willingness to pay.",
                ),
            ]

        incumbent_threats = _str_list(res.get("incumbent_threats"), [
            "Dominant enterprise platforms have native integrations with existing customer databases.",
            "Fast-follower open-source tools reduce willingness to pay for proprietary software.",
        ])
        trace.append(f"KillAgent identified {len(flaws)} potential fatal flaws and {len(incumbent_threats)} incumbent threats.")

        return KillReport(
            project_title=decomposed.project_title,
            fatal_flaws=flaws,
            incumbent_threats=incumbent_threats,
            distribution_traps=_str_list(res.get("distribution_traps"), [
                "Customer acquisition costs may exceed customer lifetime value in early stages.",
                "Lengthy organizational procurement approval cycles delay pilot conversions.",
            ]),
            overengineering_risks=_str_list(res.get("overengineering_risks"), [
                "Risk of building bespoke infrastructure rather than leveraging managed services.",
                "Overly complex multi-model pipelines create operational latency bottlenecks.",
            ]),
            bear_case_summary=str(res.get("bear_case_summary") or "High risk of incumbent replication, distribution bottlenecks, and unit economics disparity."),
            trace=trace,
            generation_source=generation_source,
            fallback_reason=fallback_reason,
        )


class ReconcilerAgent:
    """
    Impartial arbiter weighing thesis (FOR) vs antithesis (AGAINST).
    """

    def __init__(self):
        self.llm = llm_client

    def reconcile(
        self,
        decomposed: DecomposedIdea,
        market: MarketAnalysis,
        kill_report: KillReport,
    ) -> ReconciliationResult:
        trace = [f"ReconcilerAgent activated: Balancing thesis vs antithesis for '{decomposed.project_title}'"]

        user_content = (
            f"Project: {decomposed.project_title}\n"
            f"Thesis (FOR):\n"
            f"- Problem: {decomposed.problem_statement}\n"
            f"- Value Prop: {decomposed.core_value_prop}\n"
            f"- Differentiators: {', '.join(market.key_differentiators)}\n\n"
            f"Antithesis (AGAINST - Kill Agent):\n"
            f"- Bear Case: {kill_report.bear_case_summary}\n"
            f"- Fatal Flaws: {[f.title + ' (' + f.severity + ')' for f in kill_report.fatal_flaws]}\n"
            f"- Incumbent Threats: {', '.join(kill_report.incumbent_threats)}\n"
            f"- Distribution Traps: {', '.join(kill_report.distribution_traps)}\n\n"
            "Weigh both sides impartially. Formulate a calibrated verdict and non-negotiable mitigations."
        )

        trace.append("Querying Groq LLM for balanced reconciliation synthesis...")
        generation_source, fallback_reason = "llm", ""
        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": RECONCILER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=AGENT_MAX_TOKENS["reconcile"],
            )
        except Exception as err:
            trace.append(f"Reconciler LLM note ({err}). Using structured dialectical synthesis fallback.")
            generation_source, fallback_reason = "fallback", f"LLM unavailable: {err}"
            res = {}

        if res.get("verdict"):
            verdict = normalize_verdict(res.get("verdict"))
        else:
            # No model verdict: derive it from the kill report instead of defaulting to "Proceed".
            critical = sum(1 for f in kill_report.fatal_flaws if f.severity == "Critical")
            verdict = (
                "High Rejection Risk" if critical >= 2
                else "Strategic Pivot Recommended" if critical == 1
                else "Proceed with Defined Mitigations"
            )
        trace.append(f"Reconciliation verdict synthesized: '{verdict}'")

        return ReconciliationResult(
            project_title=decomposed.project_title,
            verdict=verdict,
            arguments_for=_str_list(res.get("arguments_for"), [
                f"Valid user pain point: {decomposed.core_value_prop}",
                f"Defensible niche: {', '.join(market.key_differentiators[:2]) or 'Targeted solution'}",
            ]),
            arguments_against=_str_list(res.get("arguments_against"), [
                kill_report.fatal_flaws[0].title if kill_report.fatal_flaws else "Incumbent distribution risk",
                kill_report.bear_case_summary,
            ]),
            key_tradeoffs=_str_list(res.get("key_tradeoffs"), [
                "Speed to market vs custom engineering depth",
                "Broad feature coverage vs focused niche differentiation",
            ]),
            must_have_mitigations=_str_list(res.get("must_have_mitigations"), [
                "Focus exclusively on MVP core flow to conserve runway.",
                "Secure 3 pilot user commitments prior to large-scale infrastructure build.",
            ]),
            synthesis_rationale=str(res.get("synthesis_rationale") or "The idea addresses a real problem but must navigate distribution headwinds with lean execution."),
            trace=trace,
            generation_source=generation_source,
            fallback_reason=fallback_reason,
        )


kill_agent = KillAgent()
reconciler_agent = ReconcilerAgent()
