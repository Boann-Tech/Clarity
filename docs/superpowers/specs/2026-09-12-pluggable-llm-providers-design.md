# Pluggable OpenAI-Compatible LLM Providers — Design

**Date:** 2026-09-12
**Status:** Approved for planning
**Sub-project:** 1 of 4 in the Clarity hardening program (followed by P0 security/ops, P1 product, P2 quality).

## Summary

Clarity's backend currently hard-codes a single AI gateway ("Bifrost") via `CLARITY_BIFROST_*` environment variables. This design replaces that with generic `CLARITY_LLM_*` configuration plus a code-level registry of preset OpenAI-compatible providers. Any provider that exposes the OpenAI Chat Completions API can be used; the extension remains provider-agnostic because it only talks to the Clarity backend.

The evidence-first invariant is unchanged: the LLM only normalizes claims, classifies retrieved passages, and synthesizes verdicts from those passages. It never creates citations. When no provider is configured, the deterministic evaluator handles every request exactly as it does today.

## Goals

- Configure any OpenAI-compatible provider with three values: base URL, API key, model.
- Ship named presets so common providers need only a key and model.
- Make local providers (keyless) work without fake-key friction beyond a placeholder.
- Provide minimal escape hatches for gateways and newer models: extra headers and token-parameter selection.
- Fail safe: any invalid or incomplete configuration disables LLM use with a precise startup log reason; verdicts degrade to the deterministic path rather than erroring.
- Keep the extension and public API response shape unchanged.

## Non-goals

- Built-in failover, load balancing, or routing across providers (a gateway such as Bifrost/LiteLLM can front Clarity for that).
- Runtime provider switching via API; configuration is environment-driven.
- Azure OpenAI URL/auth mode, streaming responses, embeddings, or non-chat endpoints.
- Per-provider prompt tuning.
- Exposing the model name or any credential through `/api/health`.

## Configuration Surface

Clean break: `CLARITY_BIFROST_*` variables are removed. Bifrost survives only as a preset name.

| Variable | Default | Meaning |
|---|---|---|
| `CLARITY_LLM_ENABLED` | `true` | Master switch; `false` disables all LLM calls regardless of other values. |
| `CLARITY_LLM_PROVIDER` | `openai` | Preset name (see table). Unknown names disable LLM use with a startup warning. |
| `CLARITY_LLM_BASE_URL` | preset value | Overrides the preset's base URL. Required when provider is `custom`. |
| `CLARITY_LLM_API_KEY` | none | Required for key-required presets. For keyless presets a placeholder is injected. |
| `CLARITY_LLM_MODEL` | none | Required. Model or deployment alias exactly as the provider names it. |
| `CLARITY_LLM_EXTRA_HEADERS` | `{}` | JSON object of additional request headers (e.g. OpenRouter attribution). Parsed once; malformed JSON disables LLM use with a warning. |
| `CLARITY_LLM_MAX_TOKENS_PARAM` | `max_tokens` | Either `max_tokens` or `max_completion_tokens`, for models that reject the former. |
| `CLARITY_LLM_TIMEOUT` | `30` | Per-request timeout in seconds; must be a positive integer. |

## Presets

| Name | Base URL | Key required |
|---|---|---|
| `openai` | `https://api.openai.com/v1` | yes |
| `deepseek` | `https://api.deepseek.com/v1` | yes |
| `groq` | `https://api.groq.com/openai/v1` | yes |
| `openrouter` | `https://openrouter.ai/api/v1` | yes |
| `together` | `https://api.together.xyz/v1` | yes |
| `mistral` | `https://api.mistral.ai/v1` | yes |
| `xai` | `https://api.x.ai/v1` | yes |
| `perplexity` | `https://api.perplexity.ai` | yes |
| `ollama` | `http://localhost:11434/v1` | no |
| `lmstudio` | `http://localhost:1234/v1` | no |
| `llamacpp` | `http://localhost:8080/v1` | no |
| `vllm` | `http://localhost:8000/v1` | no |
| `bifrost` | `http://localhost:8081/v1` | yes |
| `custom` | none — must be set | yes |

Presets carry only a base URL and key requirement. No preset supplies a default model, so no stale model names ship in the codebase.

## Resolution Policy

`providers.resolve_llm_config(settings) -> LLMConfig` composes the final configuration and **never raises**. It returns `enabled=False` plus a `reason` string for any of:

- `CLARITY_LLM_ENABLED=false`
- unknown provider name (reason lists valid names)
- `custom` without a base URL
- missing `CLARITY_LLM_MODEL`
- missing API key on a key-required preset
- `CLARITY_LLM_EXTRA_HEADERS` that is not valid JSON or not a JSON object
- `CLARITY_LLM_MAX_TOKENS_PARAM` outside the allowed set
- `CLARITY_LLM_TIMEOUT` not a positive integer

