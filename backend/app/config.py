"""Clarity backend configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def load_backend_env(env_file: Path | None = None) -> None:
    """Load the backend-local .env before reading Settings defaults.

    Uvicorn does not load dotenv files automatically. Resolving relative to
    this module keeps configuration stable whether it is started from backend/
    or from a process manager with a different working directory.
    """
    resolved = env_file or Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(resolved, override=False)


load_backend_env()


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return 0


@dataclass
class Settings:
    # API security — optional bearer token. Empty means unauthenticated.
    api_token: str | None = os.getenv("CLARITY_API_TOKEN")

    # Search backends
    ddg_enabled: bool = os.getenv("CLARITY_DDG_ENABLED", "true").lower() == "true"
    google_api_key: str | None = os.getenv("CLARITY_GOOGLE_API_KEY")
    google_cse_id: str | None = os.getenv("CLARITY_GOOGLE_CSE_ID")
    serpapi_key: str | None = os.getenv("CLARITY_SERPAPI_KEY")
    brave_search_api_key: str | None = os.getenv("CLARITY_BRAVE_SEARCH_API_KEY")

    # Evidence fetching
    max_sources_per_claim: int = int(os.getenv("CLARITY_MAX_SOURCES", "8"))
    max_passage_chars: int = int(os.getenv("CLARITY_MAX_PASSAGE", "600"))
    fetch_timeout: int = int(os.getenv("CLARITY_FETCH_TIMEOUT", "10"))
    user_agent: str = (
        "Clarity/1.0 (+https://github.com/boanntech/clarity) evidence-checker"
    )

    # LLM provider — any OpenAI-compatible Chat Completions endpoint.
    # Presets and validation live in app.providers.
    llm_enabled: bool = os.getenv("CLARITY_LLM_ENABLED", "true").lower() == "true"
    llm_provider: str = os.getenv("CLARITY_LLM_PROVIDER", "openai")
    llm_base_url: str | None = os.getenv("CLARITY_LLM_BASE_URL")
    llm_api_key: str | None = os.getenv("CLARITY_LLM_API_KEY")
    llm_model: str | None = os.getenv("CLARITY_LLM_MODEL")
    llm_extra_headers: str = os.getenv("CLARITY_LLM_EXTRA_HEADERS", "{}")
    llm_max_tokens_param: str = os.getenv("CLARITY_LLM_MAX_TOKENS_PARAM", "max_tokens")
    llm_timeout: int = _positive_int_env("CLARITY_LLM_TIMEOUT", 30)

    # Rate limiting
    rate_limit_per_minute: int = int(os.getenv("CLARITY_RATE_LIMIT", "60"))
    rate_limit_per_hour: int = int(os.getenv("CLARITY_RATE_LIMIT_HOUR", "500"))

    # Cache
    cache_ttl_seconds: int = int(os.getenv("CLARITY_CACHE_TTL", "1800"))

    # CORS — comma-separated origins
    cors_origins: list[str] = field(default_factory=lambda: os.getenv(
        "CLARITY_CORS_ORIGINS",
        "chrome-extension://*",
    ).split(","))


settings = Settings()