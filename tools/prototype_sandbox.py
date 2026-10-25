"""
Prototype sandbox: checks, tests, runs and monitors a generated prototype.

Everything here is plain code (no AI). A prototype lives in its own folder
under PROTOTYPE_DIR and is never written into the user's repositories.

Safety is layered, not a container:
- an AST check rejects imports outside a small allowlist (no os, subprocess,
  socket, requests, ...), dunder access and eval/exec/open before anything runs;
- tests and the server run in a subprocess with a time limit, a minimal
  environment (no API keys) and the server bound to 127.0.0.1 only;
- the page is served with a Content-Security-Policy that blocks outside
  scripts and network calls;
- a running prototype is stopped automatically after PROTOTYPE_TTL_SECONDS.
"""

import ast
import atexit
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import settings

# Outside the project on purpose: `python app.py` runs uvicorn with auto-reload,
# which watches the project folder. Writing a prototype's .py files inside it
# made the server restart and stop the prototype right after it started.
PROTOTYPE_DIR = Path(os.getenv("PROTOTYPE_DIR", str(Path.home() / ".agentic-copilot" / "prototypes")))
PROTOTYPE_TTL_SECONDS = int(os.getenv("PROTOTYPE_TTL_SECONDS", "1200"))
TEST_TIMEOUT_SECONDS = int(os.getenv("PROTOTYPE_TEST_TIMEOUT", "90"))
START_TIMEOUT_SECONDS = 20

_ID_RE = re.compile(r"^[a-f0-9]{8,16}$")

# Modules generated code may import. Everything that can touch files, processes
# or the network is left out on purpose.
ALLOWED_IMPORTS = {
    "__future__", "fastapi", "pydantic", "typing", "typing_extensions", "datetime", "uuid",
    "random", "math", "statistics", "collections", "dataclasses", "enum", "re", "json",
    "itertools", "functools", "time", "string", "decimal",
}
TEST_IMPORTS = ALLOWED_IMPORTS | {"pytest", "main", "features"}
BANNED_NAMES = {
    "eval", "exec", "open", "compile", "__import__", "globals", "locals", "vars", "input",
    "breakpoint", "exit", "quit", "help", "memoryview", "__builtins__",
    # Reflection could reach the blocked names below; FileResponse and StaticFiles
    # could serve any file on the computer. main.py (our template) is not checked.
    "getattr", "setattr", "delattr", "FileResponse", "StaticFiles",
}
# Allowed packages whose sub-modules can read files from disk.
BANNED_MODULES = ("fastapi.staticfiles", "fastapi.responses.FileResponse", "starlette")
_EXTERNAL_HTML_RE = re.compile(
    r"<script[^>]+src\s*=\s*[\"']?(?:https?:)?//|<link[^>]+href\s*=\s*[\"']?(?:https?:)?//|"
    r"@import\s+url\(\s*[\"']?(?:https?:)?//|<iframe|<object|<embed",
    re.IGNORECASE,
)
MAX_PY_BYTES = 30_000
MAX_HTML_BYTES = 40_000

# Requests the builder itself makes carry this header, so the monitor can tell
# them apart from requests made by a person using the prototype.
CHECK_HEADER = "X-Prototype-Check"


def valid_id(proto_id: str) -> bool:
    return bool(_ID_RE.match(proto_id or ""))


def proto_path(proto_id: str) -> Path:
    if not valid_id(proto_id):
        raise ValueError("Invalid prototype id.")
    return PROTOTYPE_DIR / proto_id


# ---------------------------------------------------------------- checks

