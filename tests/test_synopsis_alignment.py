"""Eval-1 synopsis-alignment tests (branch `muse`).

Every test runs offline with optional dependencies missing.
"""

from agents.synopsis_agents import get_canonical_catalog
from agents.graph import graph_spec
from indexer.knowledge_base import KnowledgeBase
from indexer.chroma_store import ChromaCodeStore
from tools.git_tools import recent_commits
from tools.lint_metrics import ruff_check, radon_complexity
from agents import session_store


def test_canonical_agents_match_synopsis_table2():
    names = {a["name"] for a in get_canonical_catalog()}
    assert {"Orchestrator Agent", "Retrieval Agent", "Idea and Research Agent",
            "Roadmap and Risk Agent", "Code Navigation Agent",
            "Diagnosis Agent", "Critic Agent"} <= names


def test_graph_spec_lists_six_plus_orchestrator():
    spec = graph_spec()
    assert "orchestrator" in spec["nodes"] and "critic" in spec["nodes"]
    assert ("diagnosis", "critic") in spec["edges"]


def test_knowledge_base_offline_lookup():
    kb = KnowledgeBase()
    hits = kb.lookup("ValueError token validator")
    assert hits and "ValueError" in hits[0].text


def test_chroma_fallback_never_raises():
    store = ChromaCodeStore()
    assert store.upsert(["a"], ["def f(): pass"])["count"] == 1
    assert "hits" in store.query("f")


def test_git_tools_never_raise(tmp_path):
    res = recent_commits(str(tmp_path), limit=3)
    assert res["status"] in ("ok", "unavailable")
    assert ruff_check(__file__)["status"] in ("ok", "issues", "unavailable", "error")
    assert radon_complexity("def f(x):\n return x\n")["backend"] in ("radon", "builtin")


def test_sqlite_session_roundtrip(tmp_path, monkeypatch):
    import agents.session_store as ss
    monkeypatch.setattr(ss, "DB_PATH", tmp_path / "t.db")
    ss.save_session("s1", None, [{"q": "hi"}])
    loaded = ss.load_session("s1")
    assert loaded and loaded["history"] == [{"q": "hi"}]
    ss.log_metric("grounding_rate", 0.8, {"n": 10})
