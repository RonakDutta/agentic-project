"""
Phase 7 Test Suite: Verifies FastAPI Server endpoints:
HTML Dashboard serving, Sample Repo path retrieval, AST inspection endpoint, and Health check.
"""

import sys
from pathlib import Path
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app import app

client = TestClient(app)


def test_app_endpoints():
    print("[1/4] Testing GET / (HTML Dashboard)...")
    res = client.get("/")
    assert res.status_code == 200
    assert "Agentic Co-Pilot" in res.text
    print("      Dashboard HTML served successfully.")

    print("[2/4] Testing GET /api/sample-repo-path...")
    res = client.get("/api/sample-repo-path")
    assert res.status_code == 200
    data = res.json()
    assert "path" in data
    assert Path(data["path"]).exists()
    print(f"      Sample repo located at: {data['path']}")

    print("[3/4] Testing POST /api/inspect-repo on sample repo...")
    res = client.post("/api/inspect-repo", json={"repo_path": data["path"]})
    assert res.status_code == 200
    inspect_data = res.json()
    assert inspect_data["status"] == "ok"
    assert inspect_data["summary"]["total_files"] >= 2
    assert inspect_data["summary"]["total_chunks"] >= 4
    print(f"      AST inspection succeeded: {inspect_data['summary']['total_files']} files, {inspect_data['summary']['total_chunks']} chunks.")

    print("[4/4] Testing GET /api/health and GET /health...")
    res = client.get("/api/health")
    assert res.status_code == 200
    res_alias = client.get("/health")
    assert res_alias.status_code == 200
    health_data = res.json()
    assert health_data["status"] == "online"
    print(f"      Health check: {health_data['status']} with model {health_data['model']}")

    print("\nAll Phase 7 Web Application tests passed successfully!")


def test_followup_endpoint():
    print("Testing POST /api/followup...")
    res = client.post(
        "/api/followup",
        json={
            "query": "Can we switch the database to PostgreSQL?",
            "context": {"type": "idea_validation", "project_title": "IoT Energy Meter"},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert "agent_name" in data
    print(f"Follow-up answered by: {data['agent_name']}")


def test_inspect_repo_github():
    print("Testing POST /api/inspect-repo with GitHub repository URL...")
    res = client.post(
        "/api/inspect-repo",
        json={"repo_path": "https://github.com/RonakDutta/agentic-project"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["is_remote"] is True
    assert data["summary"]["total_files"] >= 1
    assert "local_path" in data


if __name__ == "__main__":
    test_app_endpoints()
    test_followup_endpoint()
    test_inspect_repo_github()

