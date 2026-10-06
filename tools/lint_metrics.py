"""Ruff + Radon lint/complexity wrappers with graceful fallback.

Synopsis Sec 9 lists Ruff and Radon. If installed, use them for real
lint/complexity evidence; otherwise fall back to the built-in
`StaticCodeAnalyzer` so Eval-1 runs on any lab machine.
"""

import shutil
import subprocess
from typing import Any, Dict


def ruff_check(file_path: str) -> Dict[str, Any]:
    exe = shutil.which("ruff")
    if not exe:
        return {"status": "unavailable", "backend": "none",
                "message": "ruff not installed; using built-in analyzer"}
    try:
        proc = subprocess.run([exe, "check", file_path, "--output-format", "concise"],
                              capture_output=True, text=True, timeout=20)
        return {"status": "ok" if proc.returncode == 0 else "issues",
                "backend": "ruff", "output": (proc.stdout + proc.stderr)[:2000]}
    except Exception as err:
        return {"status": "error", "backend": "ruff", "message": str(err)}


def radon_complexity(code: str, symbol: str = "snippet") -> Dict[str, Any]:
    try:
        from radon.complexity import cc_visit  # type: ignore
        blocks = cc_visit(code)
        rows = [{"name": b.name, "complexity": b.complexity, "rank": b.rank}
                for b in blocks]
        return {"status": "ok", "backend": "radon", "blocks": rows}
    except Exception:
        from tools.static_analyzer import static_analyzer
        metrics = static_analyzer.analyze_code_snippet(code, symbol)
        return {"status": "fallback", "backend": "builtin", "metrics": metrics.to_dict()}
