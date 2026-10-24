"""
FastAPI Server and Web API for Agentic AI Co-Pilot.
Serves the browser dashboard and exposes REST endpoints for multi-agent execution.

Endpoints that run agents are plain `def` functions on purpose: the agent
pipeline is blocking (Groq calls, git clone, AST parsing), and FastAPI runs
`def` endpoints in its worker thread pool. As `async def` they blocked the
event loop, so /api/health and every other request froze during a run.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn

from core.config import settings
from core.llm import llm_client
from indexer import index_cache
from agents.orchestrator import orchestrator
from agents.workflow_state import AgentWorkflowState, RunCancelled
from tools import prototype_sandbox

app = FastAPI(
    title="Agentic AI Co-Pilot API",
    description="Multi-Agent RAG System for Idea Validation and Codebase Analysis",
    version="1.0.0",
)

ROOT_DIR = Path(__file__).resolve().parent
HTML_PATH = ROOT_DIR / "web" / "templates" / "index.html"
# The new UI (web/react-app, built with `npm run build`). Served at / when built;
# UI=legacy in the environment keeps the old single-file dashboard at /.
UI_DIST = ROOT_DIR / "web" / "react-app" / "dist"
SAMPLE_REPO_PATH = ROOT_DIR / "sample_repo"


# Every visitor shares one free Groq key, so full pipeline runs are limited per
# client (RUNS_PER_MINUTE, 0 = no limit). Follow-ups are cheap and not limited.
RUNS_PER_MINUTE = int(os.getenv("RUNS_PER_MINUTE", "6"))
_run_log: "defaultdict[str, deque]" = defaultdict(deque)
_run_lock = threading.Lock()


def _rate_limited(request: Request) -> Optional[JSONResponse]:
    if RUNS_PER_MINUTE <= 0:
        return None
    client_id = request.client.host if request.client else "unknown"
    now = time.time()
    with _run_lock:
        log = _run_log[client_id]
        while log and now - log[0] > 60:
            log.popleft()
        if len(log) >= RUNS_PER_MINUTE:
            wait = int(60 - (now - log[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"status": "failed", "error": f"Too many runs from this browser. Try again in {wait}s."},
            )
        log.append(now)
    return None


def _local_path_allowed(path: str) -> bool:
    """
    ALLOWED_REPO_ROOTS (os.pathsep-separated folders) limits which local folders
    can be indexed. Empty means any folder, which is fine on your own laptop but
    must be set before the app is reachable by anyone else.
    """
    roots = [r for r in settings.allowed_repo_roots.split(os.pathsep) if r.strip()]
    if not roots:
        return True
    target = os.path.realpath(path)
    allowed = [os.path.realpath(r) for r in roots] + [
        os.path.realpath(SAMPLE_REPO_PATH), os.path.realpath(prototype_sandbox.PROTOTYPE_DIR),
    ]
    return any(target == root or target.startswith(root + os.sep) for root in allowed)


def _check_repo_path(repo_path: Optional[str]) -> Optional[JSONResponse]:
    """Returns an error response when a local repo path is not allowed, else None."""
    if not repo_path:
        return None
    from indexer.github_ingest import github_ingest_service
    target = repo_path.strip()
    if github_ingest_service.is_valid_github_url(target):
        return None
    if not _local_path_allowed(target):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "error": f"Path '{target}' is outside ALLOWED_REPO_ROOTS.",
                     "message": f"Path '{target}' is outside ALLOWED_REPO_ROOTS."},
        )
    return None


class QueryRequest(BaseModel):
    query: str
    repo_path: Optional[str] = None
    force_intent: Optional[str] = None


class PrototypeRequest(BaseModel):
    session_id: str


class InspectRepoRequest(BaseModel):
    repo_path: str


class FollowupRequest(BaseModel):
    query: str
    context: Optional[dict] = None
    session_id: Optional[str] = None
    repo_path: Optional[str] = None


if (UI_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(UI_DIST / "assets")), name="ui-assets")


def _new_ui_enabled() -> bool:
    return (UI_DIST / "index.html").exists() and os.getenv("UI", "").lower() != "legacy"


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the new UI when it is built, otherwise the legacy dashboard."""
    if _new_ui_enabled():
        return HTMLResponse(content=(UI_DIST / "index.html").read_text(encoding="utf-8"))
    return serve_legacy_dashboard()


