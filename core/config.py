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


# One place for the default model names, so config, .env.example and README agree.
DEFAULT_PRIMARY_MODEL = "openai/gpt-oss-120b"
DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_CODE_MODEL = "qwen/qwen3.8-27b"


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default) not in ("0", "false", "False", "")


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
            os.getenv("PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL),
            os.getenv("FAST_MODEL", DEFAULT_FAST_MODEL),
            os.getenv("CODE_MODEL", DEFAULT_CODE_MODEL),
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
    primary_model: str = os.getenv("PRIMARY_MODEL", DEFAULT_PRIMARY_MODEL)
    fast_model: str = os.getenv("FAST_MODEL", DEFAULT_FAST_MODEL)
    code_model: str = os.getenv("CODE_MODEL", DEFAULT_CODE_MODEL)
    model_chain: list = field(default_factory=_parse_model_chain)

    # Execution limits (tuned for Groq free-tier rate limit guardrails)
    max_tokens_per_req: int = int(os.getenv("MAX_TOKENS_PER_REQ", "2500"))
    max_tokens_cap: int = int(os.getenv("MAX_TOKENS_CAP", "4096"))
    context_token_budget: int = int(os.getenv("CONTEXT_TOKEN_BUDGET", "2500"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    # gpt-oss-120b needs well over 10s for a 2-3k token JSON answer on the free tier.
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
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

    # Reasoning models (gpt-oss, qwen3) spend hidden "thinking" tokens out of
    # max_tokens. "low" keeps answers fast and inside the free token window.
    reasoning_effort: str = os.getenv("REASONING_EFFORT", "low")

    # Groq free-tier limits per model (secondary sources, Sept 2026, for
    # gpt-oss-120b, gpt-oss-20b and qwen3.8-27b): 30 RPM, 1,000 RPD, 8,000 TPM,
    # 200,000 TPD. Check console.groq.com/settings/limits for your account and
    # override here. The client enforces these locally from the first call,
    # before any x-ratelimit-* header has been seen.
    free_tier_rpm: int = int(os.getenv("FREE_TIER_RPM", "30"))
    free_tier_rpd: int = int(os.getenv("FREE_TIER_RPD", "1000"))
    free_tier_tpm: int = int(os.getenv("FREE_TIER_TPM", "8000"))
    free_tier_tpd: int = int(os.getenv("FREE_TIER_TPD", "200000"))
    # Persist today's per-model usage so the daily budget survives restarts.
    llm_usage_ledger_enabled: bool = _flag("LLM_USAGE_LEDGER")

    # Plain-language output: ask the model for everyday wording and strip filler.
    plain_language: bool = _flag("PLAIN_LANGUAGE")

    # Short-TTL completion cache: identical agent prompts within the TTL cost zero quota
    llm_cache_enabled: bool = _flag("LLM_CACHE_ENABLED")
    llm_cache_ttl_seconds: int = int(os.getenv("LLM_CACHE_TTL_SECONDS", "600"))
    # Persistent SQLite copy of the cache, so a demo re-run after a restart is free.
    llm_disk_cache_enabled: bool = _flag("LLM_DISK_CACHE")
    llm_disk_cache_ttl_seconds: int = int(os.getenv("LLM_DISK_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))
    llm_disk_cache_path: str = os.getenv("LLM_DISK_CACHE_PATH", str(ROOT_DIR / ".cache" / "llm_cache.sqlite"))

    # Web search: TAVILY_API_KEY (free tier) is used first when set.
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    # Repository ingestion limits. ALLOWED_REPO_ROOTS (os.pathsep-separated)
    # restricts which local folders /api/inspect-repo may index; empty = any
    # (fine for a local demo, set it before hosting the app anywhere).
    allowed_repo_roots: str = os.getenv("ALLOWED_REPO_ROOTS", "")
    max_repo_files: int = int(os.getenv("MAX_REPO_FILES", "400"))
    max_clone_mb: int = int(os.getenv("MAX_CLONE_MB", "200"))

    # Project directories
    root_dir: Path = ROOT_DIR

    def validate(self) -> None:
        if not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. Please add it to your .env file or environment variables."
            )


settings = Settings()
