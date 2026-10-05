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
from core.llm import llm_client
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "fatal_flaws": [f.to_dict() for f in self.fatal_flaws],
            "incumbent_threats": self.incumbent_threats,
            "distribution_traps": self.distribution_traps,
            "overengineering_risks": self.overengineering_risks,
            "bear_case_summary": self.bear_case_summary,
            "trace": self.trace,
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
        }


KILL_AGENT_SYSTEM_PROMPT = """You are a ruthless Devil's Advocate and VC Investment Committee Critic (Kill Agent).
Your sole purpose is to ruthlessly critique a proposed startup or project idea and find every reason why it could FAIL.
Do NOT offer praise or encouragement. Challenge every unproven assumption, competitive threat, and operational trap.

CRITICAL INSTRUCTIONS:
1. Identify 2-3 specific Fatal Flaws (existential threats to product viability).
2. Detail how established incumbents or open-source solutions can easily copy or crush this product.
3. Identify Customer Acquisition Cost (CAC) traps and user distribution bottlenecks.
4. Flag potential technical over-engineering or hardware/scaling sinkholes.
5. Output strict JSON with this exact schema:
{
  "bear_case_summary": "2-3 sentences explaining the overarching existential threat to this project.",
  "fatal_flaws": [
    {
      "title": "Short title of the fatal flaw",
      "category": "Fatal Flaw or Market & Distribution or Competitive Moat or Technical Bottleneck or Regulatory & Trust",
      "severity": "Critical or High or Medium",
      "argument": "Detailed 2-3 sentence argument on why this kills the product.",
      "counter_evidence": "What real-world dynamic makes this difficult to overcome."
    }
  ],
  "incumbent_threats": [
    "Threat 1: e.g. Major cloud providers (AWS/GCP) already offer native managed equivalents.",
    "Threat 2: e.g. Existing open-source GitHub alternatives have superior community velocity."
  ],
  "distribution_traps": [
    "Trap 1: e.g. High customer acquisition cost with low recurring willingness to pay.",
    "Trap 2: e.g. Lengthy enterprise sales cycles exceed runway."
  ],
  "overengineering_risks": [
    "Risk 1: e.g. Building custom inference models when existing APIs suffice.",
    "Risk 2: e.g. Premature microservices architecture introduces unneeded operational debt."
  ]
}
"""


RECONCILER_SYSTEM_PROMPT = """You are an impartial Systems Arbiter and Product Reconciler.
Your task is to weigh the evidence FOR the project (Value Proposition, Target Personas, Key Differentiators)
against the adversarial evidence AGAINST the project (Fatal Flaws, Incumbent Threats, Distribution Traps from the Kill Agent).

Synthesize a balanced, objective verdict and define non-negotiable preconditions for success.

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
        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": KILL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
            )
        except Exception as err:
            trace.append(f"Kill Agent LLM note ({err}). Using structured adversarial stress-test fallback.")
            res = {}

        raw_flaws = res.get("fatal_flaws", [])
        flaws: List[KillArgument] = []
        for rf in raw_flaws:
            flaws.append(
                KillArgument(
                    title=rf.get("title", "Unaddressed Vulnerability"),
                    category=rf.get("category", "Fatal Flaw"),
                    severity=rf.get("severity", "High"),
                    argument=rf.get("argument", "Potential failure mode in execution."),
                    counter_evidence=rf.get("counter_evidence", "Incumbents possess structural advantages."),
                )
            )

        if not flaws:
            # Fallback flaw if LLM returns empty list
            flaws.append(
                KillArgument(
                    title="Incumbent Distribution Advantage",
                    category="Competitive Moat",
                    severity="High",
                    argument="Dominant players possess entrenched distribution channels and zero marginal cost additions.",
                    counter_evidence="New market entrants face high customer acquisition friction.",
                )
            )

        trace.append(f"KillAgent identified {len(flaws)} potential fatal flaws and {len(res.get('incumbent_threats', []))} incumbent threats.")

        return KillReport(
            project_title=decomposed.project_title,
            fatal_flaws=flaws,
            incumbent_threats=res.get("incumbent_threats", [
                "Dominant incumbents possess existing enterprise sales pipelines.",
                "Commoditization risk from open-source alternatives."
            ]),
            distribution_traps=res.get("distribution_traps", [
                "Customer acquisition costs may exceed customer lifetime value in early stages."
            ]),
            overengineering_risks=res.get("overengineering_risks", [
                "Risk of building bespoke infrastructure rather than leveraging managed services."
            ]),
            bear_case_summary=res.get("bear_case_summary", "High risk of incumbent replication and distribution bottlenecks."),
            trace=trace,
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
        try:
            res = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": RECONCILER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
            )
        except Exception as err:
            trace.append(f"Reconciler LLM note ({err}). Using structured dialectical synthesis fallback.")
            res = {}

        verdict = res.get("verdict", "Proceed with Defined Mitigations")
        trace.append(f"Reconciliation verdict synthesized: '{verdict}'")

        return ReconciliationResult(
            project_title=decomposed.project_title,
            verdict=verdict,
            arguments_for=res.get("arguments_for", [
                f"Valid user pain point: {decomposed.core_value_prop}",
                f"Defensible niche: {', '.join(market.key_differentiators[:2]) or 'Targeted solution'}"
            ]),
            arguments_against=res.get("arguments_against", [
                kill_report.fatal_flaws[0].title if kill_report.fatal_flaws else "Incumbent distribution risk",
                kill_report.bear_case_summary
            ]),
            key_tradeoffs=res.get("key_tradeoffs", [
                "Speed to market vs custom engineering depth",
                "Broad feature coverage vs focused niche differentiation"
            ]),
            must_have_mitigations=res.get("must_have_mitigations", [
                "Focus exclusively on MVP core flow to conserve runway.",
                "Secure 3 pilot user commitments prior to large-scale infrastructure build."
            ]),
            synthesis_rationale=res.get("synthesis_rationale", "The idea addresses a real problem but must navigate distribution headwinds with lean execution."),
            trace=trace,
        )


kill_agent = KillAgent()
reconciler_agent = ReconcilerAgent()
