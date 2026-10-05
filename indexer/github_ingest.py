"""
Safe GitHub Repository Ingestion Engine.
Clones remote GitHub repositories via shallow clone (depth 1) into an isolated workspace,
applies strict safety filters to exclude non-code, secrets, and binary files,
and indexes the codebase with our AST indexer in strict read-only mode.
"""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from indexer.ast_parser import ASTCodeIndexer, CodebaseIndex


@dataclass
class IngestionResult:
    status: str  # 'ok', 'error'
    repo_name: str
    repo_url: str
    local_path: str
    total_files: int
    total_symbols: int
    branch: str = "default"
    codebase_index: Optional[CodebaseIndex] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "repo_name": self.repo_name,
            "repo_url": self.repo_url,
            "local_path": self.local_path,
            "total_files": self.total_files,
            "total_symbols": self.total_symbols,
            "branch": self.branch,
            "error_message": self.error_message,
        }


class GitHubIngestionService:
    """
    Safely clones and indexes remote GitHub repositories.
    Guarantees 100% read-only analysis without code execution.
    """

    GITHUB_URL_PATTERN = re.compile(
        r"^https:\/\/github\.com\/([a-zA-Z0-9_\.-]+)\/([a-zA-Z0-9_\.-]+?)(?:\.git)?\/?$"
    )

    def __init__(self, workspace_root: Optional[str] = None, max_files: int = 400):
        self.workspace_root = workspace_root or tempfile.gettempdir()
        self.max_files = max_files
        self._cache: Dict[str, IngestionResult] = {}

    def is_valid_github_url(self, url: str) -> bool:
        """Validates that the input is a well-formed GitHub HTTPS repository URL."""
        if not url:
            return False
        return bool(self.GITHUB_URL_PATTERN.match(url.strip()))

    def extract_repo_name(self, url: str) -> str:
        """Extracts owner/repo name from URL."""
        match = self.GITHUB_URL_PATTERN.match(url.strip())
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return "unknown/repository"

    def ingest(self, repo_url: str, branch: Optional[str] = None) -> IngestionResult:
        """
        Executes shallow clone and AST indexing over the target repository.
        """
        clean_url = repo_url.strip()
        if not self.is_valid_github_url(clean_url):
            return IngestionResult(
                status="error",
                repo_name="invalid",
                repo_url=clean_url,
                local_path="",
                total_files=0,
                total_symbols=0,
                error_message="Invalid GitHub URL format. Must be https://github.com/owner/repository",
            )

        cache_key = f"{clean_url}@{branch or 'default'}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if os.path.exists(cached.local_path):
                return cached

        repo_ident = self.extract_repo_name(clean_url).replace("/", "_")
        dest_dir = tempfile.mkdtemp(prefix=f"agentic_gh_{repo_ident}_", dir=self.workspace_root)

        try:
            # 1. Run git shallow clone (depth 1)
            cmd = ["git", "clone", "--depth", "1"]
            if branch:
                cmd.extend(["--branch", branch])
            cmd.extend([clean_url, dest_dir])

            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=50,
            )

            if res.returncode != 0:
                shutil.rmtree(dest_dir, ignore_errors=True)
                return IngestionResult(
                    status="error",
                    repo_name=repo_ident,
                    repo_url=clean_url,
                    local_path="",
                    total_files=0,
                    total_symbols=0,
                    error_message=f"Git clone failed: {res.stderr.strip() or res.stdout.strip()}",
                )

            # 2. Run AST Indexer over cloned repository
            indexer = ASTCodeIndexer(repo_path=dest_dir, max_files=self.max_files)
            codebase_index = indexer.index()

            result = IngestionResult(
                status="ok",
                repo_name=self.extract_repo_name(clean_url),
                repo_url=clean_url,
                local_path=dest_dir,
                total_files=len(codebase_index.file_list),
                total_symbols=len(codebase_index.chunks),
                branch=branch or "default",
                codebase_index=codebase_index,
            )
            self._cache[cache_key] = result
            return result

        except subprocess.TimeoutExpired:
            shutil.rmtree(dest_dir, ignore_errors=True)
            return IngestionResult(
                status="error",
                repo_name=repo_ident,
                repo_url=clean_url,
                local_path="",
                total_files=0,
                total_symbols=0,
                error_message="Git clone timed out after 50 seconds.",
            )
        except Exception as e:
            shutil.rmtree(dest_dir, ignore_errors=True)
            return IngestionResult(
                status="error",
                repo_name=repo_ident,
                repo_url=clean_url,
                local_path="",
                total_files=0,
                total_symbols=0,
                error_message=f"Ingestion error: {str(e)}",
            )


# Global singleton instance
github_ingest_service = GitHubIngestionService()
