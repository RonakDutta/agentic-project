"""
Tests for the Groq free-tier budget logic in core.llm.

Covers the pieces that keep one run inside the free plan:
- rate-limit header parsing (x-ratelimit-* and retry-after)
- budget-aware model ranking and prompt-size routing
- adaptive max_tokens so a single answer cannot empty a token window
- plain-language prompt rules and prose cleanup
"""

from types import SimpleNamespace

from core.config import settings
from core.llm import LLMClient, clean_prose, clean_value, _parse_duration


def make_client() -> LLMClient:
    client = LLMClient()
    client.client = object()  # marks the client as configured without touching the network
    return client


def fake_headers(remaining_requests=100, remaining_tokens=8000, reset_requests="10m", reset_tokens="60s"):
    return {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": str(remaining_requests),
        "x-ratelimit-reset-requests": reset_requests,
        "x-ratelimit-limit-tokens": str(remaining_tokens) if remaining_tokens is not None else "8000",
        "x-ratelimit-remaining-tokens": str(remaining_tokens) if remaining_tokens is not None else None,
        "x-ratelimit-reset-tokens": reset_tokens,
    }


# --------------------------------------------------------------------- #
# Header parsing
# --------------------------------------------------------------------- #

def test_parse_duration_formats():
    assert _parse_duration("5m45.6s") == 345.6
    assert _parse_duration("622ms") == 0.622
    assert _parse_duration("1h") == 3600.0
    assert _parse_duration("30") == 30.0
    assert _parse_duration(None) is None
    assert _parse_duration("not-a-duration") is None


def test_record_budget_stores_headers_and_proactive_cooldown():
    client = make_client()
    client._record_budget("model-a", fake_headers(remaining_requests=100, remaining_tokens=6000))
    budget = client._model_budget["model-a"]
    assert budget["remaining_requests"] == 100
    assert budget["remaining_tokens"] == 6000
    assert budget["reset_requests_at"] > 0
    assert client._has_budget("model-a", 2000) is True

    # An empty request window closes the model until it resets.
    client._record_budget("model-b", fake_headers(remaining_requests=0, remaining_tokens=6000))
    assert client._has_budget("model-b", 10) is False
    assert "model-b" in client.get_rate_limit_status()["cooldowns"]


def test_budget_window_refills_after_reset():
    client = make_client()
    client._record_budget("model-a", fake_headers(remaining_requests=0, remaining_tokens=0, reset_requests="1s", reset_tokens="1s"))
    assert client._has_budget("model-a", 10) is False

    # Simulate the window having reset a moment later.
    budget = client._model_budget["model-a"]
    budget["reset_requests_at"] = 0.0
    budget["reset_tokens_at"] = 0.0
    assert client._has_budget("model-a", 10) is True
    assert client._headroom("model-a") == 1.0


# --------------------------------------------------------------------- #
# Ranking, routing and adaptive answer size
# --------------------------------------------------------------------- #

def test_short_prompts_go_to_the_model_with_most_headroom():
    client = make_client()
    primary, fast = settings.model_chain[0], settings.model_chain[1]
    client._record_budget(primary, fake_headers(remaining_tokens=800, reset_tokens="5m"))
    client._record_budget(fast, fake_headers(remaining_tokens=7600, reset_tokens="5m"))
    ranked = client._rank_models(prompt_tokens=100, needed_tokens=500)
    assert ranked[0] == fast


def test_long_prompts_keep_the_configured_order():
    client = make_client()
    primary, fast = settings.model_chain[0], settings.model_chain[1]
    client._record_budget(primary, fake_headers(remaining_tokens=3000, reset_tokens="5m"))
    client._record_budget(fast, fake_headers(remaining_tokens=7600, reset_tokens="5m"))
    ranked = client._rank_models(prompt_tokens=settings.small_prompt_tokens + 1, needed_tokens=500)
    assert ranked[0] == primary


def test_clamp_shrinks_answer_to_fit_the_token_window():
    client = make_client()
    requested = settings.max_tokens_per_req

    client._record_budget("primary", fake_headers(remaining_tokens=4000, reset_tokens="5m"))
    clamped = client._clamp_max_tokens("primary", requested)
    assert clamped is not None
    assert clamped <= requested
    assert clamped >= settings.min_tokens_floor

    # Almost no window left: nothing useful fits, so the caller must move on.
    client._record_budget("primary", fake_headers(remaining_tokens=settings.budget_safety_margin + 10, reset_tokens="5m"))
    assert client._clamp_max_tokens("primary", requested) is None

    # Unknown budget (first call, no headers yet) keeps the requested size.
    assert client._clamp_max_tokens("never-seen", requested) == requested


def test_reserve_refuses_when_every_model_is_starved():
    client = make_client()
    for name in client._get_candidate_models():
        client._record_budget(name, fake_headers(remaining_tokens=settings.budget_safety_margin, reset_tokens="30s"))
    assert client._reserve(None, prompt_tokens=400, base_max_tokens=settings.max_tokens_per_req, attempted=set()) is None


def test_reserve_returns_a_model_and_size_when_budget_is_healthy():
    client = make_client()
    reservation = client._reserve(None, prompt_tokens=400, base_max_tokens=settings.max_tokens_per_req, attempted=set())
    assert reservation is not None
    model, max_tokens = reservation
    assert model in client._get_candidate_models()
    assert settings.min_tokens_floor <= max_tokens <= settings.max_tokens_cap


def test_seconds_until_replenish_reports_the_soonest_reset():
    client = make_client()
    for name in client._get_candidate_models():
        client._record_budget(name, fake_headers(remaining_tokens=0, reset_tokens="20s"))
    wait = client._seconds_until_replenish(None, needed_tokens=1000)
    assert wait is not None
    assert 0.5 <= wait <= 20.0


