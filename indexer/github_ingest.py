"""
Safe GitHub Repository Ingestion Engine.
Clones remote GitHub repositories via shallow clone (depth 1) into an isolated workspace,
applies strict safety filters to exclude non-code, secrets, and binary files,
and indexes the codebase with our AST indexer in strict read-only mode.
"""

import atexit
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
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

    MAX_CACHED_CLONES = 6

    def __init__(self, workspace_root: Optional[str] = None, max_files: Optional[int] = None,
                 max_clone_mb: Optional[int] = None):
        from core.config import settings
        self.workspace_root = workspace_root or tempfile.gettempdir()
        self.max_files = max_files or settings.max_repo_files
        self.max_clone_mb = max_clone_mb or settings.max_clone_mb
        # url@branch -> result; oldest clones are deleted from disk when evicted.
        self._cache: "OrderedDict[str, IngestionResult]" = OrderedDict()
        self._lock = threading.Lock()
        atexit.register(self.cleanup)

    def cleanup(self) -> None:
        """Deletes every clone this process made (also runs at interpreter exit)."""
        with self._lock:
            for result in self._cache.values():
                if result.local_path:
                    shutil.rmtree(result.local_path, ignore_errors=True)
            self._cache.clear()

    def _remember(self, key: str, result: IngestionResult) -> None:
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self.MAX_CACHED_CLONES:
                _, old = self._cache.popitem(last=False)
                if old.local_path:
                    shutil.rmtree(old.local_path, ignore_errors=True)

    @staticmethod
    def _dir_size_mb(path: str) -> float:
        total = 0
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total / (1024 * 1024)

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

        cache_key = f"{clean_url.rstrip('/').removesuffix('.git').lower()}@{branch or 'default'}"
        with self._lock:
            cached = self._cache.get(cache_key)
        if cached and os.path.exists(cached.local_path):
            return cached

        repo_ident = self.extract_repo_name(clean_url).replace("/", "_")
        dest_dir = tempfile.mkdtemp(prefix=f"agentic_gh_{repo_ident}_", dir=self.workspace_root)

        try:
            # 1. Run git shallow clone (depth 1)
            cmd = ["git", "clone", "--depth", "1", "--single-branch", "--no-tags"]
            if branch:
                cmd.extend(["--branch", branch])
            cmd.extend([clean_url, dest_dir])

            # GIT_TERMINAL_PROMPT=0: a private or misspelled repo fails at once
            # instead of hanging the request on an invisible username prompt.
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="echo")
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=50,
                env=env,
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

            size_mb = self._dir_size_mb(dest_dir)
            if size_mb > self.max_clone_mb:
                shutil.rmtree(dest_dir, ignore_errors=True)
                return IngestionResult(
                    status="error",
                    repo_name=repo_ident,
                    repo_url=clean_url,
                    local_path="",
                    total_files=0,
                    total_symbols=0,
                    error_message=(
                        f"Repository is {size_mb:.0f} MB, above the {self.max_clone_mb} MB limit "
                        "(MAX_CLONE_MB). Try a smaller repository."
                    ),
                )

            # 2. Run AST Indexer over cloned repository (shared with the index cache)
            from indexer import index_cache
            codebase_index = index_cache.get_index(dest_dir, max_files=self.max_files)

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
            self._remember(cache_key, result)
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
