<div align="center">
  <img src="src/icons/icon.svg" width="80" alt="Clarity logo" />
  <h1 align="center">Clarity</h1>
  <p align="center"><strong>Evidence for what you read.</strong></p>
  <p align="center">
    A Chrome extension that checks factual claims against authoritative sources.
    <br />
    Fights misinformation by <strong>showing evidence</strong>, not telling you what to believe.
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="Version" />
    <img src="https://img.shields.io/badge/tests-88%20passing-green.svg" alt="Tests" />
    <img src="https://img.shields.io/badge/Chrome-MV3-yellow.svg" alt="MV3" />
    <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="License" />
  </p>
  <br />
</div>

## Why Clarity?

Every day, we read articles, watch YouTube videos, and scroll through social media where people make factual claims. Some are true. Some are misleading. Some are outright false. The hard part? **You can't fact-check everything yourself.**

Clarity sits in your browser sidebar and does the legwork — it reads the page, identifies checkable claims, finds evidence from curated authoritative sources, and presents a transparent assessment with citations.

**It never tells you what to believe. It shows you the evidence so you can decide.**

## How it works

1. **Open** any article or YouTube video
2. **Click** the Clarity icon → the side panel opens
3. **Press** "Check claims on this page"
4. **Review** each claim's evidence-backed assessment

## Verdict system

Clarity uses five verdicts — none of them claim absolute truth:

| Verdict | What it means |
|---|---|
| **Supported** | The available evidence backs this claim |
| **Contradicted** | The available evidence contradicts this claim |
| **Misleading** | The claim omits important context (requires 2+ independent sources) |
| **Unverified** | No verified evidence could be found |
| **Not checkable** | This is an opinion, prediction, or value statement |

> **No citations? No verdict.** Clarity will never show Supported, Contradicted, or Misleading without at least one cited source. Without evidence, the answer is always **Unverified** — and that's honest.

## Source quality

Not all sources are equal. Clarity ranks them by authority and independence:

| Tier | Sources |
|---|---|
| **Primary** | Government statistics, WHO, CDC, legislation, central banks, court filings, peer-reviewed research |
| **Fact check** | Reuters, AP, PolitiFact, Snopes, FactCheck.org, Full Fact |
| **Secondary** | BBC, Guardian, NYT (used when primary unavailable) |

Unverified blogs, anonymous forum posts, AI-generated content, and social media are never used as evidence.

## Backend

The evidence retrieval backend is a standalone FastAPI service at `backend/`.

**Fail closed:** a verdict is only issued when evidence is fetched and classified. Without a configured LLM provider, the deterministic evaluator returns **Unverified** — Clarity never fabricates support.

### Retrieval providers

Clarity never treats a search snippet as evidence. Search providers only discover candidate URLs; every displayed citation is fetched, source-tiered, passage-classified, and validated.

- **Built in, no key:** BLS CPI-U connector for U.S. inflation/CPI claims. It retrieves structured primary data directly from the BLS public API.
- **Recommended for broad production coverage:** set `CLARITY_BRAVE_SEARCH_API_KEY`.
- **Alternatives:** `CLARITY_SERPAPI_KEY`, or both `CLARITY_GOOGLE_API_KEY` and `CLARITY_GOOGLE_CSE_ID`.
- **Fallback only:** DuckDuckGo Lite/Bing RSS. These may be rate-limited or low precision and must not be relied on for production verification.

```bash
cd backend
cp .env.example .env      # configure search backends
uvicorn app.main:app --reload --port 8080
```

Or with Docker (from the repo root):

```bash
docker build -t clarity-backend ./backend
docker run --env-file backend/.env -p 8080:8080 clarity-backend
```

`backend/.dockerignore` excludes `.env`, so credentials are passed at runtime with `--env-file` and are never baked into the image.

**Endpoints:**
- `POST /api/check` — Check a claim. Request: `{"claim": "..."}` → Response with citations and assessment
- `GET /api/health` — Health check

**Search backends** — see [Retrieval providers](#retrieval-providers) above. `CLARITY_DDG_ENABLED` toggles the DuckDuckGo fallback (enabled by default).

**Evidence pipeline:** Search → Fetch pages → Extract relevant passages → Classify source tier → Deduplicate and rank → the configured LLM classifies passages and synthesizes a constrained verdict

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

### API security

- **Optional bearer token:** set `CLARITY_API_TOKEN` on the backend, then paste the same value into the extension's Settings **Backend token** field. When configured, `/api/check` requires `Authorization: Bearer <token>` and returns 401 otherwise.
- **Rate limits:** `CLARITY_RATE_LIMIT` requests per minute (default 10) and `CLARITY_RATE_LIMIT_HOUR` requests per hour (default 50), per client IP; exceeding them returns 429.
- **Response cache:** `CLARITY_CACHE_TTL` seconds (default 1800) controls how long checked-claim responses are cached.
- **No baked secrets:** `backend/.dockerignore` excludes `.env`; pass it at runtime with `docker run --env-file backend/.env`.
- **Network egress guard with a known residual:** fetches are allowlisted to curated registry domains and every redirect hop is re-validated against the same rules. DNS rebinding between that validation and httpx's own resolution is a known TOCTOU residual — run the backend on a trusted network and add transport-level IP pinning before exposing it to untrusted networks.

## Architecture

```
src/
├── shared/protocol.ts       — Types, verdict contracts, evidence-before-verdict logic
├── background/worker.ts     — Service worker: verification pipeline, caching, source ranking
├── content/extractor.ts     — Page text extraction (articles, YouTube captions)
└── panel/                   — Side panel UI (HTML + controller)
```

Key design decisions:

- **Privacy by design:** Text is only extracted when you click "Check claims" — never automatically. No data leaves without your action. No cookies, full DOM, or browsing history is ever collected.
- **No bundled secrets:** The extension ships with no API keys or service credentials. The backend URL and optional API token are entered in Settings and stored locally.
- **Evidence before verdict:** The protocol contract enforces that a verdict requires fetched-and-validated source citations. The LLM can't fabricate a conclusion.
- **No remote code:** All logic is bundled. No eval, no remote scripts, no CSP violations.

## Quick start

### Install from source

```bash
git clone https://github.com/boanntech/clarity
cd clarity
npm install
npm test          # 16 tests — runs in ~175ms
npm run build     # → dist/

# Backend tests:
cd backend
pip install -r requirements-dev.txt
python3 -m pytest -q    # 72 tests
```

Then load in Chrome:
1. Go to `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `dist/` directory

### Load the side panel

Click the Clarity icon in the toolbar to open the side panel.

## Status

**Phase 1** ✅ — Extension UI, text extraction, verdict protocol, build pipeline
**Phase 2** ✅ — Backend API (FastAPI), evidence retrieval (DuckDuckGo + Google CSE), source tiering, verdict calculation, Docker
**Phase 3** 🏗️ — Cross-platform support (Twitter, Reddit, Facebook), claim history, user settings
**Phase 4** — Audio transcription, multi-language, breaking-news monitoring

## Contributing

Contributions are welcome. Open an issue or PR. Please keep the evidence-before-verdict principle sacred — no verdict without a sourced citation.

## License

MIT — BoannTech, Dundalk, Co. Louth.