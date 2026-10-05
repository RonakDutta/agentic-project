"""
LLM Client Wrapper for Groq API.
Handles chat completions, structured JSON parsing, fallback on rate limits (429),
and latency/token tracking for live agent trace visualization.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from groq import Groq, RateLimitError, APIError
from core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        settings.validate()
        self.client = Groq(api_key=settings.groq_api_key)
        self.total_calls = 0
        self.total_tokens_used = 0
        self.total_latency_ms = 0
        self._model_cooldowns: Dict[str, float] = {}
        self._logged_rate_limits: Dict[str, float] = {}

    def _get_candidate_models(self, preferred_model: Optional[str] = None) -> List[str]:
        """
        Builds an ordered list of candidate models without duplicates.
        Order: preferred_model -> primary_model -> fast_model -> code_model.
        """
        candidates: List[str] = []
        if preferred_model:
            candidates.append(preferred_model)
        for m in [settings.primary_model, settings.fast_model, settings.code_model]:
            if m and m not in candidates:
                candidates.append(m)
        return candidates

    def _get_healthy_model(self, preferred_model: Optional[str] = None) -> Optional[str]:
        """
        Finds the first candidate model that is not currently on cooldown.
        """
        now = time.time()
        for m in self._get_candidate_models(preferred_model):
            if now >= self._model_cooldowns.get(m, 0):
                return m
        return None

    def _mark_rate_limited(self, model: str, cooldown_seconds: float = 60.0) -> None:
        """
        Places a model on cooldown and logs the transition once to prevent log spam.
        """
        now = time.time()
        self._model_cooldowns[model] = now + cooldown_seconds
        last_logged = self._logged_rate_limits.get(model, 0)
        if now - last_logged >= cooldown_seconds:
            self._logged_rate_limits[model] = now
            logger.warning(
                f"[LLMClient] Rate limit on {model}. Placed on cooldown for {int(cooldown_seconds)}s."
            )

    def generate(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Executes a completion call with automatic fallback and retry logic.
        """
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
        max_tok = min(max_tokens or settings.max_tokens_per_req, 800)
        response_format = {"type": "json_object"} if json_mode else None

        attempts = 0
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

                # Lightweight pacing between consecutive multi-agent calls to respect Groq rate limits
                time.sleep(0.35)

                return content

            except RateLimitError as e:
                err_msg = str(e).lower()
                last_error = e
                if "otpm" in err_msg or "reduce max_tokens" in err_msg or "output tokens" in err_msg:
                    max_tok = min(max_tok, 400)

                # Mark model on cooldown so subsequent agent calls don't hammer it
                self._mark_rate_limited(current_model, cooldown_seconds=60.0)

                # Route immediately to next healthy model
                next_model = self._get_healthy_model()
                if next_model and next_model != current_model:
                    logger.info(f"[LLMClient] Falling back from {current_model} to {next_model}.")
                    current_model = next_model
                    time.sleep(0.3)
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
                time.sleep(0.3)

            except Exception as e:
                logger.error(f"[LLMClient] Unexpected error on attempt {attempts}: {e}")
                last_error = e
                time.sleep(0.5)

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
        """
        Generates and parses a structured JSON object.
        """
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
            "total_calls": self.total_calls,
            "total_tokens_used": self.total_tokens_used,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": (
                int(self.total_latency_ms / self.total_calls)
                if self.total_calls > 0
                else 0
            ),
        }


# Global singleton instance
llm_client = LLMClient()
