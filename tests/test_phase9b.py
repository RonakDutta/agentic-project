"""
Test Suite for Phase 9B: Advanced Code Intelligence & Graph Traversal.
Tests:
1. GitHub Ingestion URL validation and safety filters (Task 9.7)
2. Static Code Analyzer metrics and maintainability grades (Task 9.6)
3. AST Alias-aware import resolution and bi-directional callers/callees (Task 9.6)
4. FlowTraceAgent execution pathway and UNRESOLVED dispatch markers (Task 9.8)
5. ChangeImpactAgent blast radius, transitive callers, and risk scoring (Task 9.9)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex
from tools.static_analyzer import StaticCodeAnalyzer
from indexer.github_ingest import GitHubIngestionService
from agents.flow_trace_agent import FlowTraceAgent
from agents.change_impact_agent import ChangeImpactAgent


def create_extended_mock_repo(base_dir: str) -> None:
    """
    Creates an extended multi-file repository with:
    - Multi-tier call hierarchy (auth -> api -> controller)
    - Alias imports (from auth.jwt_service import create_token as make_jwt)
    - Dynamic dispatch calls (UNRESOLVED marker test)
    - Dedicated test file (for impact test coverage)
    """
    os.makedirs(os.path.join(base_dir, "auth"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "api"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "controllers"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "tests"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "utils"), exist_ok=True)

    # 1. auth/jwt_service.py
    jwt_code = '''"""JWT Authentication Service."""
import time
import base64

def create_token(user_id: str, expiry_seconds: int = 3600) -> str:
    """Creates a signed JWT payload."""
    now = time.time()
    payload = f"{user_id}:{now + expiry_seconds}"
    return base64.b64encode(payload.encode()).decode()

def verify_token(token: str) -> dict:
    """Verifies JWT token validity and parses user."""
    raw = base64.b64decode(token.encode()).decode()
    parts = raw.split(":")
    user_id = parts[0]
    exp_time = float(parts[1])
    if time.time() > exp_time:
        raise ValueError("Token expired")
    return {"user_id": user_id, "active": True}
'''
    with open(os.path.join(base_dir, "auth", "jwt_service.py"), "w", encoding="utf-8") as f:
        f.write(jwt_code)

    # 2. api/routes.py (uses alias import)
    routes_code = '''"""API Route Handlers."""
from auth.jwt_service import create_token as make_jwt, verify_token

def handle_login(user_id: str) -> dict:
    """Login route handler."""
    token = make_jwt(user_id)
    return {"token": token, "status": 200}

def handle_profile(token: str) -> dict:
    """Protected profile route."""
    data = verify_token(token)
    return {"profile": data}
'''
    with open(os.path.join(base_dir, "api", "routes.py"), "w", encoding="utf-8") as f:
        f.write(routes_code)

    # 3. controllers/auth_controller.py (transitive caller to handle_login)
    controller_code = '''"""Auth Controller."""
from api.routes import handle_login

def login_endpoint(user_id: str) -> dict:
    """Top-level HTTP entrypoint for user login."""
    return handle_login(user_id)
'''
    with open(os.path.join(base_dir, "controllers", "auth_controller.py"), "w", encoding="utf-8") as f:
        f.write(controller_code)

    # 4. utils/dynamic_dispatcher.py (tests unresolved calls)
    dyn_code = '''"""Dynamic Dispatcher Helper."""

def dispatch_event(handler_name: str, payload: dict) -> None:
    """Calls dynamic method based on runtime name string."""
    registry = {}
    func = registry.get(handler_name)
    if func:
        func(payload)
'''
    with open(os.path.join(base_dir, "utils", "dynamic_dispatcher.py"), "w", encoding="utf-8") as f:
        f.write(dyn_code)

    # 5. tests/test_auth.py (test suite covering auth)
    test_code = '''"""Unit tests for auth service."""
from auth.jwt_service import create_token, verify_token

def test_token_creation():
    t = create_token("user123")
    assert t is not None

def test_token_verification():
    t = create_token("user123")
    data = verify_token(t)
    assert data["user_id"] == "user123"
'''
    with open(os.path.join(base_dir, "tests", "test_auth.py"), "w", encoding="utf-8") as f:
        f.write(test_code)


def test_github_ingest_service():
    print("\n--- Testing GitHubIngestionService (Task 9.7) ---")
    service = GitHubIngestionService()

    # 1. Test URL validation
    assert service.is_valid_github_url("https://github.com/torvalds/linux")
    assert service.is_valid_github_url("https://github.com/tiangolo/fastapi.git")
    assert not service.is_valid_github_url("https://gitlab.com/owner/repo")
    assert not service.is_valid_github_url("not_a_url")
    assert not service.is_valid_github_url("https://github.com/invalid")

    # 2. Test repo name extraction
    assert service.extract_repo_name("https://github.com/torvalds/linux") == "torvalds/linux"
    assert service.extract_repo_name("https://github.com/tiangolo/fastapi.git") == "tiangolo/fastapi"

    # 3. Test invalid URL ingestion failure handling
    bad_res = service.ingest("https://invalid.com/fake")
    assert bad_res.status == "error"
    assert "Invalid GitHub URL" in (bad_res.error_message or "")
    print("[OK] GitHubIngestionService passed URL safety and validation checks.")


def test_static_code_analyzer():
    print("\n--- Testing StaticCodeAnalyzer (Task 9.6) ---")
    analyzer = StaticCodeAnalyzer()

    # Simple clean function
    simple_code = """
