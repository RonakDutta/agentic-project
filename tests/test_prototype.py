"""Prototype Builder: safety gate, AI path, one repair, labelled fallback, API (hermetic: AI stubbed)."""

import io
import json
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from agents import prototype_agent
from agents.prototype_agent import build_spec, parse_files, prototype_builder
from agents.prototype_templates import fallback_files
from agents.workflow_state import AgentWorkflowState
from core.llm import llm_client
from tools import prototype_sandbox

IDEA = {
    "type": "idea_validation",
    "project_title": "Tractor Share",
    "problem_statement": "Small farmers cannot afford their own tractor.",
    "target_personas": [{"name": "Small farmer"}, "Tractor owner"],
    "mvp_features": ["Book a tractor"],
    "prd": {"functional_requirements": [
        {"req_id": "FR-03", "title": "Ratings", "description": "Rate a booking", "priority": "Nice to Have"},
        {"req_id": "FR-01", "title": "List tractors", "description": "Owners list tractors", "priority": "Must Have"},
        {"req_id": "FR-02", "title": "Book by the hour", "description": "Farmers book a slot", "priority": "Must Have"},
    ]},
}

GOOD_FEATURES = '''from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api")
TRACTORS = [{"id": 1, "name": "Mahindra 575", "rate": 400}, {"id": 2, "name": "Swaraj 744", "rate": 450}]
BOOKINGS = []


class Booking(BaseModel):
    tractor_id: int
    hours: int


@router.get("/tractors")
def tractors():
    return TRACTORS


@router.post("/bookings", status_code=201)
def book(booking: Booking):
    if booking.hours < 1:
        raise HTTPException(status_code=422, detail="hours must be positive")
    tractor = next((t for t in TRACTORS if t["id"] == booking.tractor_id), None)
    if tractor is None:
        raise HTTPException(status_code=404, detail="tractor not found")
    entry = {"id": len(BOOKINGS) + 1, "cost": tractor["rate"] * booking.hours, **booking.model_dump()}
    BOOKINGS.append(entry)
    return entry


@router.get("/bookings")
def bookings():
    return BOOKINGS
'''
GOOD_TESTS = '''from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_list():
    assert len(client.get("/api/tractors").json()) == 2


def test_book():
    assert client.post("/api/bookings", json={"tractor_id": 1, "hours": 2}).json()["cost"] == 800


def test_missing():
    assert client.post("/api/bookings", json={"tractor_id": 9, "hours": 2}).status_code == 404
'''
GOOD_PAGE = '<!doctype html><html><head><link rel="stylesheet" href="/static/base.css"></head><body><main class="wrap"><div class="card">Tractor Share</div></main></body></html>'


def answer(features=GOOD_FEATURES, page=GOOD_PAGE, tests=GOOD_TESTS):
    return (f"### FILE: features.py\n```python\n{features}\n```\n"
            f"### FILE: static/index.html\n```html\n{page}\n```\n"
            f"### FILE: test_features.py\n```python\n{tests}\n```\n")


@pytest.fixture(autouse=True)
def sandbox_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(prototype_sandbox, "PROTOTYPE_DIR", tmp_path / "protos")
    yield
    prototype_sandbox.processes.stop_all()


def build_with(monkeypatch, replies):
    calls = []

    def fake_generate(messages, *args, **kwargs):
        calls.append(messages)
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(llm_client, "generate", fake_generate)
    steps = []
    state = AgentWorkflowState(session_id="t", user_query="t", listener=steps.append)
    return prototype_builder.build(IDEA, state), steps, calls


def test_spec_picks_must_have_first():
    spec = build_spec(IDEA)
    assert [r["id"] for r in spec["requirements"]] == ["FR-01", "FR-02", "FR-03"]
    assert spec["personas"] == ["Small farmer", "Tractor owner"]


def test_parse_files_reads_the_three_blocks():
    files = parse_files("Some intro\n" + answer())
    assert set(files) == set(prototype_agent.AI_FILES)
    assert files["features.py"].startswith("from fastapi")


