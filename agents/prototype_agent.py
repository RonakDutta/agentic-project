"""
Prototype Builder Agent: turns a validated idea into a tiny running app.

Steps (each one is a trace step, so the UI shows real progress):
1. Spec Planner (code)     : picks the PRD's top 2-3 "Must Have" requirements.
2. Code Writer (1 AI call) : writes features.py (API), static/index.html (page)
                             and test_features.py. main.py and base.css are fixed
                             templates, so the AI only writes what is specific
                             to the idea.
3. Safety Check (code)     : import allowlist, no eval/exec/open, no outside scripts.
4. Compiler (code)         : compiles every Python file without running it.
5. Test Runner             : pytest in a subprocess with a time limit.
6. Code Fixer (0-1 AI call): only when 3-5 failed; gets the real error output.
7. App Runner              : starts the app on 127.0.0.1 and waits for /health.
8. Endpoint Checker        : calls every GET endpoint from the app's own OpenAPI list.

If the AI is unavailable or its code still fails after one fix, the built-in
fallback prototype is used and labelled (generation_source="fallback").
Everything is written to a sandbox folder, never to the user's repositories.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agents.prototype_templates import BASE_CSS, CSS_CLASSES, MAIN_PY, README, fallback_files
from agents.workflow_state import AgentWorkflowState
from core.llm import llm_client, AGENT_MAX_TOKENS
from tools import prototype_sandbox as sandbox

logger = logging.getLogger(__name__)

AI_FILES = ("features.py", "static/index.html", "test_features.py")
# One code-writing call may take longer than a normal agent step and may wait
# for a per-minute token window to refill instead of falling back at once.
CODE_CALL_TIMEOUT = 90
CODE_CALL_MAX_WAIT = 65

_FILE_RE = re.compile(r"#{2,4}\s*FILE:\s*([\w./-]+)\s*\n+```[a-zA-Z]*\n(.*?)\n```", re.DOTALL)

SYSTEM_PROMPT = f"""You write very small, working FastAPI prototypes for student projects.
Return exactly these three files and nothing else, each as a heading line and one fenced code block:

### FILE: features.py
```python
...
```
### FILE: static/index.html
```html
...
```
### FILE: test_features.py
```python
...
```

Rules for features.py:
- Define `router = APIRouter(prefix="/api")`. A fixed main.py already creates the app, includes this router, serves the page at "/" and has GET /health. Do not create another app.
- 3 to 5 endpoints that implement the given requirements. Keep data in module-level lists or dicts, seeded with 3 to 5 realistic sample records for this idea.
- Use pydantic models for request bodies and raise HTTPException(404) for missing items and HTTPException(422) for invalid values.
- Only import from: fastapi, pydantic, typing, datetime, uuid, random, math, statistics, collections, dataclasses, enum, re, json, itertools, functools, time, string, decimal.
- No files, no network, no os, no subprocess, no eval or exec. Under 110 lines.

Rules for static/index.html:
- One complete page. Link the existing stylesheet with <link rel="stylesheet" href="/static/base.css">. Use only these classes: {CSS_CLASSES}. Add no other CSS except small inline styles.
- Header: <header class="top"><div class="wrap">...</div></header>, then <main class="wrap">. Show the app name, one line saying what it does, a small stats row, a form for the main action and a list or table of records.
- Plain JavaScript with fetch() to the relative /api/... paths. Put text on the page with textContent, never innerHTML with data. Show a short error message when a request fails.
- No outside scripts, fonts, images or CDNs. Under 150 lines.