def safety_check(files: Dict[str, str]) -> List[str]:
    """Returns a list of problems (empty = safe to run). Nothing is executed."""
    issues: List[str] = []
    for name, source in files.items():
        if name.endswith(".py"):
            if len(source.encode("utf-8")) > MAX_PY_BYTES:
                issues.append(f"{name}: file is too large ({len(source)} characters).")
                continue
            try:
                tree = ast.parse(source, filename=name)
            except SyntaxError:
                continue  # reported by compile_check with a line number
            allowed = TEST_IMPORTS if name.startswith("test_") else ALLOWED_IMPORTS
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root not in allowed or alias.name.startswith(BANNED_MODULES):
                            issues.append(f"{name}:{node.lineno}: import of '{alias.name}' is not allowed.")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    root = module.split(".")[0]
                    if node.level or root not in allowed or module.startswith(BANNED_MODULES):
                        issues.append(f"{name}:{node.lineno}: import from '{module or '.'}' is not allowed.")
                    for alias in node.names:
                        if alias.name in BANNED_NAMES:
                            issues.append(f"{name}:{node.lineno}: import of '{alias.name}' is not allowed.")
                elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
                    issues.append(f"{name}:{node.lineno}: use of '{node.id}' is not allowed.")
                elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
                    issues.append(f"{name}:{node.lineno}: access to '{node.attr}' is not allowed.")
                elif isinstance(node, ast.Attribute) and (node.attr in BANNED_NAMES or node.attr in ("staticfiles", "FileResponse")):
                    issues.append(f"{name}:{node.lineno}: use of '{node.attr}' is not allowed.")
        elif name.endswith(".html"):
            if len(source.encode("utf-8")) > MAX_HTML_BYTES:
                issues.append(f"{name}: page is too large ({len(source)} characters).")
            match = _EXTERNAL_HTML_RE.search(source)
            if match:
                line = source[: match.start()].count("\n") + 1
                issues.append(f"{name}:{line}: outside scripts, styles or frames are not allowed.")
    if "features.py" in files and not re.search(r"^router\s*=", files["features.py"], re.MULTILINE):
        issues.append("features.py: must define 'router = APIRouter(...)'.")
    return issues


def compile_check(files: Dict[str, str]) -> List[str]:
    """Compiles every Python file without running it; returns the errors."""
    errors = []
    for name, source in files.items():
        if not name.endswith(".py"):
            continue
        try:
            compile(source, name, "exec")
        except SyntaxError as err:
            errors.append(f"{name}:{err.lineno}: {err.msg}")
    return errors


_ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
_PAGE_API_RE = re.compile(r"""["'`](/api/[^"'`\s?#]*)""")


