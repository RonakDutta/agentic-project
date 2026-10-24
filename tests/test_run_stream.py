"""SSE run stream: real trace events arrive before the final result (hermetic, offline)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from core.llm import llm_client

SAMPLE = str(Path(__file__).resolve().parent.parent / "sample_repo")


def _events(body: str):
    out = []
    for block in body.split("\n\n"):
        kind, data = None, ""
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data += line[6:]
        if kind:
            out.append((kind, json.loads(data)))
    return out


def test_stream_sends_trace_steps_then_result(monkeypatch):
    # The pipeline runs on a worker thread, so stub the client instead of force_offline().
    def offline(*args, **kwargs):
        raise RuntimeError("offline test")

    monkeypatch.setattr(llm_client, "generate", offline)
    client = TestClient(app)
    res = client.post("/api/run/stream", json={
        "query": "Orders get processed twice. Where is the bug?",
        "repo_path": SAMPLE,
        "force_intent": "codebase_analysis",
    })
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _events(res.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "result"
    traces = [d for k, d in events if k == "trace"]
    assert any(t["agent_name"] == "Code Structure Indexer" for t in traces)
    result = events[-1][1]
    assert len(result["execution_trace"]) == len(traces)
    assert result["final_output"]["question_mode"] == "bug"


def test_legacy_ui_still_served():
    client = TestClient(app)
    assert client.get("/legacy").status_code == 200
    assert client.get("/").status_code == 200


def test_idea_stream_records_roadmap_from_its_thread(monkeypatch):
    # The roadmap runs in parallel; its step must arrive on its own (with a real
    # duration), not only at the end, and the join is a separate Report Compiler step.
    def offline(*args, **kwargs):
        raise RuntimeError("offline test")

    monkeypatch.setattr(llm_client, "generate", offline)
    client = TestClient(app)
    res = client.post("/api/run/stream", json={
        "query": "An app that helps farmers share tractors with neighbours",
        "force_intent": "idea_validation",
    })
    traces = [d for k, d in _events(res.text) if k == "trace"]
    names = [t["agent_name"] for t in traces]
    assert names.count("Roadmap & Risk Assessor") >= 1
    assert names.index("Roadmap & Risk Assessor") < names.index("Report Compiler")
    assert len({t["step_id"] for t in traces}) == len(traces)
    roadmap = next(t for t in traces if t["agent_name"] == "Roadmap & Risk Assessor" and t["details"].get("parallel"))
    assert roadmap["status"] == "warning"  # offline, so the roadmap is a labelled fallback


def test_cancel_stops_before_next_agent_step(monkeypatch):
    import threading

    import pytest

    from agents.orchestrator import orchestrator
    from agents.workflow_state import RunCancelled

    cancel = threading.Event()
    calls = []

    def stop_after_first_call(*args, **kwargs):
        calls.append(1)
        cancel.set()  # the user presses Stop while the first agent is working
        raise RuntimeError("offline test")

    monkeypatch.setattr(llm_client, "generate", stop_after_first_call)
    seen = []
    with pytest.raises(RunCancelled):
        orchestrator.process(
            query="An app that helps farmers share tractors with neighbours",
            force_intent="idea_validation",
            on_trace=seen.append,
            cancel_event=cancel,
        )
    names = [s["agent_name"] for s in seen]
    assert "Adversarial Kill Agent" not in names and "PRD & Architecture Specialist" not in names
    assert seen[-1]["status"] == "warning" and "stopped" in seen[-1]["action"]


def test_cancel_unknown_run_is_404():
    client = TestClient(app)
    res = client.post("/api/run/cancel", json={"run_id": "nope"})
    assert res.status_code == 404