@app.get("/legacy", response_class=HTMLResponse)
def serve_legacy_dashboard():
    """Serves the original single-file dashboard."""
    if not HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Dashboard template not found.")
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.post("/api/query")
def execute_query(req: QueryRequest, request: Request):
    """Executes the multi-agent orchestrator pipeline."""
    denied = _check_repo_path(req.repo_path) or _rate_limited(request)
    if denied:
        return denied
    try:
        state = orchestrator.process(
            query=req.query,
            repo_path=req.repo_path,
            force_intent=req.force_intent,
        )
        return JSONResponse(content=state.to_dict())
    except Exception as err:
        return JSONResponse(
            status_code=500,
            content={"error": str(err), "status": "failed"},
        )


# run_id -> cancel flag for runs that are streaming right now (POST /api/run/cancel).
_ACTIVE_RUNS: dict = {}


class CancelRequest(BaseModel):
    run_id: str


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/api/run/stream")
def stream_query(req: QueryRequest, request: Request):
    """
    Runs the pipeline and streams real progress as Server-Sent Events:
    `trace` for every agent step as it is recorded, `llm` for every AI model call
    (model, tokens, latency, cache hit) made since the run started, then
    `result` with the full state, or `error`. Nothing is replayed or simulated.
    LLM call events come from the shared client, so two runs at the same time
    would see each other's calls.
    """
    denied = _check_repo_path(req.repo_path) or _rate_limited(request)
    if denied:
        return denied

    return _stream_work(lambda on_trace, cancel: orchestrator.process(
        query=req.query,
        repo_path=req.repo_path,
        force_intent=req.force_intent,
        on_trace=on_trace,
        cancel_event=cancel,
    ).to_dict())


