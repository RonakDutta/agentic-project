"""
Test Suite for Phase 9D: Idea Validation Track Expansion.
Tests:
1. Deterministic 100-Point Feasibility Scorecard Engine (Task 9.5)
2. Adversarial Kill Agent & Evidence Reconciler (Task 9.3)
3. MetaGPT-Style PRD & Mermaid Architecture Models (Task 9.4)
4. Structured 13-Section Idea Report Compilation (Task 9.14)
"""

import sys
from pathlib import Path

# UTF-8 console output for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from agents.idea_agent import DecomposedIdea
from agents.market_agent import MarketAnalysis
from agents.feasibility_scorecard import FeasibilityScorecardEngine, FeasibilityScorecard
from agents.kill_agent import KillAgent, ReconcilerAgent, KillArgument, KillReport, ReconciliationResult
from agents.prd_agent import PRDAgent, PRDDocument
from agents.orchestrator import orchestrator


def create_mock_idea_data():
    """Builds realistic decomposed idea and market analysis objects for testing."""
    decomposed = DecomposedIdea(
        raw_idea="AI-powered predictive inventory optimizer for independent neighborhood pharmacies.",
        project_title="PharmaPredict AI",
        problem_statement="Independent pharmacies lose 12% in annual profit to expired medications and unexpected stockouts of critical drugs.",
        target_personas=[
            {
                "persona": "Pharmacy Owner",
                "pain_point": "Capital tied up in expiring inventory",
                "expected_benefit": "30% reduction in medication waste"
            },
            {
                "persona": "Lead Pharmacist",
                "pain_point": "Manual daily stock reconciliations",
                "expected_benefit": "Automated reorder triggers"
            }
        ],
        core_value_prop="Predictive inventory intelligence that prevents stockouts and eliminates medicine expiration waste.",
        key_assumptions=[
            "Pharmacies utilize desktop billing/POS software with exportable CSVs or local databases.",
            "Historical sales data has at least 3 months of continuous records."
        ],
        mvp_features=[
            "CSV / POS sales telemetry ingestion worker",
            "Expiry risk forecasting model with lead-time alerts",
            "Automated weekly restocking order generation"
        ],
        trace=["Decomposed test idea"]
    )

    market = MarketAnalysis(
        competitors=[
            {
                "name": "Omnicell Enterprise",
                "summary": "Heavyweight hospital pharmacy inventory robotics.",
                "advantages": "High security, deep hospital EHR integrations.",
                "gaps": "Cost-prohibitive for neighborhood pharmacies, requires specialized hardware.",
                "reference_url": "https://www.omnicell.com"
            },
            {
                "name": "Marg ERP Pharmacy Module",
                "summary": "Standard retail accounting and inventory software.",
                "advantages": "Widespread local retail footprint.",
                "gaps": "No predictive forecasting or ML-driven expiration mitigation.",
                "reference_url": "https://www.margerp.com"
            }
        ],
        tech_stack={
            "frontend": {
                "choice": "React + Tailwind CSS",
                "rationale": "High-velocity responsive dashboard UI",
                "tradeoffs": "Requires frontend build pipeline"
            },
            "backend": {
                "choice": "FastAPI (Python 3.13)",
                "rationale": "High-concurrency async endpoints with Pydantic validation",
                "tradeoffs": "CPU-bound tasks require dedicated worker processes"
            },
            "database": {
                "choice": "PostgreSQL",
                "rationale": "ACID compliance for inventory ledger transactions",
                "tradeoffs": "Requires dedicated database instance"
            }
        },
        key_differentiators=[
            "Zero new hardware: Runs on existing pharmacy POS data",
            "Specialized expiration date decay algorithms"
        ],
        citations=[
            {"title": "Pharmacy Inventory Economics", "url": "https://example.com/pharmacy-study"}
        ],
        trace=["Market analysis test"],
    )

    return decomposed, market


def test_feasibility_scorecard():
    print("\n--- Testing Feasibility Scorecard Engine (Task 9.5) ---")
    decomposed, market = create_mock_idea_data()
    engine = FeasibilityScorecardEngine()

    scorecard = engine.evaluate(decomposed, market)

    print(f"Project: {scorecard.project_title}")
    print(f"Total Score: {scorecard.total_score}/100")
    print(f"Verdict: {scorecard.verdict}")
    print(f"Disclaimer: {scorecard.rubric_disclaimer}")
    print(f"Categories evaluated: {len(scorecard.categories)}")

    # 1. Rubric verification
    assert len(scorecard.categories) == 7
    assert 0 <= scorecard.total_score <= 100
    assert scorecard.verdict in ("GO", "PIVOT", "NO-GO")

    # 2. Academic framing honesty
    assert "based on the defined project rubric" in scorecard.rubric_disclaimer

    # 3. Serialization
    sc_dict = scorecard.to_dict()
    assert sc_dict["total_score"] == scorecard.total_score
    assert len(sc_dict["categories"]) == 7

    md = scorecard.to_markdown()
    assert "Feasibility Scorecard" in md
    assert "Academic Rubric Disclaimer" in md
    print("[OK] Feasibility Scorecard passed deterministic rubric and framing checks.")


