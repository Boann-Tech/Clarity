# Pluggable LLM Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Clarity's hard-coded Bifrost-only LLM configuration with generic `CLARITY_LLM_*` settings plus a preset registry for any OpenAI-compatible provider.

**Architecture:** A new `backend/app/providers.py` owns provider presets, the resolved immutable `LLMConfig`, and a non-raising resolver with a cached accessor. `config.py` reads the generic env vars; `llm.py` builds one OpenAI client from the resolved config (extra headers, timeout, token-param choice); `main.py` gates LLM use and health output on the resolved config. The extension is untouched.

**Tech Stack:** Python 3.12 / FastAPI / openai SDK / pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-pluggable-llm-providers-design.md`

## Global Constraints

- Evidence-first behavior is unchanged: the LLM never creates citations, and with no valid provider configured the deterministic evaluator runs exactly as today.
- Clean break: `CLARITY_BIFROST_*` variables are removed. The name `bifrost` survives only as a provider preset.
- `resolve_llm_config` never raises. Invalid or incomplete configuration yields `enabled=False` plus a precise `reason`.
- Extra headers are secrets: never logged, never returned by `/api/health`.
- Public API change is limited to `/api/health`: `gateway` is removed; `provider` is added; `model` is never returned.
- Python floor 3.12; no new dependencies.
- Tests baseline: `cd backend && python3 -m pytest -q` = 81 passing; `npm test` = 16 passing. Both stay green.
- Commit identity: prefix every commit with `GIT_AUTHOR_NAME='Sean Lynch' GIT_AUTHOR_EMAIL='sean.lynch@boanntech.com' GIT_COMMITTER_NAME='Sean Lynch' GIT_COMMITTER_EMAIL='sean.lynch@boanntech.com'` (do not change git config).
- Work on branch `feat/pluggable-llm-providers`.

---

### Task 1: Provider registry and resolver

**Files:**
- Create: `backend/app/providers.py`
- Create: `backend/tests/test_providers.py`

**Interfaces:**
- Produces: `ProviderPreset(name, base_url, requires_key=True)`, `PROVIDERS: dict[str, ProviderPreset]`
- Produces: `LLMConfig(enabled=False, provider="none", base_url="", api_key="", model="", extra_headers={}, max_tokens_param="max_tokens", timeout=30, reason=None)` (all fields have defaults so tests can construct stubs)
- Produces: `resolve_llm_config(settings) -> LLMConfig` (never raises)
- Produces: `get_llm_config() -> LLMConfig` (cached in module global `_llm_config`; logs once on first resolution)
- Consumes: a settings-like object with attributes `llm_enabled`, `llm_provider`, `llm_base_url`, `llm_api_key`, `llm_model`, `llm_extra_headers`, `llm_max_tokens_param`, `llm_timeout` (Task 2 adds these to `Settings`).

- [ ] **Step 1: Write the failing provider tests** — create `backend/tests/test_providers.py`

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python3 -m pytest tests/test_providers.py -q`
Expected: FAIL — `app.providers` does not exist.

- [ ] **Step 3: Implement `backend/app/providers.py`**

```python
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


def resolve_llm_config(settings) -> LLMConfig:
    """Compose the final LLM configuration without ever raising."""
    if not getattr(settings, "llm_enabled", True):
        return _disabled("CLARITY_LLM_ENABLED=false")

    provider_name = (getattr(settings, "llm_provider", "openai") or "").strip().lower()
    preset = PROVIDERS.get(provider_name)
    if preset is None:
        valid = ", ".join(sorted(PROVIDERS))
        return _disabled(f"unknown CLARITY_LLM_PROVIDER '{provider_name}' (valid: {valid})")

    base_url = (getattr(settings, "llm_base_url", None) or preset.base_url or "").strip()
    if not base_url:
        return _disabled("CLARITY_LLM_BASE_URL is required for provider 'custom'")

    model = (getattr(settings, "llm_model", None) or "").strip()
    if not model:
        return _disabled("CLARITY_LLM_MODEL is required")

    api_key = (getattr(settings, "llm_api_key", None) or "").strip()
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

    token_param = (getattr(settings, "llm_max_tokens_param", "max_tokens") or "").strip()
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
```

- [ ] **Step 4: Run the provider tests**

Run: `cd backend && python3 -m pytest tests/test_providers.py -q`
Expected: PASS (15 tests: 1 parametrized over 4 headers, plus 14 others).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python3 -m pytest -q`
Expected: PASS (81 baseline + 15 new = 96).

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers.py backend/tests/test_providers.py
git commit -m "feat: add OpenAI-compatible provider registry and resolver"
```

