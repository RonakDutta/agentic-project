"""
Application Configuration Manager.
Loads settings from environment and provides central configuration for all agents.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    # API Credentials
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")

    # Models
    primary_model: str = os.getenv("PRIMARY_MODEL", "openai/gpt-oss-120b")
    fast_model: str = os.getenv("FAST_MODEL", "openai/gpt-oss-20b")
    code_model: str = os.getenv("CODE_MODEL", "qwen/qwen3.8-27b")

    # Execution limits (tuned for Groq free-tier rate limit guardrails)
    max_tokens_per_req: int = int(os.getenv("MAX_TOKENS_PER_REQ", "2500"))
    context_token_budget: int = int(os.getenv("CONTEXT_TOKEN_BUDGET", "2500"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.2"))
    request_timeout_seconds: int = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    retry_attempts: int = int(os.getenv("RETRY_ATTEMPTS", "3"))

    # Project directories
    root_dir: Path = ROOT_DIR

    def validate(self) -> None:
        if not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is not set. Please add it to your .env file or environment variables."
            )


settings = Settings()
