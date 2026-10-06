"""
LLM Client Wrapper for Groq API.
Handles chat completions, structured JSON parsing, plain-language output cleanup,
rate-limit-aware fallback across a model chain, TTL response caching, and
latency/token tracking for live agent trace visualization.

Rate-Limit Strategy (Groq free tier: roughly 30 requests/minute, 1000 requests/day
and 8000 tokens/minute for every model in the chain):
- Reads the x-ratelimit-* response headers after every call, so the client knows how
  much of each model's budget is left before it spends it, not after the 429.
- Spreads short prompts across every model in the chain and keeps long prompts on
  the strongest model that still has budget, so the three budgets are pooled.
- Shrinks max_tokens when a model is close to its token ceiling, so one long answer
  cannot empty the window the next agent needs.
- Waits out a short refill window instead of failing the moment every model is busy,
  and parses 'retry-after' hints into exact per-model cooldowns.
- Caches identical completions for a short TTL so repeated follow-ups cost zero quota.
- Asks for plain English up front and strips AI-style filler from the answer text.
"""

import hashlib
import json
import logging
import random
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from groq import Groq, RateLimitError, APIError, APITimeoutError
from core.config import settings

logger = logging.getLogger(__name__)

# Matches Groq 429 messages like: "Rate limit reached for model ... on tokens per min (TPM):
# Limit 6000, Used 5932, Requested 812. Please try again in 7.31s"
_RETRY_HINT_RE = re.compile(r"try again in\s+([0-9.]+)\s*s", re.IGNORECASE)

# Rate-limit headers come back like "5m45.6s" or "622ms".
_RESET_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")

# AI filler that sometimes opens or closes a completion.
_LEADING_META_RE = re.compile(
    r"^\s*(?:sure|certainly|of course|absolutely|great question)\s*[!,.:\-]*\s*"
    r"(?=(?:here(?:'s| is)|let'?s|below|i(?:'ll| will)|the )\b)",
    re.IGNORECASE,
)
_TRAILING_META_RE = re.compile(
    r"(?:\s*(?:let me know if you (?:need|have|want|would like)[^.!?]*[.!?]"
    r"|hope (?:this|that) helps[^.!?]*[.!?]"
    r"|feel free to (?:ask|reach|contact)[^.!?]*[.!?]"
    r"|if you (?:have any|need) (?:questions|doubts|help)[^.!?]*[.!?])\s*)+$",
    re.IGNORECASE,
)
_CODE_HINT_RE = re.compile(r"```|^\s*(?:def |class |import |from |<\?|graph |flowchart |sequenceDiagram)", re.MULTILINE)

# Injected into every system prompt (see _with_style_rules) so all agents write the
# same way: short sentences, plain words, no dashes, no AI narration.
PLAIN_LANGUAGE_RULES = (
    "(plain-english-rules)\n"
    "How to write every value you return:\n"
    "1. Plain, everyday English that a teacher can follow. Short sentences.\n"
    "2. Never use em dashes or en dashes. Use a comma, a colon or a full stop instead.\n"
    "3. No hype and no buzzwords such as seamless, cutting-edge, revolutionary or game-changing.\n"
    "4. Do not mention being an AI, a model, or that you were given these rules.\n"
    "5. No filler endings such as 'Let me know if you need anything else'.\n"
    "6. Give the fact and the next step; skip generic disclaimers."
)