def test_safety_check_blocks_unsafe_code():
    bad = {
        "features.py": "import os\nrouter = 1\neval('1')\nx = ().__class__\n",
        "static/index.html": '<script src="https://cdn.example.com/x.js"></script>',
        "test_features.py": "import subprocess\n",
    }
    issues = " ".join(prototype_sandbox.safety_check(bad))
    for word in ("'os'", "'eval'", "__class__", "outside scripts", "'subprocess'"):
        assert word in issues
    assert prototype_sandbox.safety_check({"features.py": "x = 1\n"}) == ["features.py: must define 'router = APIRouter(...)'."]


def test_fallback_files_are_safe_and_compile():
    files = fallback_files(build_spec(IDEA))
    assert prototype_sandbox.safety_check(files) == []
    assert prototype_sandbox.compile_check(files) == []


def test_ai_build_runs_tests_and_starts_the_app(monkeypatch):
    build, steps, calls = build_with(monkeypatch, [answer()])
    assert len(calls) == 1  # one AI call, no fix needed
    assert build["generation_source"] == "llm" and not build["repaired"]
    assert build["checks"]["tests"]["passed"] == 3 and build["checks"]["tests"]["ok"]
    assert build["checks"]["server"]["ok"]
    paths = {e["path"]: e["status"] for e in build["checks"]["endpoints"]}
    assert paths["/"] == 200 and paths["/api/tractors"] == 200
    by = {f["path"]: f["written_by"] for f in build["files"]}
    assert by["features.py"] == "ai" and by["main.py"] == "template"
    names = [s["agent_name"] for s in steps]
    assert names[:2] == ["Spec Planner", "Code Writer"] and "Endpoint Checker" in names
    status = prototype_sandbox.processes.status(build["id"])
    assert status["state"] == "running" and status["requests_checks"] >= 3 and status["requests_visitors"] == 0


def test_broken_code_is_fixed_once_with_the_real_error(monkeypatch):
    broken = GOOD_FEATURES.replace("def tractors():", "def tractors(:")
    build, steps, calls = build_with(monkeypatch, [answer(features=broken), answer()])
    assert len(calls) == 2 and build["repaired"]
    assert "invalid syntax" in calls[1][-1]["content"] or "features.py:" in calls[1][-1]["content"]
    assert build["generation_source"] == "llm" and build["checks"]["tests"]["ok"]
    assert any(s["agent_name"] == "Code Fixer" and not s["details"].get("skipped") for s in steps)


def test_unsafe_code_falls_back_and_is_labelled(monkeypatch):
    unsafe = "import os\n" + GOOD_FEATURES
    build, steps, _ = build_with(monkeypatch, [answer(features=unsafe), answer(features=unsafe)])
    assert build["generation_source"] == "fallback" and "still failed" in build["fallback_reason"]
    assert build["checks"]["tests"]["ok"]  # the fallback prototype's own tests
    assert {f["written_by"] for f in build["files"]} == {"fallback", "template"}
    assert any(s["status"] == "warning" and s["agent_name"] == "Safety Check" for s in steps)


def test_api_build_stream_monitor_stop_and_download(monkeypatch):
    from agents.conversation_session import session_manager
    from tests.test_run_stream import _events
    from app import app

    session = session_manager.get_or_create_session("proto01")
    session.active_entities["final_output"] = IDEA
    monkeypatch.setattr(llm_client, "generate", lambda *a, **k: answer())
    client = TestClient(app)

    assert client.post("/api/prototype/build/stream", json={"session_id": "nosuch"}).status_code == 404
    events = _events(client.post("/api/prototype/build/stream", json={"session_id": "proto01"}).text)
    assert events[0][0] == "start" and events[-1][0] == "result"
    build = events[-1][1]["final_output"]
    proto_id = build["id"]

    status = client.get(f"/api/prototype/{proto_id}/status").json()
    assert status["state"] == "running"
    assert client.get(f"/api/prototype/{proto_id}").json()["build"]["id"] == proto_id
    assert client.post(f"/api/prototype/{proto_id}/stop").json()["state"] == "stopped"

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"/api/prototype/{proto_id}/download").content))
    names = {n.split("/", 1)[1] for n in archive.namelist()}
    assert {"main.py", "features.py", "static/index.html", "test_features.py"} <= names
    assert client.get("/api/prototype/../../etc/status").status_code == 404
    assert client.get("/api/prototype/zzzz/status").status_code == 404
    json.dumps(build)  # the build must be plain JSON


