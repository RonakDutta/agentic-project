"""
Roadmap & Risk Agent.
Generates an actionable 3-phase development roadmap (MVP -> Beta -> Scale)
and a technical risk mitigation matrix with defense tips for college evaluations.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from core.llm import llm_client
from agents.idea_agent import DecomposedIdea
from agents.market_agent import MarketAnalysis


@dataclass
class RoadmapPhase:
    phase_number: int
    phase_name: str
    duration_weeks: str
    goals: List[str]
    deliverables: List[str]
    exit_criteria: str


@dataclass
class RiskItem:
    category: str  # 'Technical', 'Operational', 'Scope'
    risk: str
    severity: str  # 'High', 'Medium', 'Low'
    mitigation: str


@dataclass
class RoadmapAndRiskReport:
    project_title: str
    phases: List[RoadmapPhase]
    risks: List[RiskItem]
    evaluation_tips: List[str]
    trace: List[str]
    feasibility_score: int = 85
    feasibility_verdict: str = "Feasible with Standard Mitigations"
    bear_case_critic: str = "Main risk involves hardware integration delays or third-party API rate limits."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "phases": [asdict(p) for p in self.phases],
            "risks": [asdict(r) for r in self.risks],
            "evaluation_tips": self.evaluation_tips,
            "trace": self.trace,
            "feasibility_score": self.feasibility_score,
            "feasibility_verdict": self.feasibility_verdict,
            "bear_case_critic": self.bear_case_critic,
        }


ROADMAP_SYSTEM_PROMPT = """You are a Technical Project Manager and Systems Engineering Specialist.
Your role is to formulate a realistic 3-phase development roadmap and a risk mitigation matrix
tailored for professional engineering standards.

CRITICAL INSTRUCTIONS:
1. Divide work into 3 distinct chronological phases:
   - Phase 1: MVP / Core Proof of Concept (Weeks 1-4)
   - Phase 2: System Integration & Alpha Validation (Weeks 5-8)
   - Phase 3: Hardening, Evaluation Benchmarks & Demo Preparation (Weeks 9-12)
2. Detail 3-4 concrete technical and scope risks with mitigations.
3. Provide 2-3 specific strategic implementation takeaways and key technical recommendations.
4. Output strict JSON matching this exact schema:
{
  "phases": [
    {
      "phase_number": 1,
      "phase_name": "Phase 1: Core Proof of Concept",
      "duration_weeks": "Weeks 1 - 4",
      "goals": ["Build foundational hardware-software pipeline"],
      "deliverables": ["Working ingestion script", "Basic telemetry schema"],
      "exit_criteria": "Telemetry data successfully saved and rendered in terminal/UI."
    }
  ],
  "risks": [
    {
      "category": "Technical",
      "risk": "Sensor packet loss or network disconnection during demo.",
      "severity": "High",
      "mitigation": "Implement local SQLite buffer on the gateway device with automatic retry sync."
    }
  ],
  "feasibility_score": 85,
  "feasibility_verdict": "Feasible with Standard Mitigations",
  "bear_case_critic": "1-2 sentence plain-English summary of what could cause this project to fail if not addressed",
  "evaluation_tips": [
    "Tip 1: Highlight the separation of concerns between ingestion and analytics."
  ]
}
"""


class RoadmapRiskAgent:
    def __init__(self):
        self.llm = llm_client

    def generate(self, idea: DecomposedIdea, market: MarketAnalysis) -> RoadmapAndRiskReport:
        """
        Synthesizes a 3-phase milestone roadmap and risk matrix.
        """
        trace = list(market.trace)
        trace.append(f"Roadmap Agent formulating development milestones for '{idea.project_title}'...")

        tech_summary = ", ".join(
            f"{k}: {v.get('choice', '')}" for k, v in market.tech_stack.items()
        )

        user_prompt = (
            f"Project Title: {idea.project_title}\n"
            f"Problem Statement: {idea.problem_statement}\n"
            f"MVP Features: {', '.join(idea.mvp_features)}\n"
            f"Selected Tech Stack: {tech_summary}\n"
            f"Key Differentiators: {', '.join(market.key_differentiators)}\n\n"
            f"Generate the 3-phase roadmap, feasibility score (0-100), verdict, bear case risk, and evaluation tips in the required JSON format."
        )

        json_output = self.llm.generate_json(
            messages=[
                {"role": "system", "content": ROADMAP_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        phases = [
            RoadmapPhase(
                phase_number=p.get("phase_number", i + 1),
                phase_name=p.get("phase_name", f"Phase {i+1}"),
                duration_weeks=p.get("duration_weeks", "4 weeks"),
                goals=p.get("goals", []),
                deliverables=p.get("deliverables", []),
                exit_criteria=p.get("exit_criteria", ""),
            )
            for i, p in enumerate(json_output.get("phases", []))
        ]

        risks = [
            RiskItem(
                category=r.get("category", "Technical"),
                risk=r.get("risk", ""),
                severity=r.get("severity", "Medium"),
                mitigation=r.get("mitigation", ""),
            )
            for r in json_output.get("risks", [])
        ]

        trace.append(f"Roadmap generated with {len(phases)} phases and {len(risks)} risk mitigations.")

        feasibility_score = int(json_output.get("feasibility_score", 85))
        feasibility_verdict = str(json_output.get("feasibility_verdict", "Feasible with Standard Mitigations"))
        bear_case_critic = str(
            json_output.get(
                "bear_case_critic",
                "High initial hardware or API integration friction could slow down user onboarding."
            )
        )

        return RoadmapAndRiskReport(
            project_title=idea.project_title,
            phases=phases,
            risks=risks,
            evaluation_tips=json_output.get("evaluation_tips", []),
            trace=trace,
            feasibility_score=feasibility_score,
            feasibility_verdict=feasibility_verdict,
            bear_case_critic=bear_case_critic,
        )