---

### Task 2: Wire config, client, and API onto the resolved config

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/llm.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_api_check.py`
- Modify: `backend/tests/test_api_ops.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_llm.py`

**Interfaces:**
- Consumes: `get_llm_config()`, `LLMConfig` from Task 1.
- Produces: `Settings.llm_enabled/llm_provider/llm_base_url/llm_api_key/llm_model/llm_extra_headers/llm_max_tokens_param/llm_timeout`; the `Bifrost*` fields are gone.
- Produces: pytest fixtures `llm_enabled` (enables LLM by patching `providers._llm_config`) and an autouse fixture that stubs a disabled config for isolation.
- Produces: `/api/health` returns `llm_enabled`, `provider`, `model_configured`; no `gateway`, no `model`.

- [ ] **Step 1: Add the test fixtures** — modify `backend/tests/conftest.py`

```python
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

    monkeypatch.setattr(providers, "_llm_config", _llm_stub(enabled=False))
    main._rate_limiter.reset()
    main._response_cache.clear()
    yield
    main._rate_limiter.reset()
    main._response_cache.clear()


@pytest.fixture
def llm_enabled(monkeypatch):
    from app import providers

    config = _llm_stub(enabled=True)
    monkeypatch.setattr(providers, "_llm_config", config)
    return config
```

- [ ] **Step 2: Update `config.py`**

Add above `@dataclass`:

```python
def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return 0
```

Replace the LLM block (currently `bifrost_api_key` / `bifrost_base_url` / `bifrost_model` / `llm_enabled` / `llm_timeout`) with:

```python
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
```

- [ ] **Step 3: Update `llm.py`**

Rewrite the module docstring's gateway sentences to say "the configured OpenAI-compatible provider" instead of Bifrost; replace the import `from app.config import settings` with `from app.providers import get_llm_config`.

Replace `_build_client` and the top of `_call_llm`:

```python
def _build_client():
    """Create an OpenAI-compatible client for the configured provider."""
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed — LLM features disabled")
        return None

    config = get_llm_config()
    if not config.enabled:
        return None

    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        max_retries=1,
        default_headers=config.extra_headers,
    )
```

```python
def _call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    json_mode: bool = True,
) -> str | None:
    """Call the configured provider model and return response text."""
    client = _build_client()
    if client is None:
        return None

    config = get_llm_config()
    logger.info(
        "LLM request: provider=%s model=%s json_mode=%s max_tokens=%s",
        config.provider,
        config.model,
        json_mode,
        max_tokens,
    )

    kwargs: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        config.max_tokens_param: max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
