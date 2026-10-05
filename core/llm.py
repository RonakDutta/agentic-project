"""
LLM Client Wrapper for Groq API.
Handles chat completions, structured JSON parsing, rate-limit-aware fallback across
a model chain, TTL response caching, and latency/token tracking for live agent trace
visualization.

Rate-Limit Strategy (Groq free tier):
- Rotates across a chain of candidate models so per-model RPM/TPM budgets are pooled.
- Parses 429 'retry-after' / 'please try again in Xs' hints into precise per-model cooldowns.
- Backs off exponentially with jitter instead of hammering the API.
- Caches identical completions for a short TTL so repeated follow-ups cost zero quota.
"""

import hashlib
import json
import logging
import random
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from groq import Groq, RateLimitError, APIError
from core.config import settings

logger = logging.getLogger(__name__)

# Matches Groq 429 messages like: "Rate limit reached for model ... on tokens per min (TPM):
# Limit 6000, Used 5932, Requested 812. Please try again in 7.31s"
_RETRY_HINT_RE = re.compile(r"try again in\s+([0-9.]+)\s*s", re.IGNORECASE)


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

    def _get_healthy_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
        """Finds the first candidate model that is not currently on cooldown."""
        now = time.time()
        for m in self._get_candidate_models(preferred_model):
            if now >= self._model_cooldowns.get(m, 0):
                return m
        return None

    def _mark_rate_limited(self, model: str, cooldown_seconds: float) -> None:
        """Places a model on cooldown and logs the transition once to prevent log spam."""
        now = time.time()
        self._model_cooldowns[model] = now + cooldown_seconds
        last_logged = self._logged_rate_limits.get(model, 0)
        if now - last_logged >= cooldown_seconds:
            self._logged_rate_limits[model] = now
            logger.warning(
                f"[LLMClient] Rate limit on {model}. Placed on cooldown for {int(cooldown_seconds)}s."
            )

    def _cooldown_from_error(self, err_msg: str, default: float = 60.0) -> float:
        """Extracts a precise cooldown from a Groq 429 payload when possible."""
        match = _RETRY_HINT_RE.search(err_msg)
        if match:
            # Add a small safety margin over Groq's suggested wait.
            return min(max(float(match.group(1)) + 0.75, 1.0), 300.0)
        return default

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Snapshot of per-model cooldowns for observability endpoints."""
        now = time.time()
        active = {
            model: round(until - now, 1)
            for model, until in self._model_cooldowns.items()
            if until > now
        }
        return {
            "cooldowns": active,
            "all_rate_limited": len(active) >= len(self._get_candidate_models()),
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

        cache_key = self._cache_key(messages, model, temperature, json_mode, max_tokens)
        cached = self._cache_get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        target_model = self._get_healthy_model(model)
        if not target_model:
            now = time.time()
            last_all = self._logged_rate_limits.get("__all__", 0)
            if now - last_all >= 30.0:
                self._logged_rate_limits["__all__"] = now
                logger.warning(
                    "[LLMClient] All models are currently on rate-limit cooldown. Activating deterministic fallback."
                )
            raise RuntimeError("All configured Groq models are currently rate-limited. Activating deterministic fallback.")

        temp = temperature if temperature is not None else settings.temperature
        max_tok = min(max_tokens or settings.max_tokens_per_req, settings.max_tokens_cap)
        response_format = {"type": "json_object"} if json_mode else None

        attempts = 0
        backoff = settings.pace_seconds
        last_error = None
        current_model = target_model

        while attempts < settings.retry_attempts:
            attempts += 1
            start_time = time.time()
            try:
                response = self.client.chat.completions.create(
                    model=current_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=max_tok,
                    response_format=response_format,
                    timeout=settings.request_timeout_seconds,
                )

                latency_ms = int((time.time() - start_time) * 1000)
                usage = getattr(response, "usage", None)
                tokens = usage.total_tokens if usage else 0
                content = response.choices[0].message.content or ""

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
                err_msg = str(e)
                last_error = e
                if "otpm" in err_msg.lower() or "reduce max_tokens" in err_msg.lower() or "output tokens" in err_msg.lower():
                    max_tok = min(max_tok, 400)

                cooldown = self._cooldown_from_error(err_msg, default=60.0)
                self._mark_rate_limited(current_model, cooldown_seconds=cooldown)

                # Route immediately to the next healthy model in the chain
                next_model = self._get_healthy_model()
                if next_model and next_model != current_model:
                    logger.info(f"[LLMClient] Falling back from {current_model} to {next_model}.")
                    current_model = next_model
                    time.sleep(0.25)
                else:
                    logger.warning("[LLMClient] All models exhausted on Groq. Activating deterministic fallback.")
                    raise RuntimeError("All models exhausted on Groq. Activating deterministic fallback.")

            except (APIError, ValueError) as e:
                logger.warning(f"[LLMClient] Groq API or content issue on {current_model}: {e}")
                last_error = e
                candidates = self._get_candidate_models(current_model)
                next_candidates = [m for m in candidates if m != current_model]
                if next_candidates:
                    current_model = next_candidates[0]
                elif response_format is not None:
                    response_format = None
                time.sleep(min(backoff, 2.0))
                backoff *= 2

            except Exception as e:
                logger.error(f"[LLMClient] Unexpected error on attempt {attempts}: {e}")
                last_error = e
                time.sleep(min(backoff, 2.0))
                backoff *= 2

        raise RuntimeError(
            f"Failed to generate response after {settings.retry_attempts} attempts. Last error: {last_error}"
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

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback markdown code fence extraction
            cleaned = raw_text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()
            elif "{" in cleaned and "}" in cleaned:
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                cleaned = cleaned[start:end]
            return json.loads(cleaned.strip())

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