def test_kill_and_reconciler_agents():
    print("\n--- Testing KillAgent & ReconcilerAgent (Task 9.3) ---")
    decomposed, market = create_mock_idea_data()

    # 1. Kill Agent
    kill_agent = KillAgent()
    kill_report = kill_agent.critique(decomposed, market)

    print(f"Kill Agent Bear Case: {kill_report.bear_case_summary[:100]}...")
    print(f"Fatal Flaws detected: {len(kill_report.fatal_flaws)}")
    for f in kill_report.fatal_flaws:
        print(f"  - [{f.severity}] {f.title}: {f.argument[:80]}...")

    assert len(kill_report.fatal_flaws) >= 1
    assert kill_report.bear_case_summary != ""
    assert len(kill_report.incumbent_threats) >= 1

    # 2. Reconciler Agent
    reconciler = ReconcilerAgent()
    rec_result = reconciler.reconcile(decomposed, market, kill_report)

    print(f"\nReconciler Verdict: {rec_result.verdict}")
    print(f"Rationale: {rec_result.synthesis_rationale[:100]}...")
    print(f"Key Tradeoffs: {len(rec_result.key_tradeoffs)}")
    print(f"Must-Have Mitigations: {len(rec_result.must_have_mitigations)}")

    assert rec_result.verdict != ""
    assert len(rec_result.must_have_mitigations) >= 1
    assert len(rec_result.key_tradeoffs) >= 1
    print("[OK] KillAgent and ReconcilerAgent passed adversarial debate checks.")


def test_prd_agent_and_mermaid_models():
    print("\n--- Testing PRDAgent & Mermaid Diagrams (Task 9.4) ---")
    decomposed, market = create_mock_idea_data()
    prd_agent = PRDAgent()

    prd = prd_agent.generate(decomposed, market)

    print(f"PRD Title: {prd.project_title}")
    print(f"Vision: {prd.product_vision[:80]}...")
    print(f"User Stories: {len(prd.user_stories)}")
    print(f"Functional Reqs: {len(prd.functional_requirements)}")

    assert len(prd.user_stories) >= 1
    assert prd.user_stories[0].story_id.startswith("US-")
    assert len(prd.functional_requirements) >= 2
    assert prd.functional_requirements[0].req_id.startswith("FR-")

    # Verify Mermaid diagrams
    assert "graph TD" in prd.architecture_diagram_mermaid
    assert "graph LR" in prd.component_diagram_mermaid or "graph" in prd.component_diagram_mermaid
    assert "sequenceDiagram" in prd.dataflow_diagram_mermaid

    md_view = prd.to_markdown()
    assert "## 2. User Stories & Acceptance Criteria" in md_view
    assert "## 5. System Architecture Diagrams" in md_view
    print("[OK] PRDAgent passed user stories, functional specs, and Mermaid diagram checks.")


def test_13_section_idea_report_compilation():
    print("\n--- Testing 13-Section Idea Report Compilation (Task 9.14) ---")
    query = "AI-powered predictive inventory optimizer for independent neighborhood pharmacies."
    state = orchestrator.process(query=query, force_intent="idea_validation")

    print(f"Orchestrator Intent: {state.intent}")
    print(f"Trace Steps: {len(state.execution_trace)}")
    assert state.intent == "idea_validation"

    out = state.final_output
    assert out is not None
    assert out.get("type") == "idea_validation"
    assert "sections_13" in out
    sections = out["sections_13"]
    assert len(sections) == 13, f"Expected 13 sections, got {len(sections)}"

    print("Verified 13 distinct report sections:")
    for s in sections:
        print(f"  [{s['section_number']}/13] {s['title']}")
        assert len(s["content"]) > 10

    # Verify key Phase 9 models in final_output
    assert "scorecard" in out
    assert "kill_report" in out
    assert "reconciliation" in out
    assert "prd" in out
    assert "full_report_markdown" in out

    # Verify backward compatibility with Phase 5/6 assertions
    assert "phases" in out
    assert len(out["phases"]) == 3
    assert "risks" in out
    assert len(out["risks"]) >= 2
    assert out.get("feasibility_score") is not None
    assert "based on the defined project rubric" in out.get("rubric_disclaimer", "")

    print("[OK] 13-Section Idea Report compilation and schema compatibility verified.")


if __name__ == "__main__":
    test_feasibility_scorecard()
    test_kill_and_reconciler_agents()
    test_prd_agent_and_mermaid_models()
    test_13_section_idea_report_compilation()
    print("\nAll Phase 9D tests passed successfully!")
