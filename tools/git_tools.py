"""Git history tools via GitPython with stdlib fallback (synopsis Sec 9).

Used by the Diagnosis Agent: recent changes to suspect files, blame line.
If GitPython is missing or path is not a repo, returns structured
'unavailable' payloads instead of raising, so the pipeline never breaks.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def recent_commits(repo_path: str, limit: int = 10) -> Dict[str, Any]:
    try:
        from git import Repo  # type: ignore
        repo = Repo(repo_path)
        out = [{"hexsha": c.hexsha[:8], "message": c.message.strip().splitlines()[0][:120],
                "author": str(c.author), "date": str(c.committed_datetime)}
               for c in list(repo.iter_commits(max_count=limit))]
        return {"status": "ok", "backend": "GitPython", "commits": out}
    except Exception as err:
        # Fallback: plain git CLI; final fallback: unavailable marker.
        try:
            proc = subprocess.run(["git", "-C", repo_path, "log", f"-{limit}",
                                   "--pretty=format:%h|%an|%ad|%s", "--date=short"],
                                  capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                commits: List[Dict[str, str]] = []
                for line in proc.stdout.strip().splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append({"hexsha": parts[0], "author": parts[1],
                                        "date": parts[2], "message": parts[3]})
                return {"status": "ok", "backend": "git-cli", "commits": commits}
        except Exception:
            pass
        return {"status": "unavailable", "backend": "none", "message": str(err), "commits": []}


def blame_file(repo_path: str, rel_file: str, line: int) -> Dict[str, Any]:
    try:
        from git import Repo  # type: ignore
        repo = Repo(repo_path)
        blame = repo.blame("HEAD", rel_file)
        cursor = 0
        for commit, lines in blame:
            cursor += len(lines)
            if line <= cursor:
                return {"status": "ok", "backend": "GitPython",
                        "commit": commit.hexsha[:8], "author": str(commit.author),
                        "date": str(commit.committed_datetime)}
        return {"status": "not_found", "backend": "GitPython"}
    except Exception as err:
        return {"status": "unavailable", "backend": "none", "message": str(err)}


def is_repo(path: str) -> bool:
    return (Path(path) / ".git").exists()