def test_cooldown_prefers_retry_after_header():
    client = make_client()
    assert client._cooldown_from_error("no hint", headers={"retry-after": "7"}) == 7.75
    assert round(client._cooldown_from_error("Please try again in 7.31s"), 2) == 8.06
    assert client._cooldown_from_error("no hint at all") == 60.0


# --------------------------------------------------------------------- #
# Plain-language output
# --------------------------------------------------------------------- #

def test_style_rules_are_added_once_to_the_system_prompt():
    client = make_client()
    messages = [{"role": "system", "content": "You are a reviewer."}, {"role": "user", "content": "hi"}]
    styled = client._with_style_rules(messages)
    assert len(styled) == 2
    assert "plain-english-rules" in styled[0]["content"]
    assert "You are a reviewer." in styled[0]["content"]
    assert client._with_style_rules(styled) == styled


def test_style_rules_are_inserted_when_there_is_no_system_prompt():
    client = make_client()
    styled = client._with_style_rules([{"role": "user", "content": "hi"}])
    assert styled[0]["role"] == "system"
    assert "plain-english-rules" in styled[0]["content"]


def test_clean_prose_removes_ai_tells():
    assert clean_prose("Fast \u2014 cheap \u2013 and small") == "Fast, cheap, and small"
    assert clean_prose("Sure! Here is the plan: start today.") == "Here is the plan: start today."
    assert clean_prose("The build passes. Let me know if you need anything else.") == "The build passes."


def test_clean_prose_leaves_code_and_diagrams_alone():
    code = "def add(a, b):\n    return a + b"
    assert clean_prose(code) == code
    diagram = "graph LR\n    A[Sensor] --> B[Dashboard]"
    assert clean_prose(diagram) == diagram


def test_clean_value_walks_nested_structures():
    payload = {"title": "Sensor \u2014 installed", "steps": ["Run it. Hope this helps."], "count": 3}
    cleaned = clean_value(payload)
    assert cleaned["title"] == "Sensor, installed"
    assert cleaned["steps"] == ["Run it."]
    assert cleaned["count"] == 3


# --------------------------------------------------------------------- #
# End-to-end generate() against a stubbed transport
# --------------------------------------------------------------------- #

class FakeRawResponse:
    def __init__(self, content, headers):
        self.headers = headers

    def parse(self):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Sure! Here is the answer \u2014 done."))],
            usage=SimpleNamespace(total_tokens=42),
        )


class FakeRawCreate:
    """Stands in for groq's chat.completions.with_raw_response endpoint."""

    def __init__(self, headers):
        self.headers = headers
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeRawResponse("", self.headers)


class FakeTransport:
    """Stands in for the Groq SDK: client.chat.completions.with_raw_response.create()."""

    def __init__(self, headers):
        self.raw = FakeRawCreate(headers)
        self.completions = SimpleNamespace(with_raw_response=self.raw)
        self.chat = SimpleNamespace(completions=self.completions)


def test_generate_records_budget_and_cleans_output():
    client = make_client()
    transport = FakeTransport(fake_headers(remaining_tokens=7000, reset_tokens="60s"))
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=transport.completions))

    out = client.generate([{"role": "user", "content": "Explain the sensor"}])

    assert "Sure!" not in out
    assert "\u2014" not in out
    assert client._model_budget[client._get_candidate_models()[0]]["remaining_tokens"] == 7000
    # The plain-language rules ride along on every call.
    sent = transport.raw.calls[0]["messages"]
    assert any("plain-english-rules" in str(m.get("content", "")) for m in sent)


# --------------------------------------------------------------------- #
# Truncated structured output (Groq json_validate_failed)
# --------------------------------------------------------------------- #

def _validation_error():
    import httpx
    from groq import APIError
    msg = (
        'Error code: 400 - {"error": {"message": "Failed to generate JSON.", '
        '"code": "json_validate_failed"}}'
    )
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return APIError(msg, request=req, body={"error": {"code": "json_validate_failed"}})


class TruncatingRawCreate(FakeRawCreate):
    """Fails the first structured call the way Groq does when JSON is cut off."""

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise _validation_error()
        return FakeRawResponse("", self.headers)


def test_json_truncation_retries_with_bigger_budget():
    client = make_client()
    raw = TruncatingRawCreate(fake_headers(remaining_tokens=7000, reset_tokens="60s"))
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=raw))
    )

    out = client.generate([{"role": "user", "content": "List competitors"}], json_mode=True)

    assert out
    assert len(raw.calls) == 2
    first, second = raw.calls[0]["max_tokens"], raw.calls[1]["max_tokens"]
    assert second == min(first + 1024, settings.max_tokens_cap)
    assert second > first
    # Truncation is a budget problem, not a quota problem: no cooldown.
    assert client._get_candidate_models()[0] not in client.get_rate_limit_status()["cooldowns"]


class TimeoutOnceRawCreate(FakeRawCreate):
    """First call hangs past the client timeout, then the next model answers."""

    def create(self, **kwargs):
        import httpx
        from groq import APITimeoutError
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
        return FakeRawResponse("", self.headers)


def test_slow_model_timeout_rotates_without_cooldown():
    client = make_client()
    raw = TimeoutOnceRawCreate(fake_headers(remaining_tokens=7000, reset_tokens="60s"))
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=raw))
    )

    out = client.generate([{"role": "user", "content": "Explain the sensor"}])

    assert out
    assert len(raw.calls) == 2
    # A timeout spends no quota but the slow model is skipped for a while,
    # so the retry must go to a different model immediately.
    assert raw.calls[1]["model"] != raw.calls[0]["model"]
    slow = raw.calls[0]["model"]
    assert slow in client.get_rate_limit_status()["cooldowns"]
