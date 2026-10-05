"""
Deterministic 100-Point Feasibility Scorecard Engine.
Task 9.5: Evaluates startup and project ideas across a 7-category decision rubric.

Academic Disclaimer & Framing:
'Feasibility Score: X/100 based on the defined project rubric.'
(Project-defined decision model, not an absolute scientific claim).

Rubric Categories:
1. Problem Validation (max 20)
2. Market Demand & Opportunity (max 20)
3. Competition & Defensibility (max 15)
4. Technical Feasibility (max 15)
5. Execution & Go-To-Market (max 10)
6. Resource Requirements (max 10)
7. Risk Assessment & Mitigations (max 10)
Total: 100 Points.

Decision Thresholds:
- Score >= 75: GO (Proceed with Defined Mitigations)
- 50 <= Score < 75: PIVOT (Refine Value Proposition & Mitigate Key Risks)
- Score < 50: NO-GO (High Fatal Flaw Probability / Reconsider Thesis)
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from agents.idea_agent import DecomposedIdea
from agents.market_agent import MarketAnalysis


@dataclass
class CategoryScore:
    category_name: str
    score: int
    max_score: int
    criteria_met: List[str]
    gaps: List[str]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FeasibilityScorecard:
    project_title: str
    total_score: int  # 0 to 100
    verdict: str  # 'GO', 'PIVOT', 'NO-GO'
    verdict_summary: str
    rubric_disclaimer: str
    categories: List[CategoryScore]
    key_strengths: List[str] = field(default_factory=list)
    key_risks: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_title": self.project_title,
            "total_score": self.total_score,
            "verdict": self.verdict,
            "verdict_summary": self.verdict_summary,
            "rubric_disclaimer": self.rubric_disclaimer,
            "categories": [c.to_dict() for c in self.categories],
            "key_strengths": self.key_strengths,
            "key_risks": self.key_risks,
            "recommended_actions": self.recommended_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"### Feasibility Scorecard: {self.total_score}/100",
            f"> **Academic Rubric Disclaimer**: *{self.rubric_disclaimer}*",
            "",
            f"**Verdict**: `{self.verdict}`: {self.verdict_summary}",
            "",
            "| Evaluation Category | Score | Max | Status | Key Criteria |",
            "|:---|:---:|:---:|:---:|:---|",
        ]
        for c in self.categories:
            status = "Strong" if c.score >= (c.max_score * 0.75) else ("Moderate" if c.score >= (c.max_score * 0.5) else "Weak")
            crit = "; ".join(c.criteria_met[:2]) if c.criteria_met else "None"
            lines.append(f"| {c.category_name} | {c.score} | {c.max_score} | {status} | {crit} |")

        lines.extend([
            "",
            "**Key Strengths:**",
        ])
        for s in self.key_strengths:
            lines.append(f"- {s}")

        lines.extend([
            "",
            "**Key Vulnerabilities:**",
        ])
        for r in self.key_risks:
            lines.append(f"- {r}")

        lines.extend([
            "",
            "**Recommended Action Items:**",
        ])
        for a in self.recommended_actions:
            lines.append(f"- {a}")

        return "\n".join(lines)


class FeasibilityScorecardEngine:
    """
    Computes deterministic feasibility score using a 7-category rubric.
    Weighs evidence from Idea Decomposition, Market Analysis, Kill Agent, and Reconciler.
    """

    RUBRIC_MAX = {
        "problem_validation": 20,
        "market_demand": 20,
        "competition_defensibility": 15,
        "technical_feasibility": 15,
        "execution_gtm": 10,
        "resources_budget": 10,
        "risk_mitigation": 10,
    }

    def evaluate(
        self,
        decomposed: DecomposedIdea,
        market: MarketAnalysis,
        kill_report: Optional[Any] = None,
        reconciler_result: Optional[Any] = None,
    ) -> FeasibilityScorecard:
        categories: List[CategoryScore] = []

        # 1. Problem Validation (Max 20)
        p_score = 0
        p_criteria = []
        p_gaps = []
        if decomposed.problem_statement and len(decomposed.problem_statement) > 40:
            p_score += 8
            p_criteria.append("Articulated specific problem statement")
        else:
            p_gaps.append("Problem statement is vague or overly broad")

        if len(decomposed.target_personas) >= 2:
            p_score += 7
            p_criteria.append(f"Identified {len(decomposed.target_personas)} distinct user personas")
        elif len(decomposed.target_personas) == 1:
            p_score += 4
            p_criteria.append("Identified 1 user persona")
        else:
            p_gaps.append("No explicit user persona identified")

        if decomposed.core_value_prop and len(decomposed.core_value_prop) > 15:
            p_score += 5
            p_criteria.append("Clear core value proposition")
        else:
            p_gaps.append("Value proposition requires sharper differentiation")

        categories.append(
            CategoryScore(
                category_name="Problem Validation",
                score=min(20, p_score),
                max_score=20,
                criteria_met=p_criteria,
                gaps=p_gaps,
                rationale="Evaluates whether the problem is concrete, user-grounded, and clearly defined.",
            )
        )

        # 2. Market Demand & Opportunity (Max 20)
        m_score = 0
        m_criteria = []
        m_gaps = []
        comp_count = len(market.competitors) if market else 0
        if comp_count >= 2:
            m_score += 9
            m_criteria.append(f"Validated market demand through {comp_count} existing industry solutions")
        elif comp_count == 1:
            m_score += 5
            m_criteria.append("Identified 1 existing competitor")
        else:
            m_gaps.append("Limited search evidence of existing market solutions")

        if market and market.citations and len(market.citations) >= 2:
            m_score += 6
            m_criteria.append(f"Backed by {len(market.citations)} verified search citations")
        else:
            m_gaps.append("Few external references found for validation")

        if decomposed.mvp_features and len(decomposed.mvp_features) >= 3:
            m_score += 5
            m_criteria.append(f"Scope bounded to {len(decomposed.mvp_features)} core MVP features")
        else:
            m_score += 3
            p_criteria.append("Basic feature scope outlined")

        categories.append(
            CategoryScore(
                category_name="Market Demand & Opportunity",
                score=min(20, m_score),
                max_score=20,
                criteria_met=m_criteria,
                gaps=m_gaps,
                rationale="Evaluates commercial tailwinds, existing market validations, and external evidence.",
            )
        )

        # 3. Competition & Defensibility (Max 15)
        c_score = 0
        c_criteria = []
        c_gaps = []
        diffs = market.key_differentiators if market else []
        if diffs and len(diffs) >= 2:
            c_score += 8
            c_criteria.append(f"Articulated {len(diffs)} distinct competitive differentiators")
        elif diffs:
            c_score += 5
            c_criteria.append("Articulated 1 differentiator")
        else:
            c_gaps.append("Lacks clear defensive moat against incumbents")

        # Check against Kill Agent findings if present
        has_critical_fatal_flaw = False
        if kill_report and hasattr(kill_report, "fatal_flaws"):
            critical_flaws = [f for f in kill_report.fatal_flaws if getattr(f, "severity", "") == "Critical"]
            if critical_flaws:
                has_critical_fatal_flaw = True
                c_score = max(2, c_score - 4)
                c_gaps.append("Adversarial Kill Agent detected critical incumbent moat risk")
            else:
                c_score += 5
                c_criteria.append("Survived adversarial kill critique without existential fatal flaws")
        else:
            c_score += 4
            c_criteria.append("Standard competitive baseline")

        categories.append(
            CategoryScore(
                category_name="Competition & Defensibility",
                score=min(15, c_score),
                max_score=15,
                criteria_met=c_criteria,
                gaps=c_gaps,
                rationale="Evaluates competitive positioning, moat durability, and vulnerability to copycats.",
            )
        )

        # 4. Technical Feasibility (Max 15)
        t_score = 0
        t_criteria = []
        t_gaps = []
        stack = market.tech_stack if market else {}
        if "backend" in stack and "frontend" in stack and "database" in stack:
            t_score += 10
            t_criteria.append("Comprehensive 3-tier architecture defined (Frontend, Backend, Database)")
        elif "backend" in stack or "database" in stack:
            t_score += 6
            t_criteria.append("Partial core stack defined")
        else:
            t_gaps.append("Incomplete technical stack definition")

        if len(decomposed.key_assumptions) >= 2:
            t_score += 5
            t_criteria.append(f"Explicitly documented {len(decomposed.key_assumptions)} core engineering assumptions")
        else:
            t_score += 2
            t_gaps.append("Unstated technical assumptions introduce execution uncertainty")

        categories.append(
            CategoryScore(
                category_name="Technical Feasibility",
                score=min(15, t_score),
                max_score=15,
                criteria_met=t_criteria,
                gaps=t_gaps,
                rationale="Evaluates architectural viability, stack maturity, and engineering predictability.",
            )
        )

        # 5. Execution & Go-To-Market (Max 10)
        e_score = 0
        e_criteria = []
        e_gaps = []
        if len(decomposed.mvp_features) in range(2, 6):
            e_score += 6
            e_criteria.append("Pragmatic MVP scope enabling rapid pilot deployment")
        else:
            e_score += 3
            e_gaps.append("MVP scope is either too lean or overly bloated")

        if not has_critical_fatal_flaw:
            e_score += 3
            e_criteria.append("No blocking distribution traps identified")
        else:
            e_gaps.append("High customer acquisition friction noted in review")

        categories.append(
            CategoryScore(
                category_name="Execution & Go-To-Market",
                score=min(10, e_score),
                max_score=10,
                criteria_met=e_criteria,
                gaps=e_gaps,
                rationale="Evaluates pilot readiness, customer onboarding friction, and delivery tempo.",
            )
        )

        # 6. Resource Requirements (Max 10)
        r_score = 0
        r_criteria = []
        r_gaps = []
        # Free / low-cost open source technologies favored
        stack_text = str(stack).lower()
        if any(tool in stack_text for tool in ["fastapi", "react", "postgres", "sqlite", "python", "tailwind"]):
            r_score += 7
            r_criteria.append("Built on mature, zero-license open-source foundations")
        else:
            r_score += 4
            r_criteria.append("Standard commercial software dependencies")

        r_score += 2
        r_criteria.append("Lean initial engineering resource footprint")

        categories.append(
            CategoryScore(
                category_name="Resource Requirements",
                score=min(10, r_score),
                max_score=10,
                criteria_met=r_criteria,
                gaps=r_gaps,
                rationale="Evaluates infrastructure cost profile, licensing exposure, and development overhead.",
            )
        )

        # 7. Risk Assessment & Mitigations (Max 10)
        rk_score = 0
        rk_criteria = []
        rk_gaps = []
        if reconciler_result and hasattr(reconciler_result, "must_have_mitigations"):
            mit_count = len(reconciler_result.must_have_mitigations)
            if mit_count >= 2:
                rk_score += 8
                rk_criteria.append(f"Identified {mit_count} concrete risk mitigations via Reconciler")
            else:
                rk_score += 5
                rk_criteria.append("Identified foundational mitigations")
        else:
            rk_score += 6
            rk_criteria.append("Documented standard architectural guardrails")

        categories.append(
            CategoryScore(
                category_name="Risk Assessment & Mitigations",
                score=min(10, rk_score),
                max_score=10,
                criteria_met=rk_criteria,
                gaps=rk_gaps,
                rationale="Evaluates fallback strategies, failure containment, and operational contingencies.",
            )
        )

        # Total Calculation
        total_score = sum(c.score for c in categories)

        if total_score >= 75:
            verdict = "GO"
            verdict_summary = "Proceed with MVP development while adhering to documented mitigations."
        elif total_score >= 50:
            verdict = "PIVOT"
            verdict_summary = "Refine target persona pain points and tighten defensibility before scaling."
        else:
            verdict = "NO-GO"
            verdict_summary = "Core thesis carries critical fatal flaw probability; pivot or reconsider scope."

        disclaimer = f"Feasibility Score: {total_score}/100 based on the defined project rubric."

        strengths = []
        risks = []
        actions = []
        for c in categories:
            for cr in c.criteria_met:
                if len(strengths) < 4:
                    strengths.append(f"{c.category_name}: {cr}")
            for g in c.gaps:
                if len(risks) < 4:
                    risks.append(f"{c.category_name}: {g}")

        if verdict == "GO":
            actions.append("Freeze MVP specifications and initiate Sprint 1 foundational development.")
            actions.append("Establish automated regression testing for core customer journeys.")
        elif verdict == "PIVOT":
            actions.append("Interview 5 prospective target users to validate pain point willingness-to-pay.")
            actions.append("Re-evaluate competitive differentiation against leading market alternatives.")
        else:
            actions.append("Re-examine core technical assumptions and distribution viability.")

        return FeasibilityScorecard(
            project_title=decomposed.project_title,
            total_score=total_score,
            verdict=verdict,
            verdict_summary=verdict_summary,
            rubric_disclaimer=disclaimer,
            categories=categories,
            key_strengths=strengths,
            key_risks=risks,
            recommended_actions=actions,
        )


scorecard_engine = FeasibilityScorecardEngine()
