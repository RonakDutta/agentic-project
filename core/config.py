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
            os.getenv("FAST_MODEL", "openai/gpt-oss-20b"),
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
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
    code_model: str = os.getenv("CODE_MODEL", "qwen/qwen3-32b")
    model_chain: list = field(default_factory=_parse_model_chain)

    # Execution limits (tuned for Groq free-tier rate limit guardrails)
    max_tokens_per_req: int = int(os.getenv("MAX_TOKENS_PER_REQ", "750"))
    max_tokens_cap: int = int(os.getenv("MAX_TOKENS_CAP", "800"))
    context_token_budget: int = int(os.getenv("CONTEXT_TOKEN_BUDGET", "2500"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))

    # Inter-call pacing (seconds, jittered) to smooth RPM bursts across agents
    pace_seconds: float = float(os.getenv("PACE_SECONDS", "0.15"))

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
