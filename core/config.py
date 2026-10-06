"""
Application Configuration Manager.
Loads settings from environment and provides central configuration for all agents.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _parse_model_chain() -> list:
    """
    Builds the fallback model chain used to absorb Groq free-tier rate limits.
    ORDER env var wins if provided; otherwise primary + fast + high-quota Groq defaults.
    """
    raw = os.getenv("MODEL_CHAIN", "")
    if raw.strip():
        chain = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        chain = [
            os.getenv("PRIMARY_MODEL", "openai/gpt-oss-120b"),
            os.getenv("FAST_MODEL", "qwen/qwen3.8-27b"),
            os.getenv("CODE_MODEL", "openai/gpt-oss-20b"),
        ]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


@dataclass(frozen=True)
class Settings:
    # API Credentials
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")

    # Models (model_chain is the ordered rate-limit fallback rotation)
    primary_model: str = os.getenv("PRIMARY_MODEL", "openai/gpt-oss-120b")
    fast_model: str = os.getenv("FAST_MODEL", "openai/gpt-oss-20b")
    code_model: str = os.getenv("CODE_MODEL", "qwen/qwen3.8-27b")
    model_chain: list = field(default_factory=_parse_model_chain)

    # Execution limits (tuned for Groq free-tier rate limit guardrails)
    max_tokens_per_req: int = int(os.getenv("MAX_TOKENS_PER_REQ", "2500"))
    max_tokens_cap: int = int(os.getenv("MAX_TOKENS_CAP", "4096"))
    context_token_budget: int = int(os.getenv("CONTEXT_TOKEN_BUDGET", "2500"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "2"))

    # Inter-call pacing (seconds, jittered) to smooth RPM bursts across agents
    pace_seconds: float = float(os.getenv("PACE_SECONDS", "0.15"))

    # Free-tier budget guardrails (Groq gives each model a fixed requests/minute,
    # requests/day and tokens/minute budget, all reported in response headers)
    # Never spend a model's whole token window on one answer; keep this much back.
    budget_safety_margin: int = int(os.getenv("BUDGET_SAFETY_MARGIN", "512"))
    # Smallest answer we will ask for when we have to shrink to fit the budget.
    min_tokens_floor: int = int(os.getenv("MIN_TOKENS_FLOOR", "400"))
    # Prompts larger than this stay on the strongest model; smaller prompts are
    # spread across every model so one model never carries the whole run.
    small_prompt_tokens: int = int(os.getenv("SMALL_PROMPT_TOKENS", "600"))
    # How long one request may wait for a rate-limit window to refill before the
    # agents fall back to their built-in grounded answers.
    max_wait_seconds: float = float(os.getenv("MAX_WAIT_SECONDS", "12"))
    # How long a model that timed out (too slow, quota untouched) is skipped
    # so later agent steps rotate immediately instead of hanging again.
    slow_model_cooldown_seconds: float = float(os.getenv("SLOW_MODEL_COOLDOWN_SECONDS", "180"))

    # Plain-language output: ask the model for everyday wording and strip filler.
    plain_language: bool = os.getenv("PLAIN_LANGUAGE", "1") not in ("0", "false", "False")

    # Short-TTL completion cache: identical agent prompts within the TTL cost zero quota
    llm_cache_enabled: bool = os.getenv("LLM_CACHE_ENABLED", "1") not in ("0", "false", "False")
    llm_cache_ttl_seconds: int = int(os.getenv("LLM_CACHE_TTL_SECONDS", "600"))

    # Project directories
    root_dir: Path = ROOT_DIR

    def validate(self) -> None:
        if not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. Please add it to your .env file or environment variables."
            )


settings = Settings()