def api_routes(source: str) -> List[str]:
    """Routes declared in features.py, read from the code (prefix + @router.<method>("...")), not run."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    prefix, routes = "", []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = str(kw.value.value)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                        and deco.func.attr in _ROUTE_METHODS and deco.args
                        and isinstance(deco.args[0], ast.Constant)):
                    routes.append(str(deco.args[0].value))
    return [(prefix.rstrip("/") + r) or "/" for r in routes]


def _route_matches(called: str, route: str) -> bool:
    """`called` comes from the page: "${...}" stands for one value, a trailing "/" means a value follows."""
    want = called.rstrip("/").split("/")
    have = route.rstrip("/").split("/")
    if called.endswith("/") and called != "/":
        want.append("${}")  # "/api/items/" + id
    if len(want) != len(have):
        return False
    return all(w == h or "${" in w or (h.startswith("{") and h.endswith("}")) for w, h in zip(want, have))


def page_api_check(files: Dict[str, str]) -> List[str]:
    """Every /api/... path the page calls must exist in features.py. Read from the code, nothing runs."""
    page, features = files.get("static/index.html", ""), files.get("features.py", "")
    routes = api_routes(features)
    if not page or not routes:
        return []
    issues = []
    for called in sorted(set(_PAGE_API_RE.findall(page))):
        if not any(_route_matches(called, route) for route in routes):
            issues.append(f"static/index.html calls {called} but features.py has no such route "
                          f"(routes: {', '.join(sorted(set(routes)))}).")
    return issues


_runtime_ok = False


def runtime_check() -> str:
    """Checks the packages a prototype needs can be imported in the sandbox. Returns "" when fine."""
    global _runtime_ok
    if _runtime_ok:
        return ""
    PROTOTYPE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(
            [sys.executable, "-c", "import fastapi, uvicorn, pytest, httpx"],
            cwd=PROTOTYPE_DIR, env=_sandbox_env(PROTOTYPE_DIR), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"Could not start Python for the prototype: {err}"
    if done.returncode != 0:
        missing = re.search(r"No module named '([\w.]+)'", done.stderr or "")
        name = missing.group(1) if missing else "a package"
        return (f"Python cannot import {name} for the prototype. "
                f"Run: pip install fastapi uvicorn pytest httpx")
    _runtime_ok = True
    return ""


# ---------------------------------------------------------------- files

def write_files(proto_id: str, files: Dict[str, str]) -> Path:
    root = proto_path(proto_id)
    for name, content in files.items():
        target = (root / name).resolve()
        if root.resolve() not in target.parents:
            raise ValueError(f"Refusing to write outside the sandbox: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    # Keeps pytest's root inside the sandbox, away from the project's own tests.
    (root / "pytest.ini").write_text("[pytest]\naddopts = -p no:cacheprovider\n", encoding="utf-8")
    return root


def save_build(proto_id: str, build: Dict[str, Any]) -> None:
    (proto_path(proto_id) / "build.json").write_text(json.dumps(build, indent=2, default=str), encoding="utf-8")


def load_build(proto_id: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads((proto_path(proto_id) / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def zip_bytes(proto_id: str) -> bytes:
    """The prototype source as a zip (logs and build metadata left out)."""
    root = proto_path(proto_id)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".html", ".css", ".ini", ".md", ".txt"):
                archive.write(path, f"prototype-{proto_id}/{path.relative_to(root).as_posix()}")
    return buffer.getvalue()


# ---------------------------------------------------------------- subprocesses

def _site_dirs() -> List[str]:
    """Where this Python finds its installed packages (also user installs and venvs)."""
    return [p for p in sys.path if p and ("site-packages" in p or "dist-packages" in p) and os.path.isdir(p)]


def _sandbox_env(root: Path) -> Dict[str, str]:
    """A minimal environment: no API keys, no proxy settings, no project paths."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        # The site folders are passed on explicitly: with a minimal environment a
        # `pip install --user` (the default on many Windows setups) is not found.
        "PYTHONPATH": os.pathsep.join([str(root)] + _site_dirs()),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    # Needed on Windows (sockets, temp files, user folders) and for the locale. No secrets.
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "HOME", "USERPROFILE",
                "APPDATA", "LOCALAPPDATA", "USERNAME", "USER"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def run_tests(proto_id: str) -> Dict[str, Any]:
    """Runs the generated tests with pytest in a subprocess; returns real counts and output."""
    root = proto_path(proto_id)
    started = time.time()
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-rfE", "test_features.py"],
            cwd=root, env=_sandbox_env(root), capture_output=True, text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
        output = (done.stdout or "") + (done.stderr or "")
        exit_code = done.returncode
    except subprocess.TimeoutExpired:
        output, exit_code = f"Tests stopped after {TEST_TIMEOUT_SECONDS}s (time limit).", -1

    def count(word: str) -> int:
        match = re.search(rf"(\d+) {word}", output)
        return int(match.group(1)) if match else 0

    passed, failed, errors = count("passed"), count("failed"), count("errors?")
    return {
        "ok": exit_code == 0 and passed > 0,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "exit_code": exit_code,
        "duration_ms": int((time.time() - started) * 1000),
        "output": output[-4000:],
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# The prototype runs on 127.0.0.1; never send these requests through a proxy.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(url: str, timeout: float = 3.0) -> Dict[str, Any]:
    started = time.time()
    request = urllib.request.Request(url, headers={CHECK_HEADER: "1"})
    try:
        with _LOCAL.open(request, timeout=timeout) as response:
            body = response.read(200_000)
            return {"status": response.status, "ms": int((time.time() - started) * 1000),
                    "body": body, "type": response.headers.get("content-type", "")}
    except urllib.error.HTTPError as err:
        return {"status": err.code, "ms": int((time.time() - started) * 1000), "body": b"", "type": ""}
    except Exception as err:
        return {"status": 0, "ms": int((time.time() - started) * 1000), "body": b"", "type": "", "error": str(err)}


class _Running:
    def __init__(self, proto_id: str, proc: subprocess.Popen, port: int, log_handle):
        self.proto_id = proto_id
        self.proc = proc
        self.port = port
        self.log_handle = log_handle
        self.started_at = time.time()
        self.stopped_reason = ""
        self.timer: Optional[threading.Timer] = None


class PrototypeProcesses:
    """Starts, stops and reports on running prototypes (one at a time)."""

    def __init__(self):
        self._running: Dict[str, _Running] = {}
        self._reasons: Dict[str, str] = {}
        self._lock = threading.RLock()

    def start(self, proto_id: str) -> Dict[str, Any]:
        root = proto_path(proto_id)
        if not (root / "main.py").exists():
            return {"ok": False, "error": "Prototype files not found."}
        with self._lock:
            for other in list(self._running):
                self.stop(other, reason="Another prototype was started.")
            port = _free_port()
            log_handle = (root / "server.log").open("a", encoding="utf-8")
            (root / "requests.log").write_text("", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                 "--port", str(port), "--log-level", "warning"],
                cwd=root, env=_sandbox_env(root), stdout=log_handle, stderr=subprocess.STDOUT,
            )
            running = _Running(proto_id, proc, port, log_handle)
            running.timer = threading.Timer(
                PROTOTYPE_TTL_SECONDS, self.stop, args=(proto_id,),
                kwargs={"reason": f"Stopped automatically after {PROTOTYPE_TTL_SECONDS // 60} minutes."},
            )
            running.timer.daemon = True
            running.timer.start()
            self._running[proto_id] = running
            self._reasons.pop(proto_id, None)

        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if proc.poll() is not None:
                return {"ok": False, "url": url, "port": port,
                        "error": f"The app exited with code {proc.returncode} while starting.",
                        "log": self.server_log(proto_id)}
            health = http_get(url + "/health", timeout=1.5)
            if health["status"] == 200:
                return {"ok": True, "url": url, "port": port, "ms": int((time.time() - running.started_at) * 1000)}
            time.sleep(0.3)
        return {"ok": False, "url": url, "port": port,
                "error": f"No answer from /health within {START_TIMEOUT_SECONDS}s.", "log": self.server_log(proto_id)}

    def stop(self, proto_id: str, reason: str = "Stopped by the user.") -> bool:
        with self._lock:
            running = self._running.pop(proto_id, None)
            if running is None:
                return False
            self._reasons[proto_id] = reason
        if running.timer:
            running.timer.cancel()
        if running.proc.poll() is None:
            running.proc.terminate()
            try:
                running.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                running.proc.kill()
        try:
            running.log_handle.close()
        except Exception:
            pass
        return True

    def stop_all(self) -> None:
        for proto_id in list(self._running):
            self.stop(proto_id, reason="Server shut down.")

    def server_log(self, proto_id: str, lines: int = 20) -> List[str]:
        try:
            text = (proto_path(proto_id) / "server.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [line for line in text.splitlines() if line.strip()][-lines:]

    def status(self, proto_id: str) -> Dict[str, Any]:
        """Live monitor data, read from the process and the prototype's own request log."""
        root = proto_path(proto_id)
        with self._lock:
            running = self._running.get(proto_id)
        if running is not None and running.proc.poll() is not None:
            state, exit_code = "crashed", running.proc.returncode
        elif running is not None:
            state, exit_code = "running", None
        else:
            state, exit_code = "stopped", None

        entries = []
        try:
            for line in (root / "requests.log").read_text(encoding="utf-8").splitlines():
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            pass
        visits = [e for e in entries if not e.get("check")]
        errors = [e for e in entries if int(e.get("status", 0)) >= 500 or e.get("error")]
        client_errors = [e for e in entries if 400 <= int(e.get("status", 0)) < 500]
        times = [int(e.get("ms", 0)) for e in entries]
        return {
            "id": proto_id,
            "state": state,
            "exit_code": exit_code,
            "url": f"http://127.0.0.1:{running.port}" if running else None,
            "uptime_s": int(time.time() - running.started_at) if running else 0,
            "auto_stop_in_s": max(0, int(running.started_at + PROTOTYPE_TTL_SECONDS - time.time())) if running else 0,
            "stopped_reason": self._reasons.get(proto_id, ""),
            "requests_total": len(entries),
            "requests_visitors": len(visits),
            "requests_checks": len(entries) - len(visits),
            "server_errors": len(errors),
            "client_errors": len(client_errors),
            "avg_ms": round(sum(times) / len(times), 1) if times else 0,
            "recent": entries[-12:],
            "recent_errors": errors[-5:],
            "server_log": self.server_log(proto_id, 12) if state != "running" else self.server_log(proto_id, 5),
        }


processes = PrototypeProcesses()
atexit.register(processes.stop_all)
