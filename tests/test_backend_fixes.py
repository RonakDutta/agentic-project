"""
Regression tests for the Phase 1 backend fixes (see CLAUDE.md, "Phase 1").

Each test pins one bug that used to exist so it cannot quietly come back.
None of them need a Groq key or network access.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import settings
from core.llm import LLMClient, reasoning_kwargs, strip_reasoning, AGENT_MAX_TOKENS

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = str(ROOT / "sample_repo")


# --------------------------------------------------------------------- #
# Fake Groq transport that returns a scripted reply per call
# --------------------------------------------------------------------- #

class ScriptedRaw:
    def __init__(self, replies, tokens=100):
        self.replies = list(replies)
        self.calls = []
        self.tokens = tokens

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.replies.pop(0) if self.replies else "{}"
        if isinstance(content, Exception):
            raise content
        tokens = self.tokens
        return SimpleNamespace(
            headers={},
            parse=lambda: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                usage=SimpleNamespace(total_tokens=tokens),
            ),
        )


def scripted_client(replies, tokens=100):
    client = LLMClient()
    raw = ScriptedRaw(replies, tokens)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=raw)))
    return client, raw


# --------------------------------------------------------------------- #
# LLM client
# --------------------------------------------------------------------- #

def test_reasoning_controls_per_model_family():
    assert reasoning_kwargs("openai/gpt-oss-120b", "low") == {"reasoning_effort": "low", "include_reasoning": False}
    assert reasoning_kwargs("qwen/qwen3.8-27b", "low") == {"reasoning_format": "hidden"}
    assert reasoning_kwargs("some-other-model", "low") == {}


def test_think_blocks_never_reach_json_parser():
    client, _ = scripted_client(['<think>let me plan</think>{"ok": true}'])
    assert client.generate_json([{"role": "user", "content": "x"}]) == {"ok": True}
    assert strip_reasoning("<think>unfinished") == ""


def test_generate_sends_reasoning_params_to_gpt_oss():
    client, raw = scripted_client(["hello"])
    client.generate([{"role": "user", "content": "hi"}], model="openai/gpt-oss-120b")
    assert raw.calls[0]["reasoning_effort"] == settings.reasoning_effort


def test_generate_json_does_not_double_spend_on_bad_json():
    # Old behaviour: a failure in JSON mode re-ran the whole generate() in text mode.
    client, raw = scripted_client(["not json at all"])
    with pytest.raises(ValueError):
        client.generate_json([{"role": "user", "content": "x"}])
    assert len(raw.calls) == 1


def test_retry_hint_parses_minutes_for_daily_limits():
    client = LLMClient()
    cooldown = client._cooldown_from_error("Rate limit reached on tokens per day (TPD). Please try again in 14m22.08s.")
    assert 860 < cooldown < 865


def test_unavailable_model_is_parked_and_next_model_answers():
    import httpx
    from groq import APIError
    err = APIError(
        "Error code: 404 - model_not_found: The model `bad/model` does not exist",
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        body=None,
    )
    client, raw = scripted_client([err, "answer"])
    assert client.generate([{"role": "user", "content": "hi"}]) == "answer"
    parked = raw.calls[0]["model"]
    assert client.get_rate_limit_status()["cooldowns"][parked] > 3000
    assert raw.calls[1]["model"] != parked


def test_local_ledger_enforces_free_tier_tpm_before_any_header():
    client, raw = scripted_client(["a", "b", "c"], tokens=settings.free_tier_tpm)
    model = settings.model_chain[0]
    client.generate([{"role": "user", "content": "one"}], model=model)
    # That model's minute window is now full, so the next call must go elsewhere.
    client.generate([{"role": "user", "content": "two"}], model=model)
    assert raw.calls[1]["model"] != model
    status = client.get_rate_limit_status()["free_tier"][model]
    assert status["minute"]["tokens"] >= settings.free_tier_tpm
    assert status["today"]["requests"] == 1


def test_force_offline_only_affects_current_thread():
    import threading
    client, _ = scripted_client(["main-thread", "worker"])
    results = {}
    with client.force_offline():
        with pytest.raises(RuntimeError):
            client.generate([{"role": "user", "content": "x"}])
        t = threading.Thread(target=lambda: results.update(out=client.generate([{"role": "user", "content": "y"}])))
        t.start(); t.join()
    assert results["out"] == "main-thread"


def test_one_idea_run_fits_pooled_free_tier_minute():
    # Prompts are ~500-1,100 tokens; the answer budgets below must keep a full
    # 6-call idea run inside the pooled per-minute window of the model chain.
    idea_keys = ["idea", "market", "kill", "reconcile", "prd", "roadmap"]
    reserved = sum(AGENT_MAX_TOKENS[k] for k in idea_keys) + 6 * 1100
    assert reserved <= settings.free_tier_tpm * len(settings.model_chain)
    assert max(AGENT_MAX_TOKENS.values()) + 2500 <= settings.free_tier_tpm


# --------------------------------------------------------------------- #
# Web search
# --------------------------------------------------------------------- #

def test_offline_fallback_uses_whole_words_and_is_labelled():
    from tools.search_tool import WebSearchTool
    tool = WebSearchTool()
    # "email" and "retail" contain "ai" but must not pull in the AI/code references.
    assert tool._offline_references("retail email marketing tool") == []
    refs = tool._offline_references("ESP32 energy sensor")
    assert refs and all(not r.is_live for r in refs)


def test_market_only_counts_live_citations(monkeypatch):
    from agents.idea_agent import DecomposedIdea
    from agents.market_agent import MarketTechStackAgent
    from tools.search_tool import SearchResultItem

    agent = MarketTechStackAgent()
    monkeypatch.setattr(agent.search_tool, "search_many", lambda queries, max_results=5: [
        SearchResultItem("ThingsBoard", "IoT platform", "https://thingsboard.io", source="offline_reference"),
    ])
    idea = DecomposedIdea("energy sensor idea", "Energy Sensor", "Problem " * 10, [], "Value prop here", [], ["a", "b"], [])
    with agent.llm.force_offline():
        market = agent.analyze(idea)
    assert market.live_citation_count == 0
    assert market.generation_source == "fallback"
    assert all(c["evidence"] != "search" for c in market.competitors)


# --------------------------------------------------------------------- #
# Idea pipeline
# --------------------------------------------------------------------- #

def test_kill_and_reconciler_normalize_model_labels():
    from agents.kill_agent import normalize_severity, normalize_verdict, normalize_category
    assert normalize_severity("critical") == "Critical"
    assert normalize_severity("HIGH") == "High"
    assert normalize_severity("low") == "Medium"
    assert normalize_verdict("high rejection risk - do not build") == "High Rejection Risk"
    assert normalize_verdict("Pivot needed") == "Strategic Pivot Recommended"
    assert normalize_category("go-to-market and CAC") == "Market & Distribution"


def test_idea_pipeline_marks_fallbacks_and_never_fails():
    from agents.orchestrator import orchestrator
    from core.llm import llm_client
    with llm_client.force_offline():
        state = orchestrator.process("A smart water meter with LoRaWAN leak alerts", force_intent="idea_validation")
    out = state.final_output
    assert out["used_fallback"] is True
    assert out["provenance"]["scorecard"] == "deterministic"
    assert out["evidence_confidence"] == "Low"
    # Section 12 is computed from this idea, not a fixed paragraph.
    assert "lorawan" in out["sections_13"][11]["content"].lower()
    assert len(out["phases"]) == 3


def test_scorecard_reacts_to_hardware_and_paid_services():
    from agents.feasibility_scorecard import scorecard_engine
    from agents.idea_agent import DecomposedIdea
    from agents.market_agent import MarketAnalysis

    def score(idea_text, stack):
        idea = DecomposedIdea(idea_text, "T", "p" * 60, [{}, {}], "value proposition here", ["a", "b"], ["f1", "f2", "f3"], [])
        market = MarketAnalysis([], stack, ["d1", "d2"], [], [])
        card = scorecard_engine.evaluate(idea, market)
        return next(c.score for c in card.categories if c.category_name == "Resource Requirements")

    software = score("a web app", {"backend": {"choice": "FastAPI"}, "frontend": {"choice": "React"}, "database": {"choice": "SQLite"}})
    hardware = score("ESP32 sensors with LoRaWAN", {"backend": {"choice": "AWS Lambda"}, "frontend": {"choice": "React"}, "database": {"choice": "PostgreSQL"}})
    assert software > hardware


def test_scorecard_caps_go_when_reconciler_rejects():
    from agents.feasibility_scorecard import scorecard_engine
    from agents.idea_agent import DecomposedIdea
    from agents.market_agent import MarketAnalysis
    from agents.kill_agent import ReconciliationResult

    idea = DecomposedIdea("web app", "T", "p" * 80, [{}, {}], "a very clear value proposition", ["a", "b"], ["f1", "f2", "f3"], [])
    market = MarketAnalysis(
        [{"name": "X", "evidence": "search"}, {"name": "Y", "evidence": "search"}],
        {"backend": {"choice": "FastAPI"}, "frontend": {"choice": "React"}, "database": {"choice": "SQLite"}},
        ["d1", "d2"],
        [{"url": "https://a.com", "is_live": True}, {"url": "https://b.com", "is_live": True}],
        [],
    )
    rec = ReconciliationResult("T", "High Rejection Risk", ["for"], [], [], ["m1", "m2"], "r")
    card = scorecard_engine.evaluate(idea, market, None, rec)
    assert card.verdict != "GO"


def test_prd_diagrams_follow_the_idea_and_escape_labels():
    from agents.prd_agent import prd_agent, mermaid_label
    from agents.idea_agent import DecomposedIdea
    from agents.market_agent import MarketAnalysis
    from core.llm import llm_client
    idea = DecomposedIdea("x", "Leak Finder", "p", [{"persona": 'Facility "Ops" Manager'}], "v", [],
                          ["Feature 1: Leak [anomaly] detection", "Feature 2: Usage dashboard"], [])
    market = MarketAnalysis([], {"frontend": {"choice": "React"}}, [], [], [])
    with llm_client.force_offline():
        prd = prd_agent.generate(idea, market)
    assert "Leak anomaly detection" in prd.component_diagram_mermaid
    assert '"Ops"' not in prd.architecture_diagram_mermaid
    assert mermaid_label('a "b" [c] | d') == "a b c d"


# --------------------------------------------------------------------- #
# Code pipeline
# --------------------------------------------------------------------- #

def test_bm25_splits_camel_case():
    from indexer.bm25_search import tokenize_code
    tokens = tokenize_code("jwtAuthService HTTPServer")
    assert {"jwt", "auth", "service", "http", "server"} <= set(tokens)


def test_symbol_matching_needs_whole_identifiers():
    from indexer import index_cache
    from agents.code_nav_agent import CodeNavigationAgent
    index = index_cache.get_index(SAMPLE)
    nav = CodeNavigationAgent(index, index_cache.get_retriever(index))
    # "verify_tokenizer" contains "verify_token" but is a different identifier.
    assert "verify_token" not in nav.navigate("why does verify_tokenizer crash", top_k=2).identified_symbols
    assert "verify_token" in nav.navigate("why does verify_token crash", top_k=2).identified_symbols


def test_ast_chunks_are_complete_python():
    import ast, textwrap
    from indexer.ast_parser import ASTCodeIndexer
    index = ASTCodeIndexer(str(ROOT)).index()
    for chunk in index.chunks:
        code = textwrap.dedent(chunk.code)
        try:
            ast.parse(code)
        except SyntaxError:
            ast.parse("class _W:\n" + textwrap.indent(code, "    "))


def test_index_cache_reuses_unchanged_repo(tmp_path):
    from indexer import index_cache
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    first = index_cache.get_index(str(tmp_path))
    assert index_cache.get_index(str(tmp_path)) is first
    (tmp_path / "b.py").write_text("def g():\n    return 2\n")
    assert index_cache.get_index(str(tmp_path)) is not first


def _nav_for(query):
    from indexer import index_cache
    from agents.code_nav_agent import CodeNavigationAgent
    index = index_cache.get_index(SAMPLE)
    return index, CodeNavigationAgent(index, index_cache.get_retriever(index)).navigate(query, top_k=3)


def test_diagnosis_tolerates_messy_line_numbers_and_numbers_prompt_lines():
    from agents.diagnosis_agent import DiagnosisAgent
    _, nav = _nav_for("token expired in verify_token")
    reply = json.dumps({"summary": "s", "candidates": [{
        "rank": "1", "file_path": "auth/jwt_handler.py", "symbol_name": "verify_token",
        "line_start": "L24-30", "line_end": None, "wrong_code": "x", "recommended_pattern": "y = 1",
    }]})
    agent = DiagnosisAgent()
    agent.llm, raw = scripted_client([reply])
    result = agent.diagnose(nav)
    assert result.ranked_candidates[0].line_start == 24
    prompt = raw.calls[0]["messages"][-1]["content"]
    assert " | " in prompt and "line number" in prompt


def test_critic_replaces_invented_code_and_checks_fix_syntax():
    from agents.critic_agent import DeterministicCriticAgent
    from agents.diagnosis_agent import DiagnosisResult, FaultCandidate
    index, nav = _nav_for("token expired in verify_token")
    cand = FaultCandidate(
        rank=1, file_path="auth/jwt_handler.py", symbol_name="verify_token", line_start=24, line_end=50,
        confidence="high", root_cause_hypothesis="h", suggested_fix="f",
        wrong_code="if token.is_expired():\n    explode()",  # not in the file
        recommended_pattern="def broken(:\n    pass",        # not valid Python
    )
    report = DeterministicCriticAgent(index).verify(DiagnosisResult("q", "s", [cand]), retrieved_chunks=nav.candidate_chunks)
    assert "explode" not in cand.wrong_code and "def verify_token" in cand.wrong_code
    assert cand.verification["quote_matches_disk"] is False
    assert cand.verification["fix_compiles"] is False
    assert report.fixes_checked == 1 and report.fixes_compiling == 0


def test_critic_flags_citations_outside_retrieved_evidence():
    from agents.critic_agent import DeterministicCriticAgent
    from agents.diagnosis_agent import DiagnosisResult, FaultCandidate
    index, nav = _nav_for("token expired in verify_token")
    retrieved = [c for c in nav.candidate_chunks if c.name != "run_demo"]
    cand = FaultCandidate(1, "main.py", "run_demo", 9, 20, "high", "h", "f", wrong_code="", recommended_pattern="")
    report = DeterministicCriticAgent(index).verify(DiagnosisResult("q", "s", [cand]), retrieved_chunks=retrieved)
    assert report.verified_candidates == []
    assert any("retrieved evidence" in f for f in report.flags)


def test_revision_pass_sends_critic_feedback():
    from agents.orchestrator import orchestrator
    bad = json.dumps({"summary": "s", "candidates": [{
        "rank": 1, "file_path": "nope/missing.py", "symbol_name": "ghost", "line_start": 1, "line_end": 2,
        "wrong_code": "", "recommended_pattern": "x = 1",
    }]})
    good = json.dumps({"summary": "s2", "candidates": [{
        "rank": 1, "file_path": "auth/jwt_handler.py", "symbol_name": "verify_token", "line_start": 24, "line_end": 50,
        "wrong_code": "", "recommended_pattern": "x = 1",
    }]})
    client, raw = scripted_client([bad, good])
    original = orchestrator.diag_agent.llm
    orchestrator.diag_agent.llm = client
    try:
        state = orchestrator.process("token expired in verify_token", repo_path=SAMPLE, force_intent="codebase_analysis")
    finally:
        orchestrator.diag_agent.llm = original
    assert state.revision_count == 1
    assert "FAILED VERIFICATION" in raw.calls[1]["messages"][-1]["content"]
    assert state.final_output["critic"]["grounding_score"] == 1.0


def test_fallback_diagnosis_does_not_invent_fixes():
    from agents.orchestrator import orchestrator
    from core.llm import llm_client
    with llm_client.force_offline():
        state = orchestrator.process("token expired in verify_token", repo_path=SAMPLE, force_intent="codebase_analysis")
    top = state.final_output["candidates"][0]
    assert top["generated_by"] == "fallback"
    assert top["recommended_pattern"].startswith("# No fix was generated")


# --------------------------------------------------------------------- #
# Server and sessions
# --------------------------------------------------------------------- #

def test_endpoints_do_not_block_the_event_loop():
    import inspect
    import app as app_module
    for name in ("execute_query", "execute_followup", "inspect_repository", "run_graph", "health_check"):
        assert not inspect.iscoroutinefunction(getattr(app_module, name)), name


def test_allowed_repo_roots_blocks_other_folders(tmp_path):
    import app as app_module
    # Settings is a frozen dataclass; set the field directly for this test.
    object.__setattr__(app_module.settings, "allowed_repo_roots", str(tmp_path))
    try:
        assert app_module._local_path_allowed(str(tmp_path / "sub")) is True
        assert app_module._local_path_allowed(str(ROOT / "agents")) is False
        assert app_module._local_path_allowed(SAMPLE) is True  # the demo repo is always allowed
    finally:
        object.__setattr__(app_module.settings, "allowed_repo_roots", "")


def test_sessions_survive_a_restart():
    from agents.conversation_session import SessionManager
    first = SessionManager()
    session = first.get_or_create_session("persist1", SAMPLE)
    session.add_turn(user_query="who calls verify_token", agent_name="AST", answer="process_order",
                     referenced_symbols=["verify_token"])
    restarted = SessionManager()  # new process, empty memory
    restored = restarted.get_session("persist1")
    assert restored is not None
    assert restored.history[0].answer == "process_order"
    assert restored.active_entities["last_symbol"] == "verify_token"


def test_followup_resolves_github_url_to_local_clone(monkeypatch):
    from agents.conversation_session import SessionManager
    from indexer.github_ingest import github_ingest_service, IngestionResult
    monkeypatch.setattr(github_ingest_service, "ingest", lambda url, branch=None: IngestionResult(
        status="ok", repo_name="o/r", repo_url=url, local_path=SAMPLE, total_files=3, total_symbols=11))
    assert SessionManager.resolve_repo_path("https://github.com/o/r") == SAMPLE


def test_full_minute_windows_wait_briefly_instead_of_failing():
    import time as _time
    client, raw = scripted_client(["ok"])
    # Every model's minute window is full, but the bookings expire in ~2s.
    for model in settings.model_chain:
        entry = client._ledger.reserve(model, settings.free_tier_tpm)
        entry[0] = _time.time() - 58.0
    started = _time.time()
    assert client.generate([{"role": "user", "content": "hi"}]) == "ok"
    assert 1.0 < _time.time() - started < settings.max_wait_seconds + 1


def test_clamp_respects_local_minute_window():
    client = LLMClient()
    model = settings.model_chain[0]
    client._ledger.reserve(model, settings.free_tier_tpm - 1500)
    clamped = client._clamp_max_tokens(model, 1800, prompt_tokens=500)
    assert clamped is not None and clamped <= 1000
