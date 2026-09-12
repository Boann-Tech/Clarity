from types import SimpleNamespace

import pytest

from app.providers import (
    ALLOWED_TOKEN_PARAMS,
    KEYLESS_PLACEHOLDER,
    PROVIDERS,
    LLMConfig,
    resolve_llm_config,
)


def settings(**overrides):
    base = {
        "llm_enabled": True,
        "llm_provider": "openai",
        "llm_base_url": None,
        "llm_api_key": "secret",
        "llm_model": "some-model",
        "llm_extra_headers": "{}",
        "llm_max_tokens_param": "max_tokens",
        "llm_timeout": 30,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_every_preset_with_a_base_url_resolves():
    for name, preset in PROVIDERS.items():
        if preset.base_url is None:
            continue
        config = resolve_llm_config(settings(llm_provider=name, llm_api_key="secret"))
        assert config.enabled, f"{name}: {config.reason}"
        assert config.base_url == preset.base_url
        assert config.provider == name


def test_base_url_env_overrides_preset():
    config = resolve_llm_config(settings(llm_base_url="https://gateway.internal/v1"))
    assert config.base_url == "https://gateway.internal/v1"


def test_unknown_provider_is_disabled_with_reason():
    config = resolve_llm_config(settings(llm_provider="mystery"))
    assert not config.enabled
    assert "mystery" in config.reason
    assert "openai" in config.reason


def test_missing_model_disables():
    config = resolve_llm_config(settings(llm_model=""))
    assert not config.enabled
    assert "CLARITY_LLM_MODEL" in config.reason


def test_missing_key_disables_for_key_required_provider():
    config = resolve_llm_config(settings(llm_provider="deepseek", llm_api_key=""))
    assert not config.enabled
    assert "CLARITY_LLM_API_KEY" in config.reason


def test_keyless_preset_uses_placeholder_key():
    config = resolve_llm_config(settings(llm_provider="ollama", llm_api_key=""))
    assert config.enabled
    assert config.api_key == KEYLESS_PLACEHOLDER


def test_custom_requires_base_url():
    config = resolve_llm_config(settings(llm_provider="custom", llm_base_url=None))
    assert not config.enabled
    assert "CLARITY_LLM_BASE_URL" in config.reason


def test_custom_with_base_url_enables():
    config = resolve_llm_config(settings(llm_provider="custom", llm_base_url="http://box:9000/v1"))
    assert config.enabled
    assert config.base_url == "http://box:9000/v1"


def test_extra_headers_are_parsed():
    config = resolve_llm_config(settings(llm_extra_headers='{"HTTP-Referer": "https://clarity.example"}'))
    assert config.enabled
    assert config.extra_headers == {"HTTP-Referer": "https://clarity.example"}


@pytest.mark.parametrize("bad", ["{not json", '["a"]', '{"k": 1}', '"text"'])
def test_invalid_extra_headers_disable(bad):
    config = resolve_llm_config(settings(llm_extra_headers=bad))
    assert not config.enabled
    assert "CLARITY_LLM_EXTRA_HEADERS" in config.reason


def test_invalid_token_param_disables():
    config = resolve_llm_config(settings(llm_max_tokens_param="max_output_tokens"))
    assert not config.enabled
    assert "CLARITY_LLM_MAX_TOKENS_PARAM" in config.reason


def test_non_positive_timeout_disables():
    for bad in (0, -1):
        config = resolve_llm_config(settings(llm_timeout=bad))
        assert not config.enabled
        assert "CLARITY_LLM_TIMEOUT" in config.reason


def test_llm_enabled_false_disables_even_with_full_config():
    config = resolve_llm_config(settings(llm_enabled=False))
    assert not config.enabled
    assert "CLARITY_LLM_ENABLED" in config.reason


def test_allowed_token_params_constant():
    assert ALLOWED_TOKEN_PARAMS == ("max_tokens", "max_completion_tokens")


def test_get_llm_config_caches(monkeypatch):
    from app import providers

    calls = {"n": 0}

    def fake_resolve(_settings):
        calls["n"] += 1
        return LLMConfig(enabled=True, provider="custom", base_url="http://x/v1", api_key="k", model="m")

    monkeypatch.setattr(providers, "_llm_config", None)
    monkeypatch.setattr(providers, "resolve_llm_config", fake_resolve)

    first = providers.get_llm_config()
    second = providers.get_llm_config()
    assert first is second
    assert calls["n"] == 1