Rules for test_features.py:
- `from fastapi.testclient import TestClient`, `from main import app`, `client = TestClient(app)`.
- 4 to 6 short tests: each endpoint once, plus one error case (404 or 422). Tests must pass against your features.py.
"""

FIX_PROMPT = """You fix a small FastAPI prototype. The checks below failed.
Return only the files you change, each as a heading line `### FILE: <name>` followed by one fenced code block with the full corrected file.
Keep the same rules: router = APIRouter(prefix="/api") in features.py, only safe imports
(fastapi, pydantic, typing, datetime, uuid, random, math, statistics, collections, dataclasses, enum, re, json, itertools, functools, time, string, decimal),
no files, network, os, subprocess, eval or exec; tests use TestClient(app) from main."""


def build_spec(final_output: Dict[str, Any]) -> Dict[str, Any]:
    """Picks what the prototype should do from the idea result (no AI)."""
    prd = final_output.get("prd") or {}
    reqs = [r for r in (prd.get("functional_requirements") or []) if isinstance(r, dict)]
    rank = {"must have": 0, "should have": 1, "nice to have": 2}
    reqs.sort(key=lambda r: rank.get(str(r.get("priority", "")).lower(), 3))
    chosen = [
        {"id": r.get("req_id", ""), "title": r.get("title", ""), "description": r.get("description", ""),
         "priority": r.get("priority", "")}
        for r in reqs[:3] if r.get("title")
    ]
    if not chosen:  # no PRD requirements: use the MVP feature list instead
        chosen = [
            {"id": f"F-{i + 1}", "title": str(f)[:80], "description": str(f), "priority": "Must Have"}
            for i, f in enumerate((final_output.get("mvp_features") or [])[:3])
        ]
    personas = []
    for p in final_output.get("target_personas") or []:
        personas.append((p.get("name") or p.get("persona") or str(p)) if isinstance(p, dict) else str(p))
    return {
        "title": final_output.get("project_title") or "Prototype",
        "problem": final_output.get("problem_statement", "")[:400],
        "value": final_output.get("core_value_prop", "")[:300],
        "personas": [str(p)[:80] for p in personas[:3]],
        "requirements": chosen,
        "stories": [
            f"As a {s.get('persona', 'user')}, I want {s.get('want', '')}"
            for s in (prd.get("user_stories") or [])[:2] if isinstance(s, dict)
        ],
    }


def parse_files(text: str) -> Dict[str, str]:
    files = {}
    for name, body in _FILE_RE.findall(text or ""):
        name = name.strip().lstrip("./")
        if name in AI_FILES:
            files[name] = body.rstrip() + "\n"
    return files


class PrototypeBuilderAgent:
    def __init__(self):
        self.llm = llm_client

    # ------------------------------------------------------------ AI calls

    def _write_code(self, spec: Dict[str, Any]) -> Tuple[Dict[str, str], str]:
        """One AI call. Returns (files, error)."""
        user = "Build the prototype for this idea:\n" + json.dumps(spec, indent=1)
        try:
            text = self.llm.generate(
                [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                max_tokens=AGENT_MAX_TOKENS["prototype"], timeout=CODE_CALL_TIMEOUT, max_wait=CODE_CALL_MAX_WAIT,
            )
        except Exception as err:
            return {}, str(err)
        files = parse_files(text)
        missing = [f for f in AI_FILES if f not in files]
        if missing:
            return files, f"The answer was missing {', '.join(missing)}."
        return files, ""

    def _fix_code(self, files: Dict[str, str], problems: str) -> Tuple[Dict[str, str], str]:
        """At most one repair call, with the real error output. The page is only sent when it is the problem."""
        send = ["features.py", "test_features.py"] + (["static/index.html"] if "index.html" in problems else [])
        body = "\n".join(f"### FILE: {name}\n```\n{files[name]}\n```" for name in send if name in files)
        user = f"Failed checks:\n{problems[-2500:]}\n\nCurrent files:\n{body}"
        try:
            text = self.llm.generate(
                [{"role": "system", "content": FIX_PROMPT}, {"role": "user", "content": user}],
                max_tokens=AGENT_MAX_TOKENS["prototype_fix"], timeout=CODE_CALL_TIMEOUT, max_wait=CODE_CALL_MAX_WAIT,
            )
        except Exception as err:
            return files, str(err)
        fixed = parse_files(text)
        if not fixed:
            return files, "The fix answer held no files."
        return {**files, **fixed}, ""

    # ------------------------------------------------------------ checks

    @staticmethod
    def _check(proto_id: str, files: Dict[str, str], state: AgentWorkflowState) -> Tuple[bool, str, Dict[str, Any]]:
        """Safety, compile and tests on one set of files. Returns (ok, problems text, checks)."""
        issues = sandbox.safety_check(files)
        state.add_trace(
            "Safety Check",
            "Safe to run: allowed imports only, no eval/exec/open, no outside scripts" if not issues
            else f"Blocked {len(issues)} unsafe line(s)",
            status="completed" if not issues else "warning",
            output_summary=f"{len(issues)} issue(s)",
            details={"issues": issues, "tool": "AST import allowlist (no AI)"},
        )
        if issues:
            return False, "Safety check failed:\n" + "\n".join(issues), {"safety": issues}
        errors = sandbox.compile_check(files)
        state.add_trace(
            "Compiler",
            "All Python files compile" if not errors else f"{len(errors)} syntax error(s)",
            status="completed" if not errors else "warning",
            details={"errors": errors, "tool": "Python compile() (no AI)"},
        )
        if errors:
            return False, "Syntax errors:\n" + "\n".join(errors), {"safety": [], "compile": errors}
        sandbox.write_files(proto_id, files)
        tests = sandbox.run_tests(proto_id)
        state.add_trace(
            "Test Runner",
            f"pytest: {tests['passed']} passed, {tests['failed']} failed" + (f", {tests['errors']} errors" if tests["errors"] else ""),
            status="completed" if tests["ok"] else "warning",
            duration_ms=tests["duration_ms"],
            output_summary=f"{tests['passed']}/{tests['total']} tests passed",
            details={"tool": "pytest in a subprocess, time limit", "exit_code": tests["exit_code"]},
        )
        checks = {"safety": [], "compile": [], "tests": tests}
        return tests["ok"], "" if tests["ok"] else "pytest output:\n" + tests["output"], checks

    # ------------------------------------------------------------ pipeline

    def build(self, final_output: Dict[str, Any], state: AgentWorkflowState) -> Dict[str, Any]:
        proto_id = uuid.uuid4().hex[:10]
        spec = build_spec(final_output)
        state.add_trace(
            "Spec Planner",
            f"Picked {len(spec['requirements'])} requirement(s) for the prototype",
            output_summary=", ".join(r["title"] for r in spec["requirements"])[:200],
            details={"tool": "PRD requirements sorted by priority (no AI)", "requirements": spec["requirements"]},
        )

        # Fixed template files go in first: the generated tests import main.py.
        sandbox.write_files(proto_id, self._template_files(spec, "written by AI"))

        started = time.time()
        files, write_error = self._write_code(spec)
        source, fallback_reason, repaired = "llm", "", False
        state.add_trace(
            "Code Writer",
            f"AI wrote {len(files)} files ({sum(f.count(chr(10)) for f in files.values())} lines)" if not write_error
            else f"AI could not write the code ({write_error[:120]})",
            status="completed" if not write_error else "warning",
            duration_ms=int((time.time() - started) * 1000),
            details={"tool": "AI model, 1 call", "files": list(files)},
        )

        ok, checks = False, {}
        if not write_error:
            ok, problems, checks = self._check(proto_id, files, state)
            if not ok:
                started = time.time()
                files, fix_error = self._fix_code(files, problems)
                repaired = not fix_error
                state.add_trace(
                    "Code Fixer",
                    "AI fixed the code using the real error output" if not fix_error else f"Fix failed ({fix_error[:120]})",
                    status="completed" if not fix_error else "warning",
                    duration_ms=int((time.time() - started) * 1000),
                    details={"tool": "AI model, 1 call", "problems": problems[-1500:]},
                )
                if not fix_error:
                    ok, problems, checks = self._check(proto_id, files, state)
                # Failing tests after the fix are reported as they are; unsafe or
                # broken code is never run, so that case falls back.
                if not ok and checks.get("tests") is None:
                    fallback_reason = f"The AI code still failed after one fix: {problems.splitlines()[0]}"
            else:
                state.add_trace("Code Fixer", "Not needed: every check passed", details={"skipped": True})
        else:
            fallback_reason = write_error

        if fallback_reason:
            source = "fallback"
            files = fallback_files(spec)
            state.add_trace("Code Writer", "Using the built-in MVP planner prototype instead", status="warning",
                            details={"fallback_reason": fallback_reason})
            ok, _, checks = self._check(proto_id, files, state)

        all_files = {**files, **self._template_files(spec, "written by AI" if source == "llm" else "built-in fallback")}
        sandbox.write_files(proto_id, all_files)
        tests = checks.get("tests") or {}

        server = sandbox.processes.start(proto_id)
        state.add_trace(
            "App Runner",
            f"App running at {server.get('url')}" if server["ok"] else f"App did not start: {server.get('error')}",
            status="completed" if server["ok"] else "warning",
            duration_ms=server.get("ms", 0),
            details={"tool": "uvicorn subprocess on 127.0.0.1, auto-stop", "log": server.get("log", [])},
        )

        endpoints = self._check_endpoints(server) if server["ok"] else []
        if server["ok"]:
            called = [e for e in endpoints if e["status"] is not None]
            good = sum(1 for e in called if 200 <= e["status"] < 300)
            state.add_trace(
                "Endpoint Checker",
                f"{good}/{len(called)} GET endpoints answered; {len(endpoints) - len(called)} others are covered by the tests",
                status="completed" if good == len(called) else "warning",
                details={"tool": "HTTP calls to the running app (no AI)"},
            )

        build = {
            "id": proto_id,
            "title": spec["title"],
            "path": str(sandbox.proto_path(proto_id)),
            "created_at": time.time(),
            "generation_source": source,
            "fallback_reason": fallback_reason,
            "repaired": repaired,
            "spec": spec,
            "files": [
                {"path": name, "lines": content.count("\n") + 1,
                 "written_by": ("ai" if source == "llm" else "fallback") if name in AI_FILES else "template",
                 "content": content}
                for name, content in sorted(all_files.items(), key=lambda kv: (kv[0] not in AI_FILES, kv[0]))
            ],
            "checks": {
                "safety_ok": not checks.get("safety"),
                "compile_ok": not checks.get("compile"),
                "tests": tests,
                "server": {k: v for k, v in server.items() if k != "log"},
                "endpoints": endpoints,
            },
        }
        sandbox.save_build(proto_id, build)
        return build

    @staticmethod
    def _template_files(spec: Dict[str, Any], source: str) -> Dict[str, str]:
        return {
            "main.py": MAIN_PY.format(title=spec["title"]),
            "static/base.css": BASE_CSS,
            "README.md": README.format(title=spec["title"], source=source),
        }

    @staticmethod
    def _check_endpoints(server: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Calls "/" and every GET route without path parameters, from the app's OpenAPI list."""
        url = server["url"]
        results = []
        page = sandbox.http_get(url + "/")
        results.append({"method": "GET", "path": "/", "status": page["status"], "ms": page["ms"], "note": "page"})
        spec = sandbox.http_get(url + "/openapi.json")
        try:
            paths = json.loads(spec["body"] or b"{}").get("paths", {})
        except ValueError:
            paths = {}
        for path, methods in paths.items():
            if path in ("/", "/health"):
                continue
            for method in methods:
                entry = {"method": method.upper(), "path": path}
                if method == "get" and "{" not in path:
                    answer = sandbox.http_get(url + path)
                    entry.update(status=answer["status"], ms=answer["ms"])
                    results.append(entry)
                else:
                    entry.update(status=None, ms=None, note="covered by tests")
                    results.append(entry)
        return [r for r in results if r["status"] is not None] + [r for r in results if r["status"] is None]


prototype_builder = PrototypeBuilderAgent()
