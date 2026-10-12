"""
Roadmap & Risk Agent.
Generates an actionable 3-phase development roadmap (MVP -> Beta -> Scale)
and a technical risk mitigation matrix with defense tips for college evaluations.
"""

from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from core.llm import llm_client, AGENT_MAX_TOKENS
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
    # Kept for backwards compatibility. The official score comes from the
    # deterministic scorecard; the roadmap no longer asks the model for one.
    feasibility_score: int = 0
    feasibility_verdict: str = ""
    bear_case_critic: str = ""
    generation_source: str = "llm"
    fallback_reason: str = ""

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
            "generation_source": self.generation_source,
            "fallback_reason": self.fallback_reason,
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

        tech_parts = []
        for k, v in market.tech_stack.items():
            if isinstance(v, dict):
                choice = v.get("choice", "")
            elif isinstance(v, list):
                choice = ", ".join(str(x) for x in v)
            else:
                choice = str(v)
            tech_parts.append(f"{k}: {choice}")
        tech_summary = ", ".join(tech_parts)

        user_prompt = (
            f"Project Title: {idea.project_title}\n"
            f"Problem Statement: {idea.problem_statement}\n"
            f"MVP Features: {', '.join(idea.mvp_features)}\n"
            f"Selected Tech Stack: {tech_summary}\n"
            f"Key Differentiators: {', '.join(market.key_differentiators)}\n\n"
            f"Generate the 3-phase roadmap, risk matrix and evaluation tips in the required JSON format."
        )

        generation_source, fallback_reason = "llm", ""
        try:
            json_output = self.llm.generate_json(
                messages=[
                    {"role": "system", "content": ROADMAP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=AGENT_MAX_TOKENS["roadmap"],
            )
        except Exception as err:
            trace.append(f"LLM roadmap generation note ({err}). Synthesizing deterministic milestones.")
            generation_source, fallback_reason = "fallback", f"LLM unavailable: {err}"
            first_feat = idea.mvp_features[0] if idea.mvp_features else "Core Pipeline Engine"
            second_feat = idea.mvp_features[1] if len(idea.mvp_features) > 1 else "Interactive Dashboard"
            json_output = {
                "phases": [
                    {
                        "phase_number": 1,
                        "phase_name": "Phase 1: Proof of Concept & MVP",
                        "duration_weeks": "3-4 weeks",
                        "goals": ["Establish foundational data flow and verify end-to-end integration."],
                        "deliverables": [
                            f"Implement primary feature: {first_feat}",
                            "Construct local validation harness and unit tests"
                        ],
                        "exit_criteria": "Core flow functional without uncaught exceptions."
                    },
                    {
                        "phase_number": 2,
                        "phase_name": "Phase 2: Platform Maturation & Persistence",
                        "duration_weeks": "4-6 weeks",
                        "goals": ["Build out authentication, data storage, and analytics."],
                        "deliverables": [
                            f"Implement secondary feature: {second_feat}",
                            "Database indexing and asynchronous worker queues"
                        ],
                        "exit_criteria": "Persistent storage verified with sub-second response times."
                    },
                    {
                        "phase_number": 3,
                        "phase_name": "Phase 3: Production Hardening & Scale",
                        "duration_weeks": "4-6 weeks",
                        "goals": ["Perform security auditing, rate limiting, and CI/CD automation."],
                        "deliverables": [
                            "Production CI/CD deployment pipeline",
                            "Security audit, token budgeting, and observability metrics"
                        ],
                        "exit_criteria": "Production readiness checklist verified."
                    }
                ],
                "risks": [
                    {
                        "category": "Technical",
                        "risk": "Scalability bottlenecks under concurrent request spikes.",
                        "severity": "Medium",
                        "mitigation": "Introduce asynchronous background queueing and caching layer."
                    },
                    {
                        "category": "Market",
                        "risk": "Incumbent platforms replicating core capabilities.",
                        "severity": "High",
                        "mitigation": f"Focus on unique differentiators: {', '.join(market.key_differentiators[:2]) or 'Targeted problem niche'}."
                    },
                    {
                        "category": "Operational",
                        "risk": "Integration and deployment friction during user onboarding.",
                        "severity": "Medium",
                        "mitigation": "Provide containerized setups and automated environment validation scripts."
                    }
                ],
                "feasibility_score": 85,
                "feasibility_verdict": "Feasible with Defined Mitigations",
                "bear_case_critic": "Adoption friction must be minimized via automated onboarding.",
                "evaluation_tips": [
                    "Demo the live working prototype first during evaluation.",
                    "Highlight deterministic validation layers alongside AI reasoning."
                ]
            }

        default_phases = [
            RoadmapPhase(
                phase_number=1,
                phase_name="Phase 1: Proof of Concept & MVP",
                duration_weeks="3-4 weeks",
                goals=["Establish foundational data flow and verify end-to-end integration."],
                deliverables=[f"Implement primary feature: {idea.mvp_features[0] if idea.mvp_features else 'Core Engine'}", "Construct validation harness and unit tests"],
                exit_criteria="Core flow functional without uncaught exceptions.",
            ),
            RoadmapPhase(
                phase_number=2,
                phase_name="Phase 2: Platform Maturation & Persistence",
                duration_weeks="4-6 weeks",
                goals=["Build out authentication, data storage, and analytics."],
                deliverables=[f"Implement secondary feature: {idea.mvp_features[1] if len(idea.mvp_features) > 1 else 'Interactive Dashboard'}", "Database indexing and asynchronous workers"],
                exit_criteria="Persistent storage verified with sub-second response times.",
            ),
            RoadmapPhase(
                phase_number=3,
                phase_name="Phase 3: Production Hardening & Scale",
                duration_weeks="4-6 weeks",
                goals=["Perform security auditing, rate limiting, and CI/CD automation."],
                deliverables=["Production CI/CD deployment pipeline", "Security audit and observability metrics"],
                exit_criteria="Production readiness checklist verified.",
            ),
        ]

        raw_phases = json_output.get("phases") or []
        phases = [
            RoadmapPhase(
                phase_number=int(p.get("phase_number") or i + 1) if str(p.get("phase_number") or i + 1).isdigit() else i + 1,
                phase_name=str(p.get("phase_name") or f"Phase {i+1}"),
                duration_weeks=str(p.get("duration_weeks") or "4 weeks"),
                goals=[str(g) for g in (p.get("goals") or [])] if isinstance(p.get("goals"), list) else [str(p.get("goals"))],
                deliverables=[str(d) for d in (p.get("deliverables") or [])] if isinstance(p.get("deliverables"), list) else [str(p.get("deliverables"))],
                exit_criteria=str(p.get("exit_criteria") or ""),
            )
            for i, p in enumerate(raw_phases if isinstance(raw_phases, list) else [])
            if isinstance(p, dict)
        ]
        if len(phases) < 3:
            for dp in default_phases[len(phases):3]:
                phases.append(dp)

        default_risks = [
            RiskItem(
                category="Technical",
                risk="Scalability bottlenecks under concurrent request spikes.",
                severity="Medium",
                mitigation="Introduce asynchronous background queueing and caching layer.",
            ),
            RiskItem(
                category="Market",
                risk="Incumbent platforms replicating core capabilities.",
                severity="High",
                mitigation=f"Focus on unique differentiators: {', '.join(market.key_differentiators[:2]) if market.key_differentiators else 'Targeted problem niche'}.",
            ),
            RiskItem(
                category="Operational",
                risk="Integration and deployment friction during user onboarding.",
                severity="Medium",
                mitigation="Provide containerized setups and automated environment validation scripts.",
            ),
        ]

        raw_risks = json_output.get("risks") or json_output.get("risk_matrix") or json_output.get("risks_and_mitigations") or []
        risks = [
            RiskItem(
                category=str(r.get("category") or "Technical"),
                risk=str(r.get("risk")),
                severity=_normalize_risk_severity(r.get("severity")),
                mitigation=str(r.get("mitigation") or ""),
            )
            for r in (raw_risks if isinstance(raw_risks, list) else [])
            if isinstance(r, dict) and r.get("risk")
        ]
        if len(risks) < 2:
            for dr in default_risks:
                if dr.risk not in [r.risk for r in risks]:
                    risks.append(dr)
                if len(risks) >= 3:
                    break

        trace.append(f"Roadmap generated with {len(phases)} phases and {len(risks)} risk mitigations.")

        eval_tips = json_output.get("evaluation_tips") or json_output.get("tips") or []
        if not isinstance(eval_tips, list):
            eval_tips = [str(eval_tips)]
        if not eval_tips:
            eval_tips = [
                "Demo the live working prototype first during evaluation.",
                "Highlight deterministic validation layers alongside AI reasoning."
            ]

        return RoadmapAndRiskReport(
            project_title=idea.project_title,
            phases=phases,
            risks=risks,
            evaluation_tips=eval_tips,
            trace=trace,
            generation_source=generation_source,
            fallback_reason=fallback_reason,
        )


def _normalize_risk_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith(("crit", "high", "severe", "major")):
        return "High"
    if text.startswith(("low", "minor")):
        return "Low"
    return "Medium"