Keyless presets receive the placeholder key `not-needed`. `providers.get_llm_config()` caches the resolved config at first access; `main.py` calls it once at import and logs a single startup line: provider name, base-URL host, model configured yes/no, enabled yes/no, reason when disabled.

## Components and Interfaces

New module `backend/app/providers.py`:

```python
@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str | None
    requires_key: bool = True
    keyless_placeholder: str = "not-needed"

@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    provider: str
    base_url: str
    api_key: str
    model: str
    extra_headers: dict[str, str]
    max_tokens_param: str
    timeout: int
    reason: str | None = None

PROVIDERS: dict[str, ProviderPreset] = {...}

def resolve_llm_config(settings) -> LLMConfig: ...
def get_llm_config() -> LLMConfig: ...   # cached accessor used by app.llm
```

Changed modules:

- `backend/app/config.py`: removes `bifrost_api_key`, `bifrost_base_url`, `bifrost_model`; adds the eight `CLARITY_LLM_*` fields; calls `load_backend_env()` as today.
- `backend/app/llm.py`: `_build_client()` builds an `OpenAI` client from `get_llm_config()` with `default_headers`, `timeout`, `max_retries=1`; `_call_llm` sends the configured token parameter name. JSON-mode retry and deterministic fallback are unchanged.
- `backend/app/main.py`: `llm_available` becomes `get_llm_config().enabled`; `/api/health` returns `provider` and `llm_enabled`/`model_configured`, never the model string.
- `backend/app/evidence.py`: unchanged; `use_llm` still gates classification.
- `backend/.env.example`, `README.md`: preset table, per-provider examples, migration note.

## Data Flow

1. Import: env vars → `Settings` → `resolve_llm_config` → cached `LLMConfig`; one startup log line.
2. Request: `check_claim` checks `llm_config.enabled`; if enabled, `normalize_claim` → per-query retrieval with `use_llm=True` → `classify_passages` → `synthesize_verdict`, all through the one configured client. If disabled, the existing deterministic path runs untouched.
3. Health: `{ llm_enabled, provider, model_configured }` — provider name and booleans only.

## Error Handling

- Invalid configuration: `enabled=False` + logged reason; no exception at import, no crash during requests.
- Runtime provider errors: existing `_call_llm` retry-without-JSON-mode then `None` → deterministic fallback. The client already caps retries at 1 and uses the configured timeout.
- Extra headers are secrets: never logged, never returned in health or error messages.
- No change to evidence-first guards or verdict integrity introduced by this design.

## Testing

All tests offline; `_call_llm` is monkeypatched where LLM behavior is not under test.

- New `backend/tests/test_providers.py`:
  - each preset resolves to its documented base URL
  - `CLARITY_LLM_BASE_URL` overrides the preset
  - unknown provider → disabled with reason naming the provider
  - missing model → disabled; missing key on key-required preset → disabled
  - keyless preset with empty key → enabled with placeholder
  - `custom` without base URL → disabled; with base URL → enabled
  - extra headers valid JSON parsed; malformed and non-object JSON → disabled
  - token param whitelist; timeout validation
  - `CLARITY_LLM_ENABLED=false` disables even with a complete config
- `backend/tests/test_llm.py`: asserts `_call_llm` sends the configured token parameter (kwargs captured from a fake client), and unchanged fallback behavior.
- `backend/tests/test_api_check.py`: replaces `settings.bifrost_api_key` monkeypatching with a stubbed resolved `LLMConfig`.
- `backend/tests/test_config.py`: updates env-var names in its fixture.
- Full suites remain green: `python3 -m pytest -q` and `npm test`.

## Security Notes

- Provider credentials stay server-side; the extension still holds only the backend URL and optional backend token.
- `CLARITY_LLM_EXTRA_HEADERS` may carry additional secrets (e.g. gateway attribution tokens); treat the dict as secret and redact in logs.
- `/api/health` reveals the provider family name and configuration booleans only; this is acceptable and useful for operators.

## Docs and Migration

- README replaces the "Bifrost is the only egress point" section with "LLM providers": preset table, three-var quickstart, and worked examples for OpenAI, DeepSeek, Groq, OpenRouter, Ollama, and Bifrost-as-a-gateway.
- `.env.example` documents all `CLARITY_LLM_*` variables with commented examples.
- Migration note: existing `CLARITY_BIFROST_API_KEY` / `CLARITY_BIFROST_BASE_URL` / `CLARITY_BIFROST_MODEL` must be renamed to `CLARITY_LLM_API_KEY` / `CLARITY_LLM_BASE_URL` / `CLARITY_LLM_MODEL`; set `CLARITY_LLM_PROVIDER=bifrost` (or `custom` with the same base URL) to reproduce previous behavior exactly.

## Out of Scope

Failover/routing, runtime switching, Azure OpenAI, streaming, model defaulting, per-provider prompt tuning, and any extension-side provider UI.