def _stream_work(work) -> StreamingResponse:
    """Runs work(on_trace, cancel_event) -> result dict on a thread and streams it as SSE."""
    events: "queue.Queue" = queue.Queue()
    started = time.time()
    run_id = uuid.uuid4().hex[:12]
    cancel = threading.Event()

    def worker() -> None:
        try:
            events.put(("result", work(lambda step: events.put(("trace", step)), cancel)))
        except RunCancelled:
            events.put(("error", {"error": "Run stopped. No further agent steps were run.", "status": "cancelled"}))
        except Exception as err:  # pragma: no cover - surfaced to the client
            logging.getLogger(__name__).exception("Streamed run failed")
            events.put(("error", {"error": str(err), "status": "failed"}))

    def stream():
        _ACTIVE_RUNS[run_id] = cancel
        threading.Thread(target=worker, daemon=True, name="run-stream").start()
        try:
            yield from _stream_events(events, started, run_id)
        finally:
            # Also reached when the client disconnects: stop the pipeline instead of
            # letting it spend model calls nobody is watching.
            cancel.set()
            _ACTIVE_RUNS.pop(run_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/run/cancel")
def cancel_run(req: CancelRequest):
    """Stops a streaming run before its next agent step (the step already running finishes)."""
    cancel = _ACTIVE_RUNS.get(req.run_id)
    if cancel is None:
        return JSONResponse(status_code=404, content={"error": "No running run with that id.", "status": "not_found"})
    cancel.set()
    return {"status": "cancelling", "run_id": req.run_id}


def _stream_events(events: "queue.Queue", started: float, run_id: str):
    seen_calls = set()
    last_beat = time.time()
    yield _sse("start", {"started_at": started, "run_id": run_id})
    while True:
        try:
            kind, payload = events.get(timeout=0.4)
        except queue.Empty:
            kind, payload = None, None
        for call in list(llm_client.recent_calls):
            key = (call.get("at"), call.get("model"), call.get("tokens"))
            if call.get("at", 0) >= started and key not in seen_calls:
                seen_calls.add(key)
                yield _sse("llm", {**call, "elapsed_ms": int((call.get("at", started) - started) * 1000)})
        if kind is None:
            if time.time() - last_beat > 5:
                last_beat = time.time()
                yield _sse("heartbeat", {"elapsed_ms": int((time.time() - started) * 1000)})
            continue
        yield _sse(kind, payload)
        if kind in ("result", "error"):
            break


@app.post("/api/prototype/build/stream")
def build_prototype(req: PrototypeRequest, request: Request):
    """
    Prototype Builder: turns the idea of a finished Startup Assistance run into a
    tiny FastAPI + HTML app in a sandbox folder, then checks, tests, starts and
    probes it. Streams the same SSE events as /api/run/stream; `result` holds
    the state with `final_output` = the build (files, checks, endpoints).
    """
    from agents.conversation_session import session_manager
    from agents.prototype_agent import prototype_builder

    session = session_manager.get_session(req.session_id)
    idea = (session.active_entities.get("final_output") if session else None) or {}
    if idea.get("type") != "idea_validation":
        return JSONResponse(status_code=404, content={
            "status": "failed", "error": "No idea result found for this session. Run Startup Assistance first.",
        })
    denied = _rate_limited(request)
    if denied:
        return denied

    def work(on_trace, cancel):
        state = AgentWorkflowState(session_id=req.session_id, user_query=idea.get("project_title", ""),
                                   intent="prototype", listener=on_trace)
        state.final_output = prototype_builder.build(idea, state)
        state.finalize()
        return state.to_dict()

    return _stream_work(work)


def _prototype_or_404(proto_id: str):
    if not prototype_sandbox.valid_id(proto_id) or not prototype_sandbox.proto_path(proto_id).is_dir():
        raise HTTPException(status_code=404, detail="Prototype not found.")


@app.get("/api/prototype/{proto_id}")
def get_prototype(proto_id: str):
    """The saved build (files, checks) plus the live monitor status."""
    _prototype_or_404(proto_id)
    return {"build": prototype_sandbox.load_build(proto_id), "status": prototype_sandbox.processes.status(proto_id)}


@app.get("/api/prototype/{proto_id}/status")
def prototype_status(proto_id: str):
    """Monitor: process state, uptime, request counts, errors and recent requests."""
    _prototype_or_404(proto_id)
    return prototype_sandbox.processes.status(proto_id)


@app.post("/api/prototype/{proto_id}/start")
def start_prototype(proto_id: str):
    _prototype_or_404(proto_id)
    result = prototype_sandbox.processes.start(proto_id)
    return {**result, "status": prototype_sandbox.processes.status(proto_id)}


@app.post("/api/prototype/{proto_id}/stop")
def stop_prototype(proto_id: str):
    _prototype_or_404(proto_id)
    prototype_sandbox.processes.stop(proto_id)
    return prototype_sandbox.processes.status(proto_id)


@app.get("/api/prototype/{proto_id}/download")
def download_prototype(proto_id: str):
    _prototype_or_404(proto_id)
    return Response(
        content=prototype_sandbox.zip_bytes(proto_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="prototype-{proto_id}.zip"'},
    )


@app.post("/api/followup")
def execute_followup(req: FollowupRequest):
    """Answers conversational follow-up questions with persistent repository session context."""
    denied = _check_repo_path(req.repo_path)
    if denied:
        return denied
    try:
        result = orchestrator.answer_followup(
            query=req.query,
            context=req.context,
            session_id=req.session_id,
            repo_path=req.repo_path,
        )
        return JSONResponse(content=result)
    except Exception as err:
        return JSONResponse(
            status_code=500,
            content={"error": str(err), "status": "failed"},
        )


@app.post("/api/inspect-repo")
def inspect_repository(req: InspectRepoRequest):
    """Parses a local Python codebase or safely shallow-clones and indexes a remote GitHub repository."""
    target = req.repo_path.strip()
    from indexer.github_ingest import github_ingest_service

    if github_ingest_service.is_valid_github_url(target):
        ingest_res = github_ingest_service.ingest(target)
        if ingest_res.status != "ok":
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": ingest_res.error_message or "Failed to clone GitHub repository."},
            )
        summary = (
            ingest_res.codebase_index.get_summary()
            if ingest_res.codebase_index
            else {"total_files": ingest_res.total_files, "total_chunks": ingest_res.total_symbols}
        )
        return JSONResponse(
            content={
                "status": "ok",
                "summary": summary,
                "local_path": ingest_res.local_path,
                "repo_name": ingest_res.repo_name,
                "is_remote": True,
            }
        )

    if not os.path.isdir(target):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Path '{target}' is not a folder on disk."},
        )
    if not _local_path_allowed(target):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "message": f"Path '{target}' is outside ALLOWED_REPO_ROOTS."},
        )
    try:
        index = index_cache.get_index(target, max_files=settings.max_repo_files)
        return JSONResponse(
            content={
                "status": "ok",
                "summary": index.get_summary(),
                "local_path": target,
                "is_remote": False,
            }
        )
    except Exception as err:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(err)},
        )