def test_parse_answer_tolerates_headings_and_drops_cut_off_files():
    loose = (f"**features.py**\n```python\n{GOOD_FEATURES}\n```\n"
             f"`static/index.html`:\n```html\n{GOOD_PAGE}\n```\n"
             f"### FILE: test_features.py\n```python\n{GOOD_TESTS[:80]}")  # answer hit its token limit
    files, cut = prototype_agent.parse_answer(loose)
    assert set(files) == {"features.py", "static/index.html"} and cut == ["test_features.py"]
    unnamed, _ = prototype_agent.parse_answer(f"```python\n{GOOD_TESTS}\n```")
    assert list(unnamed) == ["test_features.py"]  # named by its content


def test_page_check_finds_calls_to_missing_routes():
    page = 'fetch("/api/tractors"); api(`/api/bookings/${id}`); api("/api/bookings/" + id); fetch("/api/rentals")'
    features = GOOD_FEATURES + '\n\n@router.delete("/bookings/{booking_id}")\ndef cancel(booking_id: int):\n    return {}\n'
    issues = prototype_sandbox.page_api_check({"features.py": features, "static/index.html": page})
    assert len(issues) == 1 and "/api/rentals" in issues[0]
    assert prototype_sandbox.api_routes(GOOD_FEATURES) == ["/api/tractors", "/api/bookings", "/api/bookings"]


def test_missing_file_goes_to_the_fixer_not_the_fallback(monkeypatch):
    partial = answer().split("### FILE: test_features.py")[0]
    tests_only = f"### FILE: test_features.py\n```python\n{GOOD_TESTS}\n```\n"
    build, steps, calls = build_with(monkeypatch, [partial, tests_only])
    assert len(calls) == 2 and "Missing files: test_features.py" in calls[1][-1]["content"]
    assert build["generation_source"] == "llm" and build["repaired"] and build["checks"]["tests"]["ok"]


def test_page_calling_a_missing_route_is_sent_to_the_fixer(monkeypatch):
    bad_page = GOOD_PAGE.replace("</body>", '<script>fetch("/api/rentals")</script></body>')
    build, steps, calls = build_with(monkeypatch, [answer(page=bad_page), answer()])
    assert len(calls) == 2 and "/api/rentals" in calls[1][-1]["content"]
    assert build["checks"]["page_ok"] and build["checks"]["tests"]["ok"]
    assert any(s["agent_name"] == "Page Check" and s["status"] == "warning" for s in steps)


def test_sandbox_env_finds_installed_packages_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    env = prototype_sandbox._sandbox_env(tmp_path)
    assert "GROQ_API_KEY" not in env and "HTTPS_PROXY" not in env
    assert any("site-packages" in p or "dist-packages" in p for p in env["PYTHONPATH"].split(os.pathsep))
    assert prototype_sandbox.runtime_check() == ""


def test_code_call_waits_for_a_full_budget_instead_of_shrinking():
    from core.llm import LLMClient
    client = LLMClient()
    model = client._get_candidate_models(None)[0]
    client._model_budget[model] = {"remaining_tokens": 2500, "reset_tokens_at": time.time() + 30}
    assert client._clamp_max_tokens(model, 4800, 1500) is not None  # normal calls shrink
    assert client._clamp_max_tokens(model, 4800, 1500, min_answer=4000) is None  # code calls wait
    client._model_budget.clear()
    assert client._clamp_max_tokens(model, 4800, 1500, min_answer=4000) == 4800  # not cut to MAX_TOKENS_CAP
