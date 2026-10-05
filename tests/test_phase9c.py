"""
Test Suite for Phase 9C: Agent Orchestration & Conversational Memory.
Tests:
1. Standardized Agent Execution Trace Schema (Task 9.12)
2. Grounded Anti-Pattern vs Recommended Pattern Educational Slices (Task 9.2)
3. Persistent Conversational Session Scoped to Repository with Anaphora Resolution (Task 9.1)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from agents.workflow_state import AgentWorkflowState, TraceStep
from agents.diagnosis_agent import FaultCandidate, DiagnosisResult
from agents.conversation_session import (
    SessionManager,
    ConversationSession,
    ConversationalFollowupEngine,
)
from tests.test_phase9b import create_extended_mock_repo


def test_standardized_agent_trace_schema():
    print("\n--- Testing Standardized Agent Execution Trace (Task 9.12) ---")
    state = AgentWorkflowState(
        session_id="test_sess_01",
        user_query="Diagnose memory leak in session handler",
    )

    # 1. Add standardized trace step
    state.add_trace(
        agent_name="DiagnosisAgent",
        action="Localized fault candidate in auth/session.py",
        status="completed",
        agent_role="Root-Cause Diagnosis Specialist",
        input_summary="Query + 3 candidate code chunks from AST index",
        output_summary="Identified unclosed session pool at line 45",
        evidence_count=3,
        citations=["auth/session.py:40-60 (SessionPool)"],
        duration_ms=120,
    )

    assert len(state.execution_trace) == 1
    step = state.execution_trace[0]
    assert step.agent_name == "DiagnosisAgent"
    assert step.agent_role == "Root-Cause Diagnosis Specialist"
    assert step.evidence_count == 3
    assert step.duration_ms == 120
    assert len(step.citations) == 1

    # 2. Test serialization
    data = state.to_dict()
    assert "execution_trace" in data
    trace_data = data["execution_trace"][0]
    assert trace_data["agent_role"] == "Root-Cause Diagnosis Specialist"
    assert trace_data["input_summary"] == "Query + 3 candidate code chunks from AST index"
    assert trace_data["output_summary"] == "Identified unclosed session pool at line 45"
    assert trace_data["evidence_count"] == 3
    assert trace_data["citations"] == ["auth/session.py:40-60 (SessionPool)"]

    print("[OK] Standardized agent trace schema verified.")


def test_grounded_educational_comparison_slice():
    print("\n--- Testing Grounded Educational Comparison Slices (Task 9.2) ---")
    candidate = FaultCandidate(
        rank=1,
        file_path="auth/jwt_service.py",
        symbol_name="verify_token",
        line_start=15,
        line_end=25,
        confidence="high",
        root_cause_hypothesis="Expiration check uses strict greater-than comparison with float precision drift.",
        suggested_fix="Use int cast and defensive margin for timestamp checks.",
        wrong_code="if time.time() > exp_time:\n    raise ValueError('Token expired')",
        correct_code="if int(time.time()) >= int(exp_time):\n    raise ValueError('Token expired')",
        why_problematic="Float precision timestamp drift can allow expired tokens to validate across clock skew intervals.",
        recommended_pattern="def verify_token(token: str, leeway: int = 5) -> dict:\n    # Defensive leeway window\n    if int(time.time()) >= (int(exp_time) + leeway):\n        raise ValueError('Token expired')",
        explanation_of_change="Normalizes time comparison to integer seconds and introduces configurable leeway.",
        citations=["auth/jwt_service.py:15-25 (verify_token)"],
    )

    # 1. Test educational slice extraction
    slice_data = candidate.to_educational_slice()
    assert "current_implementation" in slice_data
    assert "why_problematic" in slice_data
    assert "recommended_pattern" in slice_data
    assert "explanation_of_change" in slice_data
    assert "citations" in slice_data

    assert slice_data["current_implementation"]["file_path"] == "auth/jwt_service.py"
    assert slice_data["current_implementation"]["lines"] == "15-25"
    assert "time.time() > exp_time" in slice_data["current_implementation"]["code"]
    assert "Float precision" in slice_data["why_problematic"]
    assert "leeway" in slice_data["recommended_pattern"]
    assert "auth/jwt_service.py:15-25 (verify_token)" in slice_data["citations"][0]

    # 2. Test diagnosis result serialization
    diag_res = DiagnosisResult(
        query="Verify token expiration bug",
        summary="Found clock skew issue in token verification.",
        ranked_candidates=[candidate],
    )
    res_dict = diag_res.to_dict()
    assert len(res_dict["educational_slices"]) == 1
    assert res_dict["educational_slices"][0]["current_implementation"]["symbol"] == "verify_token"

    print("[OK] Educational comparison slice verified.")


def test_conversational_session_and_anaphora():
    print("\n--- Testing Conversational Session & Anaphora Resolution (Task 9.1) ---")
    session_mgr = SessionManager()
    session = session_mgr.get_or_create_session(session_id="multi_turn_test")

    # 1. Turn 1: Discuss authentication
    turn1 = session.add_turn(
        user_query="Where is authentication implemented?",
        agent_name="Code Review & AST Specialist",
        answer="Authentication is implemented in `auth/jwt_service.py` with `verify_token` and `create_token`.",
        referenced_symbols=["verify_token", "create_token"],
        referenced_files=["auth/jwt_service.py"],
    )
    assert len(session.history) == 1
    assert session.active_entities["last_symbol"] == "verify_token"
    assert session.active_entities["last_file"] == "auth/jwt_service.py"

    # 2. Anaphora Resolution test
    # "What calls that function?" -> should resolve "that function" to "verify_token"
    resolved_q2 = session.resolve_anaphora("What calls that function?")
    assert "verify_token" in resolved_q2
    print(f"Resolved 'What calls that function?' -> '{resolved_q2}'")

    # "What could break if I modify it?" -> should resolve "modify it" to "modify verify_token"
    resolved_q3 = session.resolve_anaphora("What could break if I modify it?")
    assert "verify_token" in resolved_q3
    print(f"Resolved 'What could break if I modify it?' -> '{resolved_q3}'")

    # 3. Bounded Context test
    # Add multiple turns to check bounded context packing
    for i in range(5):
        session.add_turn(
            user_query=f"Follow-up question #{i}",
            agent_name="Lead Systems Architect",
            answer=f"Detailed response for turn #{i} discussing system modularity.",
        )
    bounded_ctx = session.get_bounded_context(max_tokens=2000)
    assert "Earlier Conversation Summary" in bounded_ctx or "Recent Conversation History" in bounded_ctx
    assert "Follow-up question #4" in bounded_ctx
    print("[OK] Session anaphora resolution and bounded context verified.")


def test_conversational_followup_tool_dispatch():
    print("\n--- Testing Conversational Tool Dispatch on Mock Repo (Task 9.1) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_chat_repo_")
    try:
        create_extended_mock_repo(temp_dir)
        session_mgr = SessionManager()
        engine = ConversationalFollowupEngine(session_manager=session_mgr)

        session_id = "chat_dispatch_test"

        # Turn 1: Initial query seeds session memory
        session = session_mgr.get_or_create_session(session_id=session_id, repo_path=temp_dir)
        session.add_turn(
            user_query="Find token generation logic",
            agent_name="Code Review & AST Specialist",
            answer="Token generation is handled by `create_token` in `auth/jwt_service.py`.",
            referenced_symbols=["create_token"],
            referenced_files=["auth/jwt_service.py"],
        )

        # Turn 2: Follow-up 1 -> "What calls that function?"
        res_callers = engine.process_followup(
            query="What calls that function?",
            session_id=session_id,
            repo_path=temp_dir,
        )
        print(f"Turn 2 Agent: {res_callers['agent_name']}")
        print(f"Turn 2 Action: {res_callers['action_taken']}")
        assert res_callers["agent_name"] == "Code Review & AST Specialist"
        assert "handle_login" in res_callers["answer"]
        print("[OK] Turn 2 dynamically queried callers of 'create_token'.")

        # Turn 3: Follow-up 2 -> "What could break if I modify it?"
        res_impact = engine.process_followup(
            query="What could break if I modify it?",
            session_id=session_id,
            repo_path=temp_dir,
        )
        print(f"Turn 3 Agent: {res_impact['agent_name']}")
        print(f"Turn 3 Action: {res_impact['action_taken']}")
        assert res_impact["agent_name"] == "Risk & Security Auditor"
        assert "Change Impact Analysis" in res_impact["answer"]
        assert "Blast Radius Score" in res_impact["answer"]
        assert "impact_data" in res_impact
        assert res_impact["impact_data"]["blast_radius_score"] > 0
        print("[OK] Turn 3 dynamically executed ChangeImpactAgent on 'create_token'.")

        # Turn 4: Follow-up 3 -> "Trace execution of create_token"
        res_trace = engine.process_followup(
            query="Trace execution of create_token",
            session_id=session_id,
            repo_path=temp_dir,
        )
        print(f"Turn 4 Agent: {res_trace['agent_name']}")
        print(f"Turn 4 Action: {res_trace['action_taken']}")
        assert res_trace["agent_name"] == "Lead Systems Architect"
        assert "Execution Flow" in res_trace["answer"]
        assert "flow_data" in res_trace
        print("[OK] Turn 4 dynamically executed FlowTraceAgent on 'create_token'.")

        # Verify session preserved all 4 turns
        full_session = session_mgr.get_session(session_id)
        assert full_session is not None
        assert len(full_session.history) == 4
        print(f"[OK] Full session preserved {len(full_session.history)} turns seamlessly.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_standardized_agent_trace_schema()
    test_grounded_educational_comparison_slice()
    test_conversational_session_and_anaphora()
    test_conversational_followup_tool_dispatch()
    print("\nAll Phase 9C tests passed successfully!")
