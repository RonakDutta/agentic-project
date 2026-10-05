"""
Test Suite for Sub-Phase 9E:
UX Integration, End-to-End Tests, Session Continuity, and Documentation Verification.
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

from agents.orchestrator import orchestrator
from core.config import settings

SAMPLE_REPO = ROOT_DIR / "sample_repo"
TEMPLATE_PATH = ROOT_DIR / "web" / "templates" / "index.html"
README_PATH = ROOT_DIR / "README.md"


def test_template_phase9_elements():
    """Verifies that index.html contains all Phase 9 UI components and Mermaid scripts."""
    assert TEMPLATE_PATH.exists(), "index.html template must exist."
    content = TEMPLATE_PATH.read_text(encoding="utf-8")

    # 1. Mermaid.js script in head
    assert "mermaid@10/dist/mermaid.min.js" in content, "Mermaid.js library must be included in head."

    # 2. Feasibility Scorecard components (Task 9.5)
    assert "Feasibility Decision Scorecard" in content
    assert "scDisclaimerText" in content
    assert "7-Category Project Decision Rubric" in content
    assert "scScoreNum" in content
    assert "scVerdictBadge" in content

    # 3. Adversarial Kill Agent & Reconciler components (Task 9.3)
    assert "Kill Agent" in content
    assert "killBearCaseSummary" in content
    assert "fatalFlawsContainer" in content
    assert "incumbentThreatsContainer" in content
    assert "recVerdictBadge" in content
    assert "recPreconditionsContainer" in content

    # 4. MetaGPT PRD & Mermaid diagram tabs (Task 9.4)
    assert "Product Requirements Document (PRD) & Architecture" in content
    assert "userStoriesContainer" in content
    assert "functionalReqsContainer" in content
    assert "tabMermaid_architecture" in content
    assert "mermaidContainer" in content

    # 5. Read-only educational comparison components (Task 9.2)
    assert "Read-Only" in content
    assert "Educational Pattern Comparison" in content
    assert "Current / Risky Implementation" in content
    assert "Correct / Recommended Pattern" in content
    assert "Grounded Citations" in content

    # 6. Persistent session memory & full export (Task 9.1 & 9.14)
    assert "session_id: sessionId" in content
    assert "followupQuickChips" in content
    assert "full_report_markdown" in content


def test_end_to_end_followup_session_continuity():
    """Verifies end-to-end persistent session conversation and tool dispatch across turns."""
    sample_path_str = str(SAMPLE_REPO).replace("\\", "/")

    # Step 1: Execute initial codebase diagnosis query
    state = orchestrator.process(
        query="ValueError: Token expired when verify_token validates customer in checkout",
        repo_path=sample_path_str,
        force_intent="codebase_analysis",
    )

    assert state.session_id is not None
    assert state.final_output is not None
    assert state.final_output.get("type") == "codebase_analysis"

    session_id = state.session_id

    # Step 2: Turn 1 Follow-up: Ask who calls the token function
    turn1_res = orchestrator.answer_followup(
        query="What functions call that function?",
        context=state.final_output,
        session_id=session_id,
        repo_path=sample_path_str,
    )

    assert turn1_res["status"] == "ok"
    assert turn1_res["session_id"] == session_id
    assert "answer" in turn1_res
    assert len(turn1_res["answer"]) > 0

    # Step 3: Turn 2 Follow-up: Ask about blast radius using anaphora
    turn2_res = orchestrator.answer_followup(
        query="What could break if I modify it? Check blast radius.",
        context=state.final_output,
        session_id=session_id,
        repo_path=sample_path_str,
    )

    assert turn2_res["status"] == "ok"
    assert turn2_res["session_id"] == session_id
    assert "answer" in turn2_res
    assert len(turn2_res["answer"]) > 0


def test_no_em_dashes_in_phase9_files():
    """Strictly validates zero em dashes (\u2014) across all Phase 9 files and documentation."""
    files_to_check = [
        ROOT_DIR / "core" / "config.py",
        ROOT_DIR / "indexer" / "context_budget.py",
        ROOT_DIR / "indexer" / "repo_map.py",
        ROOT_DIR / "indexer" / "ast_parser.py",
        ROOT_DIR / "tools" / "static_analyzer.py",
        ROOT_DIR / "indexer" / "github_ingest.py",
        ROOT_DIR / "agents" / "flow_trace_agent.py",
        ROOT_DIR / "agents" / "change_impact_agent.py",
        ROOT_DIR / "agents" / "conversation_session.py",
        ROOT_DIR / "agents" / "diagnosis_agent.py",
        ROOT_DIR / "agents" / "workflow_state.py",
        ROOT_DIR / "agents" / "feasibility_scorecard.py",
        ROOT_DIR / "agents" / "kill_agent.py",
        ROOT_DIR / "agents" / "prd_agent.py",
        ROOT_DIR / "agents" / "orchestrator.py",
        ROOT_DIR / "app.py",
        TEMPLATE_PATH,
        README_PATH,
    ]

    em_dash = "\u2014"
    violations = []

    for file_path in files_to_check:
        if file_path.exists():
            text = file_path.read_text(encoding="utf-8")
            if em_dash in text:
                violations.append(str(file_path.relative_to(ROOT_DIR)))

    assert not violations, f"Em dashes found in: {violations}"