```

Update the two exception-path log lines and comments to generic wording ("The provider may not expose response_format", "LLM call failed after JSON-mode retry", `logger.info("LLM response received: model=%s", config.model)`).

- [ ] **Step 4: Update `main.py`**

Add `from app.providers import get_llm_config` next to the other app imports. Replace the health body and the `llm_available` line:

```python
@app.get("/api/health")
async def health():
    config = get_llm_config()
    return {
        "status": "ok",
        "version": "3.0.0",
        "llm_enabled": config.enabled,
        "provider": config.provider,
        "model_configured": bool(config.model),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

```python
    llm_available = get_llm_config().enabled
```

- [ ] **Step 5: Migrate `test_api_ops.py`**

- In the `_offline_and_reset` fixture, delete `monkeypatch.setattr(config.settings, "bifrost_api_key", None)` (the autouse conftest stub now disables LLM).
- In `test_health_does_not_leak_model`, delete the bifrost monkeypatch and assert:

```python
    body = TestClient(app).get("/api/health").json()
    assert "model" not in body
    assert "gateway" not in body
    assert body["model_configured"] is False
    assert body["provider"] == "none"
```

- In `test_not_checkable_cache_hit_uses_canonical_key` and `test_cache_hit_skips_evidence_retrieval`, add `llm_enabled` to the test signature and delete the two lines monkeypatching `config.settings.bifrost_api_key` / `llm_enabled`.

- [ ] **Step 6: Migrate `test_api_check.py`**

For all six tests that monkeypatch `config.settings.bifrost_api_key` / `config.settings.llm_enabled` — `test_null_limitations_does_not_500`, `test_null_snippet_and_long_title_are_coerced`, `test_context_host_cannot_independently_support_misleading`, `test_subdomain_citations_cannot_support_misleading`, `test_distinct_publishers_keep_misleading_verdict`, `test_misleading_requires_support_and_contradiction_at_boundary` — add the `llm_enabled` fixture parameter to the signature and delete those two monkeypatch lines. The `import app.llm as llm` blocks stay.

- [ ] **Step 7: Migrate `test_config.py`**

Change the fixture's env lines and assertions from `CLARITY_BIFROST_BASE_URL` / `CLARITY_BIFROST_MODEL` to `CLARITY_LLM_BASE_URL` / `CLARITY_LLM_MODEL` (same values, same monkeypatch.delenv calls).

- [ ] **Step 8: Add LLM client tests and update wording in `test_llm.py`**

Update the module docstring: "no configured LLM provider = graceful degradation" and rename `test_classify_passages_accepts_bifrost_passages_response` to `test_classify_passages_accepts_wrapped_passages_response` (keep the body). Append:

```python
# ── Client configuration ──


def test_call_llm_returns_none_when_disabled(monkeypatch):
    from app import llm, providers

    monkeypatch.setattr(providers, "_llm_config", providers.LLMConfig(enabled=False, reason="test"))

    def explode(**_kwargs):
        raise AssertionError("client must not be built when LLM is disabled")

    monkeypatch.setattr("openai.OpenAI", explode)
    assert llm._call_llm("system", "user") is None


def test_call_llm_uses_configured_client_and_token_param(monkeypatch):
    from app import llm, providers

    config = providers.LLMConfig(
        enabled=True,
        provider="custom",
        base_url="http://llm.test/v1",
        api_key="k",
        model="m",
        extra_headers={"HTTP-Referer": "https://clarity.example"},
        max_tokens_param="max_completion_tokens",
        timeout=5,
    )
    monkeypatch.setattr(providers, "_llm_config", config)

    client_kwargs = {}
    create_kwargs = {}

    class FakeCompletions:
        def create(self, **kwargs):
            create_kwargs.update(kwargs)
            message = type("Message", (), {"content": "{}"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    def fake_openai(**kwargs):
        client_kwargs.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("openai.OpenAI", fake_openai)

    result = llm._call_llm("system", "user", max_tokens=123, json_mode=False)

    assert result == "{}"
    assert client_kwargs["api_key"] == "k"
    assert client_kwargs["base_url"] == "http://llm.test/v1"
    assert client_kwargs["default_headers"] == {"HTTP-Referer": "https://clarity.example"}
    assert client_kwargs["timeout"] == 5
    assert create_kwargs["model"] == "m"
    assert create_kwargs["max_completion_tokens"] == 123
    assert "max_tokens" not in create_kwargs
```

- [ ] **Step 9: Run the full suites**

Run: `cd backend && python3 -m pytest -q`
Expected: PASS (96 baseline + 2 new = 98; adjust to actual).

Run: `npm test` (from repo root)
Expected: PASS (16).

- [ ] **Step 10: Commit**

```bash
git add backend
git commit -m "feat: configure any OpenAI-compatible provider via generic LLM settings"
```

---

### Task 3: Docs and migration notes

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Update `backend/.env.example`**

Replace lines 18–26 (the Bifrost block and standalone `CLARITY_LLM_*` lines) with:

```text
# LLM provider — any OpenAI-compatible Chat Completions endpoint.
# Presets: openai, deepseek, groq, openrouter, together, mistral, xai,
#          perplexity, ollama, lmstudio, llamacpp, vllm, bifrost, custom.
# MODEL is required to enable the LLM; leave it empty to run the
# deterministic evaluator (all verdicts Unverified unless classified).
CLARITY_LLM_ENABLED=true
CLARITY_LLM_PROVIDER=openai
CLARITY_LLM_API_KEY=
CLARITY_LLM_MODEL=
# CLARITY_LLM_BASE_URL=            # overrides the preset; required for custom
# CLARITY_LLM_EXTRA_HEADERS={}     # JSON object (e.g. OpenRouter attribution)
# CLARITY_LLM_MAX_TOKENS_PARAM=max_tokens   # or max_completion_tokens
CLARITY_LLM_TIMEOUT=30
```

- [ ] **Step 2: Update `README.md`**

- Line 64: replace `Without a \`CLARITY_BIFROST_API_KEY\`` with `Without a configured LLM provider`.
- Line 96: replace "Bifrost model classifies passages and synthesizes a constrained verdict" with "the configured LLM classifies passages and synthesizes a constrained verdict".
- Replace the entire `### AI gateway: Bifrost` section (lines 98–113) with:

````markdown
### LLM providers

Clarity sends LLM traffic to any provider that exposes the OpenAI Chat Completions API. Three values configure it: base URL, API key, and model. Named presets supply the base URL.

| Provider | Preset | Base URL | Key |
|---|---|---|---|
| OpenAI | `openai` | `https://api.openai.com/v1` | required |
| DeepSeek | `deepseek` | `https://api.deepseek.com/v1` | required |
| Groq | `groq` | `https://api.groq.com/openai/v1` | required |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | required |
| Together | `together` | `https://api.together.xyz/v1` | required |
| Mistral | `mistral` | `https://api.mistral.ai/v1` | required |
| xAI | `xai` | `https://api.x.ai/v1` | required |
| Perplexity | `perplexity` | `https://api.perplexity.ai` | required |
| Ollama | `ollama` | `http://localhost:11434/v1` | not required |
| LM Studio | `lmstudio` | `http://localhost:1234/v1` | not required |
| llama.cpp | `llamacpp` | `http://localhost:8080/v1` | not required |
| vLLM | `vllm` | `http://localhost:8000/v1` | not required |
| Bifrost (gateway) | `bifrost` | `http://localhost:8081/v1` | required |
| Anything else | `custom` | set `CLARITY_LLM_BASE_URL` | required |

```bash
# Example: DeepSeek
CLARITY_LLM_PROVIDER=deepseek
CLARITY_LLM_API_KEY=sk-...
CLARITY_LLM_MODEL=deepseek-chat

# Example: local Ollama
CLARITY_LLM_PROVIDER=ollama
CLARITY_LLM_MODEL=llama3.1

# Example: OpenRouter with attribution headers
CLARITY_LLM_PROVIDER=openrouter
CLARITY_LLM_API_KEY=sk-or-...
CLARITY_LLM_MODEL=deepseek/deepseek-chat
CLARITY_LLM_EXTRA_HEADERS={"HTTP-Referer":"https://github.com/boanntech/clarity"}
```

Models that reject `max_tokens` (some newer OpenAI models) can use `CLARITY_LLM_MAX_TOKENS_PARAM=max_completion_tokens`. If a provider rejects JSON mode, Clarity retries with a standard chat completion and ultimately falls back to the deterministic evaluator. With no model configured, evaluations are **Unverified** — Clarity never fabricates support.

**Migration from Bifrost-only config:** rename `CLARITY_BIFROST_API_KEY`/`CLARITY_BIFROST_BASE_URL`/`CLARITY_BIFROST_MODEL` to `CLARITY_LLM_API_KEY`/`CLARITY_LLM_BASE_URL`/`CLARITY_LLM_MODEL`, and set `CLARITY_LLM_PROVIDER=bifrost` (or `custom` with the same base URL).
````

- [ ] **Step 3: Verify no stale references remain**

Run: `grep -rn "BIFROST\|Bifrost" README.md backend/.env.example backend/app backend/tests`
Expected: only the `bifrost` preset in `backend/app/providers.py`, the provider examples in this plan's README section, and `test_llm.py`'s renamed test body text if any; no `CLARITY_BIFROST_*` variables.

- [ ] **Step 4: Run the full suites once more**

Run: `cd backend && python3 -m pytest -q` and `npm test` (repo root)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/.env.example README.md
git commit -m "docs: document pluggable OpenAI-compatible LLM providers"
```

---

## Review-Findings Coverage

| Requirement | Task |
|---|---|
| Generic `CLARITY_LLM_*` config, Bifrost vars removed | 2 |
| Preset registry with base URLs and key requirements | 1 |
| Local providers usable without keys | 1 |
| `EXTRA_HEADERS` and `MAX_TOKENS_PARAM` escape hatches | 1, 2 |
| Never-raise validation with logged reason | 1 |
| LLM client built from resolved config | 2 |
| Health reports provider, never model/credentials | 2 |
| Extension unchanged | all |
| Docs and migration note | 3 |

## Self-Review Notes

- Interface consistency: `get_llm_config`/`LLMConfig` names match Task 1's implementation and Task 2's imports; the `llm_enabled` fixture patches `providers._llm_config`, which both `main.get_llm_config()` and `llm._build_client()` read at call time.
- `Settings` field names in Task 2 match the attribute names Task 1's resolver reads.
- `test_api_check.py` no longer imports `config` after Step 6? It still imports `from app import config, main` — after removing all `config.settings` uses, drop `config` from that import; the same cleanup applies to `test_api_ops.py` (it still uses `config.settings` for rate limits/cache TTL, so keep it there).
- Logging happens on first `get_llm_config()` call (lazy) rather than at import; this preserves the spec's single startup log without import-time side effects.
- Test counts in this plan are estimates; Task 2's implementer records the actual totals.