@app.get("/api/sample-repo-path")
def get_sample_repo_path():
    """Returns the normalized absolute path to the built-in sample demo repository."""
    return JSONResponse(content={"path": str(SAMPLE_REPO_PATH).replace("\\", "/")})


@app.get("/health")
@app.get("/api/health")
def health_check():
    """Returns active model settings, runtime metrics, and rate-limit cooldown state."""
    return JSONResponse(
        content={
            "status": "online",
            "model": settings.primary_model,
            "model_chain": settings.model_chain,
            "metrics": llm_client.get_metrics(),
            "rate_limits": llm_client.get_rate_limit_status(),
            "indexed_repos_cached": index_cache.cached_repo_count(),
        }
    )


@app.get("/v1/models")
@app.get("/models")
def list_models():
    """Returns active model list in standard OpenAI-compatible format to avoid 404 polling errors."""
    models_list = []
    seen = set()
    for m in [settings.primary_model] + (settings.model_chain or []):
        if m and m not in seen:
            seen.add(m)
            models_list.append({"id": m, "object": "model", "owned_by": "copilot", "permission": []})
    return JSONResponse(content={"object": "list", "data": models_list})



@app.get("/api/agents")
def list_specialist_agents():
    """Returns the direct-interrogation agent catalog used by the UI chat chips."""
    from agents.conversation_session import ConversationalFollowupEngine
    return JSONResponse(content={"status": "ok", "agents": ConversationalFollowupEngine.get_direct_agent_catalog()})


@app.get("/api/session/{session_id}")
def get_session_info(session_id: str):
    """Returns conversation history and active entities for a session."""
    from agents.conversation_session import session_manager
    session = session_manager.get_session(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"status": "not_found", "message": f"Session '{session_id}' not found."})
    return JSONResponse(content={"status": "ok", "session": session.to_dict()})


# --- Synopsis alignment layer (branch `muse`, Eval-1) ---
@app.get("/api/graph")
def get_graph_spec():
    from agents.graph import graph_spec
    return JSONResponse(content={"status": "ok", "graph": graph_spec()})


@app.post("/api/graph/run")
def run_graph(req: QueryRequest, request: Request):
    from agents.graph import run
    denied = _check_repo_path(req.repo_path) or _rate_limited(request)
    if denied:
        return denied
    try:
        return JSONResponse(content=run(query=req.query, repo_path=req.repo_path, force_intent=req.force_intent))
    except Exception as err:
        return JSONResponse(status_code=500, content={"error": str(err), "status": "failed"})


@app.get("/api/synopsis/agents")
def get_synopsis_agents():
    from agents.synopsis_agents import get_canonical_catalog
    return JSONResponse(content={"status": "ok", "agents": get_canonical_catalog()})


@app.get("/api/kb/lookup")
def kb_lookup(q: str, top_k: int = 3):
    from indexer.knowledge_base import knowledge_base
    return JSONResponse(content={"status": "ok", "hits": [h.to_dict() for h in knowledge_base.lookup(q, top_k=top_k)]})


@app.get("/api/session-store/{session_id}")
def get_stored_session(session_id: str):
    from agents import session_store
    data = session_store.load_session(session_id)
    if not data:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return JSONResponse(content={"status": "ok", "session": data})


if __name__ == "__main__":
    # Default to 127.0.0.1 so browsers on Windows/macOS can click/open the URL directly.
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = os.getenv("RELOAD", "1") not in ("0", "false", "False")
    print(f"\n[Agentic Co-Pilot] Running at: http://localhost:{port} (http://127.0.0.1:{port})\n")
    uvicorn.run("app:app", host=host, port=port, reload=reload_enabled)
