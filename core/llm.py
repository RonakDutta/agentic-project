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
        target_model = model or settings.primary_model
        temp = temperature if temperature is not None else settings.temperature
        max_tok = max_tokens or settings.max_tokens_per_req

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

                self.total_calls += 1
                self.total_tokens_used += tokens
                self.total_latency_ms += latency_ms

                return response.choices[0].message.content or ""

            except RateLimitError as e:
                logger.warning(
                    f"[LLMClient] Rate limit hit on {current_model}. Falling back to {settings.fast_model}."
                )
                last_error = e
                current_model = settings.fast_model
                time.sleep(1.0)

            except APIError as e:
                logger.warning(f"[LLMClient] Groq API error on attempt {attempts}: {e}")
                last_error = e
                time.sleep(1.0)

            except Exception as e:
                logger.error(f"[LLMClient] Unexpected error on attempt {attempts}: {e}")
                last_error = e
                time.sleep(1.0)

        raise RuntimeError(
            f"Failed to generate response after {settings.retry_attempts} attempts. Last error: {last_error}"
        )

    def generate_json(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Generates and parses a structured JSON object.
        """
        raw_text = self.generate(
            messages=messages,
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            # Fallback markdown code fence extraction
            cleaned = raw_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
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
