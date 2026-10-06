"""
FastAPI Server and Web API for Agentic AI Co-Pilot.
Serves the browser dashboard and exposes REST endpoints for multi-agent execution.
"""

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from core.config import settings
from core.llm import llm_client
from indexer.ast_parser import ASTCodeIndexer
from agents.orchestrator import orchestrator

app = FastAPI(
    title="Agentic AI Co-Pilot API",
    description="Multi-Agent RAG System for Idea Validation and Codebase Analysis",
    version="1.0.0",
)

ROOT_DIR = Path(__file__).resolve().parent
HTML_PATH = ROOT_DIR / "web" / "templates" / "index.html"
SAMPLE_REPO_PATH = ROOT_DIR / "sample_repo"


class QueryRequest(BaseModel):
    query: str
    repo_path: Optional[str] = None
    force_intent: Optional[str] = None


class InspectRepoRequest(BaseModel):
    repo_path: str


class FollowupRequest(BaseModel):
    query: str
    context: Optional[dict] = None
    session_id: Optional[str] = None
    repo_path: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the main interactive dashboard."""
    if not HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Dashboard template not found.")
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.post("/api/query")
async def execute_query(req: QueryRequest):
    """Executes the multi-agent orchestrator pipeline."""
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


@app.post("/api/followup")
async def execute_followup(req: FollowupRequest):
    """Answers conversational follow-up questions with persistent repository session context."""
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
async def inspect_repository(req: InspectRepoRequest):
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

    if not os.path.exists(target):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Path '{target}' does not exist on disk."},
        )
    try:
        indexer = ASTCodeIndexer(repo_path=target)
        index = indexer.index()
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
async def get_sample_repo_path():
    """Returns the normalized absolute path to the built-in sample demo repository."""
    return JSONResponse(content={"path": str(SAMPLE_REPO_PATH).replace("\\", "/")})


@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Returns active model settings, runtime metrics, and rate-limit cooldown state."""
    return JSONResponse(
        content={
            "status": "online",
            "model": settings.primary_model,
            "model_chain": settings.model_chain,
            "metrics": llm_client.get_metrics(),
            "rate_limits": llm_client.get_rate_limit_status(),
        }
    )


@app.get("/v1/models")
@app.get("/models")
async def list_models():
    """Returns active model list in standard OpenAI-compatible format to avoid 404 polling errors."""
    models_list = []
    seen = set()
    for m in [settings.primary_model] + (settings.model_chain or []):
        if m and m not in seen:
            seen.add(m)
            models_list.append({"id": m, "object": "model", "owned_by": "groq", "permission": []})
    return JSONResponse(content={"object": "list", "data": models_list})



@app.get("/api/agents")
async def list_specialist_agents():
    """Returns the direct-interrogation agent catalog used by the UI chat chips."""
    from agents.conversation_session import ConversationalFollowupEngine
    return JSONResponse(content={"status": "ok", "agents": ConversationalFollowupEngine.get_direct_agent_catalog()})


@app.get("/api/session/{session_id}")
async def get_session_info(session_id: str):
    """Returns conversation history and active entities for a session."""
    from agents.conversation_session import session_manager
    session = session_manager.get_session(session_id)
    if not session:
        return JSONResponse(status_code=404, content={"status": "not_found", "message": f"Session '{session_id}' not found."})
    return JSONResponse(content={"status": "ok", "session": session.to_dict()})


# --- Synopsis alignment layer (branch `muse`, Eval-1) ---
@app.get("/api/graph")
async def get_graph_spec():
    from agents.graph import graph_spec
    return JSONResponse(content={"status": "ok", "graph": graph_spec()})


@app.post("/api/graph/run")
async def run_graph(req: QueryRequest):
    from agents.graph import run
    try:
        return JSONResponse(content=run(query=req.query, repo_path=req.repo_path, force_intent=req.force_intent))
    except Exception as err:
        return JSONResponse(status_code=500, content={"error": str(err), "status": "failed"})


@app.get("/api/synopsis/agents")
async def get_synopsis_agents():
    from agents.synopsis_agents import get_canonical_catalog
    return JSONResponse(content={"status": "ok", "agents": get_canonical_catalog()})


@app.get("/api/kb/lookup")
async def kb_lookup(q: str, top_k: int = 3):
    from indexer.knowledge_base import knowledge_base
    return JSONResponse(content={"status": "ok", "hits": [h.to_dict() for h in knowledge_base.lookup(q, top_k=top_k)]})


@app.get("/api/session-store/{session_id}")
async def get_stored_session(session_id: str):
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