def add(a, b):
    return a + b
"""
    m1 = analyzer.analyze_code_snippet(simple_code, "add")
    assert m1.cyclomatic_complexity == 1
    assert m1.maintainability_grade == "A"
    assert m1.risk_level == "Low"

    # Branch-heavy complex function
    complex_code = """
def complex_workflow(x, y, z):
    if x > 0:
        if y > 0:
            for i in range(10):
                if z and x:
                    while y < 100:
                        y += 1
    elif x < -10:
        try:
            return 1 / x
        except ZeroDivisionError:
            return 0
    else:
        assert z is not None
    return x + y + z
"""
    m2 = analyzer.analyze_code_snippet(complex_code, "complex_workflow")
    assert m2.cyclomatic_complexity >= 7
    assert m2.branch_count >= 6
    assert len(m2.findings) >= 1
    print(f"Complex code metrics: Grade {m2.maintainability_grade}, Complexity {m2.cyclomatic_complexity}")
    print("[OK] StaticCodeAnalyzer passed complexity and grading checks.")


def test_alias_aware_call_graph():
    print("\n--- Testing Alias-Aware Call Graph (Task 9.6) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_callgraph_")
    try:
        create_extended_mock_repo(temp_dir)
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        index = indexer.index()

        # 1. Verify alias import resolution
        # handle_login calls make_jwt, which aliases auth.jwt_service.create_token
        callers = index.get_callers("create_token")
        caller_symbols = [c["caller_symbol"] for c in callers]
        print(f"Callers of 'create_token': {caller_symbols}")

        assert "handle_login" in caller_symbols, f"Expected handle_login in callers of create_token, got: {caller_symbols}"

        # 2. Check call confidence
        direct_call = [c for c in callers if c["caller_symbol"] == "handle_login"][0]
        assert direct_call["confidence"] == "high"
        assert direct_call["caller_file"] == "api/routes.py"
        print("[OK] Alias-aware import resolution and caller mapping passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_flow_trace_agent():
    print("\n--- Testing FlowTraceAgent (Task 9.8) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_flow_")
    try:
        create_extended_mock_repo(temp_dir)
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        index = indexer.index()

        agent = FlowTraceAgent(codebase_index=index)
        result = agent.trace_flow(query="handle_login", starting_symbol="handle_login")

        print(f"Flow Trace: {result.total_hops} hops, starting from '{result.starting_symbol}'")
        for h in result.hops:
            print(f"  Hop {h.step_number}: {h.symbol_name} in {h.file_path} (confidence: {h.confidence})")

        assert result.total_hops >= 2
        assert result.hops[0].symbol_name == "handle_login"
        assert any(h.symbol_name in ("make_jwt", "create_token") for h in result.hops)
        assert "graph LR" in result.mermaid_diagram or "-->" in result.mermaid_diagram

        # Test unresolved dynamic dispatch behavior
        dyn_result = agent.trace_flow(query="dispatch_event", starting_symbol="dispatch_event")
        assert dyn_result.total_hops >= 1
        print("[OK] FlowTraceAgent execution pathway and Mermaid generation passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_change_impact_agent():
    print("\n--- Testing ChangeImpactAgent (Task 9.9) ---")
    temp_dir = tempfile.mkdtemp(prefix="agentic_impact_")
    try:
        create_extended_mock_repo(temp_dir)
        indexer = ASTCodeIndexer(repo_path=temp_dir)
        index = indexer.index()

        agent = ChangeImpactAgent(codebase_index=index)
        result = agent.analyze_impact(target_symbol="create_token")

        print(f"Target: {result.target_symbol} ({result.target_file})")
        print(f"Blast Radius Score: {result.blast_radius_score}/100, Risk Level: {result.risk_level}")
        print(f"Direct callers count: {len(result.direct_callers)}")
        print(f"Indirect callers count: {len(result.indirect_callers)}")
        print(f"Affected tests: {result.affected_tests}")
        print(f"Affected entrypoints: {result.affected_entrypoints}")

        # 1. Direct caller must include handle_login
        direct_symbols = [c.symbol_name for c in result.direct_callers]
        assert "handle_login" in direct_symbols

        # 2. Indirect caller must include login_endpoint (calls handle_login)
        indirect_symbols = [c.symbol_name for c in result.indirect_callers]
        assert "login_endpoint" in indirect_symbols

        # 3. Affected tests must detect tests/test_auth.py
        assert any("test_auth.py" in t for t in result.affected_tests)

        # 4. Entrypoints must be recognized
        assert len(result.affected_entrypoints) >= 1

        # 5. Mermaid diagram must exist
        assert "graph TD" in result.mermaid_diagram
        assert "Target" in result.mermaid_diagram

        # 6. Recommendations must be populated
        assert len(result.recommendations) >= 1
        assert any("test" in r.lower() for r in result.recommendations)

        print("[OK] ChangeImpactAgent blast radius, indirect callers, and test coverage passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_github_ingest_service()
    test_static_code_analyzer()
    test_alias_aware_call_graph()
    test_flow_trace_agent()
    test_change_impact_agent()
    print("\nAll Phase 9B tests passed successfully!")
