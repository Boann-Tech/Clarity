"""Shared test isolation for process-wide API state."""

import pytest

from app.providers import LLMConfig


def _llm_stub(enabled: bool) -> LLMConfig:
    if not enabled:
        return LLMConfig(enabled=False, provider="none", reason="test stub")
    return LLMConfig(
        enabled=True,
        provider="custom",
        base_url="http://llm.test/v1",
        api_key="test",
        model="test-model",
        extra_headers={},
        max_tokens_param="max_tokens",
        timeout=5,
    )


@pytest.fixture(autouse=True)
def _reset_api_state(monkeypatch):
    from app import main, providers
    from app.metrics import metrics

    monkeypatch.setattr(providers, "_llm_config", _llm_stub(enabled=False))
    main._rate_limiter.reset()
    main._response_cache.clear()
    metrics.reset()
    yield
    main._rate_limiter.reset()
    main._response_cache.clear()
    metrics.reset()


@pytest.fixture
def llm_enabled(monkeypatch):
    from app import providers

    config = _llm_stub(enabled=True)
    monkeypatch.setattr(providers, "_llm_config", config)
    return config
