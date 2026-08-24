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


@dataclass
class Settings:
    # Server
    host: str = os.getenv("CLARITY_HOST", "0.0.0.0")
    port: int = int(os.getenv("CLARITY_PORT", "8080"))
    debug: bool = os.getenv("CLARITY_DEBUG", "false").lower() == "true"

    # Search backends
    ddg_enabled: bool = os.getenv("CLARITY_DDG_ENABLED", "true").lower() == "true"
    google_api_key: str | None = os.getenv("CLARITY_GOOGLE_API_KEY")
    google_cse_id: str | None = os.getenv("CLARITY_GOOGLE_CSE_ID")
    serpapi_key: str | None = os.getenv("CLARITY_SERPAPI_KEY")

    # Evidence fetching
    max_sources_per_claim: int = int(os.getenv("CLARITY_MAX_SOURCES", "8"))
    max_passage_chars: int = int(os.getenv("CLARITY_MAX_PASSAGE", "600"))
    fetch_timeout: int = int(os.getenv("CLARITY_FETCH_TIMEOUT", "10"))
    user_agent: str = (
        "Clarity/1.0 (+https://github.com/boanntech/clarity) evidence-checker"
    )

    # LLM gateway — Bifrost is the single AI egress point.
    # The configured model is the exact deployment/model alias Bifrost exposes.
    bifrost_api_key: str | None = os.getenv("CLARITY_BIFROST_API_KEY")
    bifrost_base_url: str = os.getenv(
        "CLARITY_BIFROST_BASE_URL", "http://localhost:8081/v1"
    )
    bifrost_model: str = os.getenv("CLARITY_BIFROST_MODEL", "deepseek-pro")
    llm_enabled: bool = os.getenv("CLARITY_LLM_ENABLED", "true").lower() == "true"

    # Rate limiting
    rate_limit_per_minute: int = int(os.getenv("CLARITY_RATE_LIMIT", "10"))
    rate_limit_per_hour: int = int(os.getenv("CLARITY_RATE_LIMIT_HOUR", "50"))

    # Cache
    cache_ttl_seconds: int = int(os.getenv("CLARITY_CACHE_TTL", "1800"))

    # CORS — comma-separated origins
    cors_origins: list[str] = field(default_factory=lambda: os.getenv(
        "CLARITY_CORS_ORIGINS",
        "chrome-extension://*",
    ).split(","))

    # Validation
    max_claim_chars: int = 500
    min_claim_chars: int = 10


settings = Settings()