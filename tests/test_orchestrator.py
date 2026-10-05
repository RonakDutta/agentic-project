"""
Phase 6 Test Suite: Verifies Orchestrator Agent:
Intent Classification -> Supervisory Routing -> Code Pipeline -> Idea Pipeline -> Execution Traces.
"""

import shutil
import sys
import tempfile
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
from tests.test_ast_parser import create_mock_repository


def test_orchestrator_pipeline():
    temp_dir = tempfile.mkdtemp(prefix="agentic_orch_test_")
    try:
        create_mock_repository(temp_dir)

        # 1. Test Codebase Analysis Intent Routing
        print("[1/2] Testing Orchestrator on Codebase Analysis Track...")
        code_query = "Login endpoint is failing because verify_token raises a ValueError on expired tokens."
        code_state = orchestrator.process(query=code_query, repo_path=temp_dir)

        print(f"      Identified Intent: '{code_state.intent}' (Confidence: {code_state.intent_confidence})")
        print(f"      Total Trace Steps: {len(code_state.execution_trace)}")
        print(f"      Critic Verified: {code_state.final_output.get('critic', {}).get('is_valid')}")
        print(f"      Total Latency: {code_state.total_latency_ms}ms")

        assert code_state.intent == "codebase_analysis"
        assert code_state.final_output is not None
        assert code_state.final_output.get("type") == "codebase_analysis"
        assert len(code_state.execution_trace) >= 5

        # 2. Test Idea Validation Intent Routing
        print("\n[2/2] Testing Orchestrator on Idea Validation Track...")
        idea_query = "An automated AI peer review platform for engineering students to evaluate their lab code against best practices."
        idea_state = orchestrator.process(query=idea_query)

        print(f"      Identified Intent: '{idea_state.intent}' (Confidence: {idea_state.intent_confidence})")
        print(f"      Generated Project: '{idea_state.final_output.get('project_title')}'")
        print(f"      Phases Count: {len(idea_state.final_output.get('phases', []))}")
        print(f"      Total Latency: {idea_state.total_latency_ms}ms")

        assert idea_state.intent == "idea_validation"
        assert idea_state.final_output is not None
        assert idea_state.final_output.get("type") == "idea_validation"
        assert len(idea_state.final_output.get("phases", [])) == 3
        assert len(idea_state.execution_trace) >= 4

        print("\nAll Phase 6 Orchestrator tests passed successfully!")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_orchestrator_pipeline()
