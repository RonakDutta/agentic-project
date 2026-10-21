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
