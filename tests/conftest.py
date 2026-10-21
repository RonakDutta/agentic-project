"""Shared pytest setup: keep tests hermetic (no persistent LLM cache on disk)."""

import os
import sys
import tempfile
from pathlib import Path

# Must run before core.config is imported anywhere: Settings reads env at import.
os.environ.setdefault("LLM_DISK_CACHE", "0")
# Test sessions go to a throwaway database, never the real sessions.db.
os.environ.setdefault("SESSIONS_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="copilot_tests_"), "sessions.db"))

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
os.environ.setdefault("RUNS_PER_MINUTE", "0")
os.environ.setdefault("LLM_USAGE_LEDGER", "0")
# The idea pipeline would otherwise search arXiv / Semantic Scholar / OpenAlex.
os.environ.setdefault("PRIOR_ART_ENABLED", "0")
os.environ.setdefault("PAPER_CACHE", "0")
