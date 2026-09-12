"""OpenAI-compatible LLM provider presets and configuration resolution.

Clarity talks to any provider that exposes the OpenAI Chat Completions API.
Configuration is environment-driven and resolution never raises: an invalid or
incomplete configuration disables LLM use and records a human-readable reason,
so the evidence pipeline degrades to the deterministic evaluator.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("clarity.providers")

KEYLESS_PLACEHOLDER = "not-needed"
ALLOWED_TOKEN_PARAMS = ("max_tokens", "max_completion_tokens")


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str | None
    requires_key: bool = True


PROVIDERS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset("openai", "https://api.openai.com/v1"),
    "deepseek": ProviderPreset("deepseek", "https://api.deepseek.com/v1"),
    "groq": ProviderPreset("groq", "https://api.groq.com/openai/v1"),
    "openrouter": ProviderPreset("openrouter", "https://openrouter.ai/api/v1"),
    "together": ProviderPreset("together", "https://api.together.xyz/v1"),
    "mistral": ProviderPreset("mistral", "https://api.mistral.ai/v1"),
    "xai": ProviderPreset("xai", "https://api.x.ai/v1"),
    "perplexity": ProviderPreset("perplexity", "https://api.perplexity.ai"),
    "ollama": ProviderPreset("ollama", "http://localhost:11434/v1", requires_key=False),
    "lmstudio": ProviderPreset("lmstudio", "http://localhost:1234/v1", requires_key=False),
    "llamacpp": ProviderPreset("llamacpp", "http://localhost:8080/v1", requires_key=False),
    "vllm": ProviderPreset("vllm", "http://localhost:8000/v1", requires_key=False),
    "bifrost": ProviderPreset("bifrost", "http://localhost:8081/v1"),
    "custom": ProviderPreset("custom", None),
}


@dataclass
class LLMConfig:
    enabled: bool = False
    provider: str = "none"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_tokens_param: str = "max_tokens"
    timeout: int = 30
    reason: str | None = None


def _disabled(reason: str) -> LLMConfig:
    return LLMConfig(enabled=False, reason=reason)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_llm_config(settings) -> LLMConfig:
    """Compose the final LLM configuration without ever raising."""
    if not getattr(settings, "llm_enabled", True):
        return _disabled("CLARITY_LLM_ENABLED=false")

    provider_name = _text(getattr(settings, "llm_provider", "openai")).lower()
    preset = PROVIDERS.get(provider_name)
    if preset is None:
        valid = ", ".join(sorted(PROVIDERS))
        return _disabled(f"unknown CLARITY_LLM_PROVIDER '{provider_name}' (valid: {valid})")

    raw_base_url = getattr(settings, "llm_base_url", None)
    if raw_base_url is not None and not isinstance(raw_base_url, str):
        return _disabled("CLARITY_LLM_BASE_URL must be a string")
    base_url = _text(raw_base_url) or _text(preset.base_url)
    if not base_url:
        return _disabled("CLARITY_LLM_BASE_URL is required for provider 'custom'")

    model = _text(getattr(settings, "llm_model", None))
    if not model:
        return _disabled("CLARITY_LLM_MODEL is required")

    api_key = _text(getattr(settings, "llm_api_key", None))
    if not api_key:
        if preset.requires_key:
            return _disabled(f"CLARITY_LLM_API_KEY is required for provider '{provider_name}'")
        api_key = KEYLESS_PLACEHOLDER

    raw_headers = getattr(settings, "llm_extra_headers", "{}") or "{}"
    try:
        extra_headers = json.loads(raw_headers)
    except (TypeError, ValueError):
        return _disabled("CLARITY_LLM_EXTRA_HEADERS is not valid JSON")
    if not isinstance(extra_headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in extra_headers.items()
    ):
        return _disabled("CLARITY_LLM_EXTRA_HEADERS must be a JSON object of string values")

    token_param = _text(getattr(settings, "llm_max_tokens_param", "max_tokens"))
    if token_param not in ALLOWED_TOKEN_PARAMS:
        allowed = ", ".join(ALLOWED_TOKEN_PARAMS)
        return _disabled(f"CLARITY_LLM_MAX_TOKENS_PARAM must be one of {allowed}")

    timeout = getattr(settings, "llm_timeout", 30)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        return _disabled("CLARITY_LLM_TIMEOUT must be a positive integer")

    return LLMConfig(
        enabled=True,
        provider=provider_name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        extra_headers=extra_headers,
        max_tokens_param=token_param,
        timeout=timeout,
    )


_llm_config: LLMConfig | None = None


def get_llm_config() -> LLMConfig:
    """Resolve and cache the LLM configuration, logging the outcome once."""
    global _llm_config
    if _llm_config is None:
        from app.config import settings

        _llm_config = resolve_llm_config(settings)
        if _llm_config.enabled:
            logger.info(
                "LLM enabled: provider=%s host=%s",
                _llm_config.provider,
                urlparse(_llm_config.base_url).netloc or _llm_config.base_url,
            )
        else:
            logger.warning("LLM disabled: %s", _llm_config.reason)
    return _llm_config