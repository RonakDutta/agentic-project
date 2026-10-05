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


@app.post("/api/inspect-repo")
async def inspect_repository(req: InspectRepoRequest):
    """Parses a local Python codebase and returns AST structural statistics."""
    if not os.path.exists(req.repo_path):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Path '{req.repo_path}' does not exist on disk."},
        )
    try:
        indexer = ASTCodeIndexer(repo_path=req.repo_path)
        index = indexer.index()
        return JSONResponse(content={"status": "ok", "summary": index.get_summary()})
    except Exception as err:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(err)},
        )


@app.get("/api/sample-repo-path")
async def get_sample_repo_path():
    """Returns the normalized absolute path to the built-in sample demo repository."""
    return JSONResponse(content={"path": str(SAMPLE_REPO_PATH).replace("\\", "/")})


@app.get("/api/health")
async def health_check():
    """Returns active model settings and runtime metrics."""
    return JSONResponse(
        content={
            "status": "online",
            "model": settings.primary_model,
            "fast_model": settings.fast_model,
            "metrics": llm_client.get_metrics(),
        }
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