def _parse_duration(value: Optional[str]) -> Optional[float]:
    """Turns a rate-limit duration such as '5m45.6s', '622ms' or '30' into seconds."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    total = 0.0
    found = False
    for number, unit in _RESET_RE.findall(text):
        found = True
        amount = float(number)
        total += {"ms": amount / 1000.0, "s": amount, "m": amount * 60.0, "h": amount * 3600.0}[unit]
    if found:
        return total
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token). Used only for budget maths."""
    return max(1, len(text) // 4)


def _estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for message in messages:
        total += _estimate_tokens(str(message.get("content") or "")) + 4
    return total


def clean_prose(text: str) -> str:
    """
    Removes the tells that make machine text read like machine text:
    em dashes, conversational openers and filler sign-offs. Leaves the wording alone.
    """
    if not text or not isinstance(text, str):
        return text
    cleaned = text.strip()
    if not cleaned:
        return text

    # Em dash as punctuation -> comma; en dash (spaced) -> comma; leftovers -> hyphen.
    cleaned = re.sub(r"\s*\u2014\s*", ", ", cleaned)
    cleaned = re.sub(r"\s+\u2013\s+", ", ", cleaned)
    cleaned = cleaned.replace("\u2013", "-")

    # Only touch narration when the text is prose, never when it holds code or a diagram.
    if not _CODE_HINT_RE.search(cleaned):
        cleaned = _LEADING_META_RE.sub("", cleaned)
        cleaned = _TRAILING_META_RE.sub("", cleaned)

    return cleaned.strip()


def clean_value(value: Any) -> Any:
    """Applies clean_prose to every string inside a parsed structure."""
    if isinstance(value, str):
        return clean_prose(value)
    if isinstance(value, dict):
        return {key: clean_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    return value


class LLMClient:
    def __init__(self):
        # Never hard-crash at import: the dashboard, AST tooling, and deterministic
        # routers all work without a key. LLM-backed calls fail with a clear message
        # (and recover automatically if the key is added later).
        self.client: Optional[Groq] = None
        self._init_client()
        self.total_calls = 0
        self.total_tokens_used = 0
        self.total_latency_ms = 0
        self.cache_hits = 0
        self._model_cooldowns: Dict[str, float] = {}
        self._logged_rate_limits: Dict[str, float] = {}
        # Per-model budget as reported by the x-ratelimit-* response headers:
        # {model: {"limit_requests", "remaining_requests", "reset_requests_at",
        #          "limit_tokens", "remaining_tokens", "reset_tokens_at", "updated_at"}}
        self._model_budget: Dict[str, Dict[str, Optional[float]]] = {}
        # TTL cache: key -> (expiry_ts, content). Small LRU bound keeps memory flat.
        self._cache: "OrderedDict[str, Tuple[float, str]]" = OrderedDict()
        self._cache_max_entries = 128

    def _init_client(self) -> None:
        """Initializes (or refreshes) the Groq SDK client when an API key is present."""
        import os
        api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY", "")
        if not api_key:
            if self.client is None:
                logger.warning(
                    "[LLMClient] GROQ_API_KEY is not set. Dashboard, AST tools, and deterministic "
                    "follow-up routers remain fully available; LLM-backed agents will use grounded fallbacks."
                )
            return
        if self.client is None:
            self.client = Groq(api_key=api_key)
            logger.info("[LLMClient] Groq client initialized.")

    @property
    def is_configured(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------ #
    # Model chain & health
    # ------------------------------------------------------------------ #

    def _get_candidate_models(self, preferred_model: Optional[str] = None) -> List[str]:
        """
        Builds an ordered list of candidate models without duplicates.
        Order: preferred_model -> configured chain (primary -> fast -> extras -> code).
        """
        candidates: List[str] = []
        if preferred_model:
            candidates.append(preferred_model)
        for m in settings.model_chain:
            if m and m not in candidates:
                candidates.append(m)
        return candidates

    def _budget_remaining(self, model: str, key: str, reset_key: str) -> Optional[float]:
        """
        Remaining units of a rate-limit window, or None when there is no data or the
        window has already refilled (in which case the model counts as full again).
        """
        budget = self._model_budget.get(model)
        if not budget:
            return None
        value = budget.get(key)
        if value is None:
            return None
        reset_at = budget.get(reset_key)
        if reset_at is None:
            reset_at = 0.0
        if time.time() >= reset_at:
            return None
        return float(value)

    def _has_budget(self, model: str, needed_tokens: int) -> bool:
        """True when the model's headers say it can still take this call."""
        remaining_requests = self._budget_remaining(model, "remaining_requests", "reset_requests_at")
        if remaining_requests is not None and remaining_requests <= 0:
            return False
        remaining_tokens = self._budget_remaining(model, "remaining_tokens", "reset_tokens_at")
        if remaining_tokens is not None and remaining_tokens < needed_tokens + settings.budget_safety_margin:
            return False
        return True

    def _headroom(self, model: str) -> float:
        """Share (0..1) of the model's token window that is still unused."""
        remaining = self._budget_remaining(model, "remaining_tokens", "reset_tokens_at")
        if remaining is None:
            return 1.0
        limit = (self._model_budget.get(model) or {}).get("limit_tokens") or 0
        if limit:
            return max(0.0, min(1.0, remaining / float(limit)))
        return 1.0 if remaining > 0 else 0.0

    def _rank_models(
        self,
        preferred_model: Optional[str] = None,
        prompt_tokens: int = 0,
        needed_tokens: int = 0,
        exclude: Optional[set] = None,
    ) -> List[str]:
        """
        Candidate models that are out of cooldown and still hold enough budget,
        best first.
        """
        excluded = exclude or set()
        now = time.time()
        ready: List[Tuple[int, str]] = []
        for index, candidate in enumerate(self._get_candidate_models(preferred_model)):
            if candidate in excluded:
                continue
            if now < self._model_cooldowns.get(candidate, 0):
                continue
            if not self._has_budget(candidate, needed_tokens):
                continue
            ready.append((index, candidate))

        if prompt_tokens > settings.small_prompt_tokens:
            # Long jobs keep the configured order: strongest model first.
            ready.sort(key=lambda item: item[0])
        else:
            # Short jobs go to whichever model has the most budget left, so the three
            # windows drain evenly instead of one model taking every call.
            ready.sort(key=lambda item: (-self._headroom(item[1]), item[0]))
        return [candidate for _, candidate in ready]

    def _get_healthy_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
        """Finds the first candidate model that is out of cooldown and holds budget."""
        ranked = self._rank_models(preferred_model)
        return ranked[0] if ranked else None

    def _reserve(
        self,
        preferred_model: Optional[str],
        prompt_tokens: int,
        base_max_tokens: int,
        attempted: set,
    ) -> Optional[Tuple[str, int]]:
        """
        Picks a model and the answer size it can afford right now.
        Returns None when every model is cooling down or over budget, which means the
        caller should wait for a window to refill instead of firing a doomed request.
        """
        for needed in (prompt_tokens + base_max_tokens, prompt_tokens + settings.min_tokens_floor):
            for candidate in self._rank_models(preferred_model, prompt_tokens, needed, exclude=attempted):
                max_tokens = self._clamp_max_tokens(candidate, base_max_tokens)
                if max_tokens is not None:
                    return candidate, max_tokens
        return None

    def _clamp_max_tokens(self, model: str, requested: int) -> Optional[int]:
        """
        Shrinks the answer budget so this call stays inside the model's token window.
        Returns None when the model cannot fit even the smallest useful answer.
        """
        base = min(requested, settings.max_tokens_cap)
        remaining = self._budget_remaining(model, "remaining_tokens", "reset_tokens_at")
        if remaining is None:
            return base
        room = int(remaining) - settings.budget_safety_margin
        if room < 1:
            return None
        if base <= settings.min_tokens_floor:
            return min(base, room)
        if room < settings.min_tokens_floor:
            return None
        return max(settings.min_tokens_floor, min(base, room))

    def _seconds_until_replenish(
        self, preferred_model: Optional[str] = None, needed_tokens: int = 0
    ) -> Optional[float]:
        """Shortest wait (seconds) before any model can take this call again."""
        now = time.time()
        waits: List[float] = []
        for candidate in self._get_candidate_models(preferred_model):
            cooldown_until = self._model_cooldowns.get(candidate, 0)
            if cooldown_until > now:
                waits.append(cooldown_until - now)
                continue
            if self._has_budget(candidate, needed_tokens):
                continue
            budget = self._model_budget.get(candidate) or {}
            for key in ("reset_requests_at", "reset_tokens_at"):
                reset_at = budget.get(key) or 0.0
                if reset_at > now:
                    waits.append(reset_at - now)
        if not waits:
            return None
        return max(0.5, min(waits))

    def _record_budget(self, model: str, headers: Any) -> None:
        """Stores the x-ratelimit-* headers reported with a successful call."""
        if headers is None:
            return
        try:
            limit_requests = _to_int(headers.get("x-ratelimit-limit-requests"))
            remaining_requests = _to_int(headers.get("x-ratelimit-remaining-requests"))
            reset_requests = _parse_duration(headers.get("x-ratelimit-reset-requests"))
            limit_tokens = _to_int(headers.get("x-ratelimit-limit-tokens"))
            remaining_tokens = _to_int(headers.get("x-ratelimit-remaining-tokens"))
            reset_tokens = _parse_duration(headers.get("x-ratelimit-reset-tokens"))
        except Exception:  # pragma: no cover - headers are optional telemetry
            return
        if all(v is None for v in (remaining_requests, remaining_tokens)):
            return

        now = time.time()
        self._model_budget[model] = {
            "limit_requests": limit_requests,
            "remaining_requests": remaining_requests,
            "reset_requests_at": (
                now + reset_requests if remaining_requests is not None and reset_requests else 0.0
            ),
            "limit_tokens": limit_tokens,
            "remaining_tokens": remaining_tokens,
            "reset_tokens_at": now + reset_tokens if remaining_tokens is not None and reset_tokens else 0.0,
            "updated_at": now,
        }
        # Proactive: stop calling a model whose request window is already empty.
        if remaining_requests is not None and remaining_requests <= 0 and reset_requests:
            self._mark_rate_limited(model, cooldown_seconds=min(max(reset_requests, 1.0), 3600.0))

    def _with_style_rules(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Appends the plain-language rules to the system prompt of every call."""
        if not settings.plain_language:
            return messages
        for message in messages:
            if message.get("role") == "system" and PLAIN_LANGUAGE_RULES.splitlines()[0] in str(message.get("content") or ""):
                return messages
        styled = [dict(message) for message in messages]
        for message in styled:
            if message.get("role") == "system":
                message["content"] = f"{message.get('content') or ''}\n\n{PLAIN_LANGUAGE_RULES}"
                return styled
        styled.insert(0, {"role": "system", "content": PLAIN_LANGUAGE_RULES})
        return styled

    def _mark_rate_limited(self, model: str, cooldown_seconds: float, reason: str = "Rate limit") -> None:
        """Places a model on cooldown and logs the transition once to prevent log spam."""
        now = time.time()
        self._model_cooldowns[model] = now + cooldown_seconds
        last_logged = self._logged_rate_limits.get(model, 0)
        if now - last_logged >= cooldown_seconds:
            self._logged_rate_limits[model] = now
            logger.warning(
                f"[LLMClient] {reason} on {model}. Placed on cooldown for {int(cooldown_seconds)}s."
            )

    def _cooldown_from_error(
        self, err_msg: str, headers: Any = None, default: float = 60.0
    ) -> float:
        """Extracts a precise cooldown from a Groq 429 header or payload when possible."""
        if headers is not None:
            retry_after = _parse_duration(headers.get("retry-after"))
            if retry_after is not None:
                return min(max(retry_after + 0.75, 1.0), 3600.0)
        match = _RETRY_HINT_RE.search(err_msg)
        if match:
            # Add a small safety margin over Groq's suggested wait.
            return min(max(float(match.group(1)) + 0.75, 1.0), 300.0)
        return default

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Snapshot of per-model cooldowns and budgets for observability endpoints."""
        now = time.time()
        active = {
            model: round(until - now, 1)
            for model, until in self._model_cooldowns.items()
            if until > now
        }
        budgets = {}
        for model, budget in self._model_budget.items():
            remaining_requests = self._budget_remaining(model, "remaining_requests", "reset_requests_at")
            remaining_tokens = self._budget_remaining(model, "remaining_tokens", "reset_tokens_at")
            budgets[model] = {
                "requests_left": int(remaining_requests) if remaining_requests is not None else None,
                "tokens_left": int(remaining_tokens) if remaining_tokens is not None else None,
            }
        candidates = self._get_candidate_models()
        return {
            "cooldowns": active,
            "budgets": budgets,
            "all_rate_limited": bool(candidates) and all(
                now < self._model_cooldowns.get(m, 0) or not self._has_budget(m, settings.min_tokens_floor)
                for m in candidates
            ),
            "cache_entries": len(self._cache),
        }

    # ------------------------------------------------------------------ #
    # TTL response cache
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cache_key(messages: List[Dict[str, str]], model: Optional[str], temperature: Optional[float], json_mode: bool, max_tokens: Optional[int]) -> str:
        payload = json.dumps(
            {
                "messages": messages,
                "model": model or "auto",
                "temperature": temperature if temperature is not None else settings.temperature,
                "json": json_mode,
                "max_tokens": max_tokens,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[str]:
        if not settings.llm_cache_enabled:
            return None
        entry = self._cache.get(key)
        if not entry:
            return None
        expiry, content = entry
        if expiry < time.time():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return content

    def _cache_put(self, key: str, content: str) -> None:
        if not settings.llm_cache_enabled:
            return
        self._cache[key] = (time.time() + settings.llm_cache_ttl_seconds, content)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max_entries:
            self._cache.popitem(last=False)

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def generate(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Executes a completion call with caching, fallback and retry logic."""
        if self.client is None:
            # Re-check the environment in case the key was added after startup.
            self._init_client()
        if self.client is None:
            raise RuntimeError(
                "GROQ_API_KEY is not configured. Add it in Settings > Environment to enable LLM agents."
            )

        messages = self._with_style_rules(messages)

        cache_key = self._cache_key(messages, model, temperature, json_mode, max_tokens)
        cached = self._cache_get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        temp = temperature if temperature is not None else settings.temperature
        base_max_tokens = min(max_tokens or settings.max_tokens_per_req, settings.max_tokens_cap)
        prompt_tokens = _estimate_messages_tokens(messages)
        response_format = {"type": "json_object"} if json_mode else None

        attempts = 0
        wait_cycles = 0
        waited = 0.0
        backoff = settings.pace_seconds
        last_error = None
        attempted_models: set = set()
        candidates = self._get_candidate_models(model)
        max_attempts = max(settings.retry_attempts + 2 * len(candidates), 6)

        while attempts < max_attempts:
            reservation = self._reserve(model, prompt_tokens, base_max_tokens, attempted_models)
            if reservation is None:
                # Everything is cooling down or over budget. Wait for a window to
                # refill instead of spending a request we know will be rejected.
                wait_s = self._seconds_until_replenish(model, prompt_tokens + settings.min_tokens_floor)
                if wait_s is not None and wait_cycles < 6 and waited + wait_s <= settings.max_wait_seconds:
                    wait_cycles += 1
                    logger.info(
                        f"[LLMClient] Every model is out of budget. Waiting {wait_s:.1f}s for a window to refill."
                    )
                    time.sleep(wait_s)
                    waited += wait_s
                    attempted_models.clear()
                    continue
                now = time.time()
                last_all = self._logged_rate_limits.get("__all__", 0)
                if now - last_all >= 30.0:
                    self._logged_rate_limits["__all__"] = now
                    logger.warning(
                        "[LLMClient] All Groq models are out of rate-limit budget. Activating deterministic fallback."
                    )
                raise RuntimeError(
                    "All configured Groq models are rate-limited. Activating deterministic fallback."
                )

            current_model, max_tok = reservation
            attempted_models.add(current_model)
            attempts += 1
            start_time = time.time()
            try:
                raw = self.client.chat.completions.with_raw_response.create(
                    model=current_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=max_tok,
                    response_format=response_format,
                    timeout=settings.request_timeout_seconds,
                )
                response = raw.parse()
                # Budget accounting for every later call in this run.
                self._record_budget(current_model, raw.headers)

                latency_ms = int((time.time() - start_time) * 1000)
                usage = getattr(response, "usage", None)
                tokens = usage.total_tokens if usage else 0
                content = clean_prose(response.choices[0].message.content or "")

                if not content.strip():
                    raise ValueError(f"Received empty completion content from {current_model}")

                self.total_calls += 1
                self.total_tokens_used += tokens
                self.total_latency_ms += latency_ms

                # Lightweight jittered pacing between consecutive multi-agent calls
                if settings.pace_seconds > 0:
                    time.sleep(settings.pace_seconds * random.uniform(0.75, 1.25))

                self._cache_put(cache_key, content)
                return content

            except RateLimitError as e:
                last_error = e
                error_response = getattr(e, "response", None)
                error_headers = getattr(error_response, "headers", None)
                if error_headers is not None:
                    self._record_budget(current_model, error_headers)
                cooldown = self._cooldown_from_error(str(e), headers=error_headers, default=60.0)
                self._mark_rate_limited(current_model, cooldown_seconds=cooldown)
                # The next loop pass moves to whichever model still holds budget.
                continue

            except APITimeoutError as e:
                # The model was too slow, not out of quota: skip it for a while
                # so the next agent steps rotate immediately instead of burning
                # the full request timeout on every call. No quota was spent.
                last_error = e
                logger.warning(
                    f"[LLMClient] Request timed out on {current_model} after "
                    f"{settings.request_timeout_seconds}s (slow model, quota untouched). "
                    f"Skipping it for {int(settings.slow_model_cooldown_seconds)}s."
                )
                self._mark_rate_limited(
                    current_model,
                    cooldown_seconds=settings.slow_model_cooldown_seconds,
                    reason="Too slow",
                )
                time.sleep(min(backoff, 2.0))
                backoff *= 2
                continue

            except (APIError, ValueError) as e:
                err_str = str(e).lower()
                logger.warning(f"[LLMClient] Groq API or content issue on {current_model}: {e}")
                last_error = e

                if "json_validate_failed" in err_str:
                    # Structured output was cut off mid-JSON: the answer budget
                    # was too small, not the model. Retry with a larger budget
                    # instead of failing over with the same small budget
                    # (which would fail the exact same way on the next model).
                    bigger = min(base_max_tokens + 1024, settings.max_tokens_cap)
                    if bigger > base_max_tokens:
                        base_max_tokens = bigger
                        attempted_models.clear()
                        logger.info(
                            f"[LLMClient] JSON output truncated on {current_model}. "
                            f"Retrying with {base_max_tokens} max tokens."
                        )
                        time.sleep(min(backoff, 2.0))
                        backoff *= 2
                        continue

                # If model failed due to tool invocation or JSON validation quirks, cooldown it for 60s
                if "tool_use_failed" in err_str or "json_validate_failed" in err_str or "tool choice is none" in err_str:
                    logger.info(f"[LLMClient] Placing {current_model} on cooldown due to model-specific quirk ({e}).")
                    self._mark_rate_limited(current_model, cooldown_seconds=60.0, reason="Model quirk")

                if response_format is not None and len(attempted_models) >= len(candidates):
                    # Every model refused structured output: retry once in plain text.
                    response_format = None
                    attempted_models.clear()
                time.sleep(min(backoff, 2.0))
                backoff *= 2
                continue

            except Exception as e:
                logger.error(f"[LLMClient] Unexpected error on attempt {attempts}: {e}")
                last_error = e
                attempted_models.add(current_model)
                time.sleep(min(backoff, 2.0))
                backoff *= 2
                continue

        raise RuntimeError(
            f"Failed to generate response after {max_attempts} attempts. Last error: {last_error}"
        )

    def generate_json(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generates and parses a structured JSON object."""
        try:
            raw_text = self.generate(
                messages=messages,
                model=model,
                temperature=temperature,
                json_mode=True,
                max_tokens=max_tokens,
            )
        except Exception as err:
            err_str = str(err).lower()
            if "rate-limited" in err_str or "rate limit" in err_str or "exhausted" in err_str or "cooldown" in err_str:
                raise
            logger.warning(
                f"[LLMClient] Structured JSON mode failed ({err}). Retrying in standard text mode..."
            )
            raw_text = self.generate(
                messages=messages,
                model=model,
                temperature=temperature,
                json_mode=False,
                max_tokens=max_tokens,
            )

        def _try_parse(txt: str) -> Optional[Dict[str, Any]]:
            txt = txt.strip()
            if not txt:
                return None
            try:
                parsed = json.loads(txt)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            fixed = re.sub(r",\s*([\]}])", r"\1", txt)
            # Repair malformed keys missing colons like {"title","category": -> {"title": "", "category":
            fixed = re.sub(r'([{\[,])\s*"([a-zA-Z0-9_-]+)"\s*,\s*"', r'\1 "\2": "", "', fixed)
            try:
                parsed = json.loads(fixed)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            return None

        # 1. Direct parse
        res = _try_parse(raw_text)
        if res is not None:
            return res

        # 2. Markdown fence / bracket extraction
        cleaned = raw_text.strip()
        if "```json" in cleaned:
            extracted = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
            res = _try_parse(extracted)
            if res is not None:
                return res
        if "```" in cleaned:
            extracted = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
            res = _try_parse(extracted)
            if res is not None:
                return res
        if "{" in cleaned and "}" in cleaned:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            extracted = cleaned[start:end]
            res = _try_parse(extracted)
            if res is not None:
                return res

        return json.loads(raw_text)

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "llm_configured": self.is_configured,
            "total_calls": self.total_calls,
            "total_tokens_used": self.total_tokens_used,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": (
                int(self.total_latency_ms / self.total_calls)
                if self.total_calls > 0
                else 0
            ),
            "cache_hits": self.cache_hits,
        }


# Global singleton instance
llm_client = LLMClient()
