"""SQLite session + evaluation log store (synopsis Sec 9).

Replaces pure in-memory sessions for Eval-1 persistence:
sessions table + eval_logs table (localisation runs, grounding rate,
latency). Works with stdlib sqlite3 only.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(os.getenv("SESSIONS_DB_PATH", str(Path(__file__).resolve().parent.parent / "sessions.db")))
_lock = threading.Lock()
# Databases whose schema is already set up (DB_PATH can change, e.g. in tests).
_ready_paths: set = set()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  created_at REAL,
  updated_at REAL,
  repo_path TEXT,
  history_json TEXT
);
CREATE TABLE IF NOT EXISTS eval_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL,
  metric TEXT,
  value REAL,
  detail_json TEXT
);
"""


def _connect() -> sqlite3.Connection:
    path = str(DB_PATH)
    conn = sqlite3.connect(path, timeout=10)
    if path not in _ready_paths:
        with _lock:
            conn.executescript(_SCHEMA)
            # Older databases predate the entities column.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "entities_json" not in cols:
                conn.execute("ALTER TABLE sessions ADD COLUMN entities_json TEXT")
            conn.commit()
            _ready_paths.add(path)
    return conn


def save_session(
    session_id: str,
    repo_path: Optional[str],
    history: List[Dict[str, Any]],
    entities: Optional[Dict[str, Any]] = None,
) -> None:
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions(session_id, created_at, updated_at, repo_path, history_json, entities_json)"
            " VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET"
            " updated_at=excluded.updated_at, repo_path=excluded.repo_path,"
            " history_json=excluded.history_json,"
            " entities_json=COALESCE(excluded.entities_json, sessions.entities_json)",
            (session_id, now, now, repo_path or "", json.dumps(history, default=str),
             json.dumps(entities, default=str) if entities is not None else None),
        )
        conn.commit()
    finally:
        conn.close()


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT session_id, repo_path, history_json, entities_json FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "session_id": row[0],
            "repo_path": row[1],
            "history": json.loads(row[2] or "[]"),
            "entities": json.loads(row[3] or "{}"),
        }
    finally:
        conn.close()


def log_metric(metric: str, value: float, detail: Optional[Dict[str, Any]] = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO eval_logs(created_at, metric, value, detail_json) VALUES(?,?,?,?)",
            (time.time(), metric, float(value), json.dumps(detail or {})),
        )
        conn.commit()
    finally:
        conn.close()
