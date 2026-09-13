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
    <img src="https://img.shields.io/badge/tests-182%20passing-green.svg" alt="Tests" />
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

**Locked dependencies:** `requirements.in` and `requirements-dev.in` hold top-level dependencies; `requirements.txt` and `requirements-dev.txt` are hash-pinned locks generated with pip-tools. After editing a `.in` file, regenerate under Python 3.12 (the lock target; pip-compile resolves against the interpreter it runs on, and current pip-tools has no `--python-version` flag):

```bash
cd backend
python3.12 -m piptools compile --generate-hashes --output-file requirements.txt requirements.in
python3.12 -m piptools compile --generate-hashes --allow-unsafe --output-file requirements-dev.txt requirements-dev.in
```

`--allow-unsafe` is needed for the dev lock because pip-tools otherwise leaves `pip` and `setuptools` unpinned, which breaks `--require-hashes` installs. Docker and CI install only the lock files with `--require-hashes`, and CI runs `pip-audit` and `npm audit`.

**Endpoints:**
- `POST /api/check` — Check a claim. Request: `{"claim": "..."}` → Response with citations and assessment
- `POST /api/check/batch` — Check 1–10 claims in one request. Request: `{"claims": ["...", ...]}` → `{"results": [...]}` in input order; charges one rate-limit unit per uncached claim
- `GET /api/health` — Health check
- `GET /api/metrics` — Per-process operational counters (see [Operational metrics](#operational-metrics) below)

**Search backends** — see [Retrieval providers](#retrieval-providers) above. `CLARITY_DDG_ENABLED` toggles the DuckDuckGo fallback (enabled by default).

**Evidence pipeline:** Normalize claim → LLM-generated search queries → Search each query → Merge and deduplicate candidate URLs *before* fetching (a URL surfaced by more than one generated query is fetched and classified once, not once per query) → Fetch pages → Extract relevant passages → Classify source tier → Deduplicate and rank → the configured LLM classifies passages and synthesizes a constrained verdict. The "misleading" verdict's 2-independent-sources rule also collapses citations under common ownership (e.g. bbc.co.uk/bbc.com, or PolitiFact/its owner the Poynter Institute) so they can't satisfy the requirement together.

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
# Example: OpenAI
CLARITY_LLM_PROVIDER=openai
CLARITY_LLM_API_KEY=sk-...
CLARITY_LLM_MODEL=gpt-4o

# Example: DeepSeek
CLARITY_LLM_PROVIDER=deepseek
CLARITY_LLM_API_KEY=sk-...
CLARITY_LLM_MODEL=deepseek-chat

# Example: Groq
CLARITY_LLM_PROVIDER=groq
CLARITY_LLM_API_KEY=gsk_...
CLARITY_LLM_MODEL=llama-3.3-70b-versatile

# Example: OpenRouter with attribution headers
CLARITY_LLM_PROVIDER=openrouter
CLARITY_LLM_API_KEY=sk-or-...
CLARITY_LLM_MODEL=deepseek/deepseek-chat
CLARITY_LLM_EXTRA_HEADERS={"HTTP-Referer":"https://github.com/boanntech/clarity"}

# Example: local Ollama
CLARITY_LLM_PROVIDER=ollama
CLARITY_LLM_MODEL=llama3.1

# Example: Bifrost gateway (preset base URL http://localhost:8081/v1;
# set CLARITY_LLM_BASE_URL to point at a remote host)
CLARITY_LLM_PROVIDER=bifrost
CLARITY_LLM_API_KEY=your-bifrost-key
CLARITY_LLM_MODEL=deepseek-pro
```

Models that reject `max_tokens` (some newer OpenAI models) can use `CLARITY_LLM_MAX_TOKENS_PARAM=max_completion_tokens`. If a provider rejects JSON mode, Clarity retries with a standard chat completion and ultimately falls back to the deterministic evaluator. With no model configured, evaluations are **Unverified** — Clarity never fabricates support.

**Migration from Bifrost-only config:** rename `CLARITY_BIFROST_API_KEY`/`CLARITY_BIFROST_BASE_URL`/`CLARITY_BIFROST_MODEL` to `CLARITY_LLM_API_KEY`/`CLARITY_LLM_BASE_URL`/`CLARITY_LLM_MODEL`, and set `CLARITY_LLM_PROVIDER=bifrost` (or `custom` with the same base URL).

### API security

- **Optional bearer token:** set `CLARITY_API_TOKEN` on the backend, then paste the same value into the extension's Settings **Backend token** field. When configured, `/api/check` and `/api/check/batch` require `Authorization: Bearer <token>` and return 401 otherwise.
- **Rate limits:** `CLARITY_RATE_LIMIT` requests per minute (default 60) and `CLARITY_RATE_LIMIT_HOUR` requests per hour (default 500), per client IP; exceeding them returns 429. Cache hits are free — only uncached claims consume units, so a first scan of a 10-claim page costs 10 units and the defaults are sized for it. The extension checks uncached claims in `POST /api/check/batch` requests of at most 10 claims each (a scan of up to 20 claims makes at most two requests, 120 s budget per batch); a batch charges one unit per uncached claim and returns 429 if it would exceed the configured limits, so no per-claim request fan-out and no partial charging.
- **Behind a reverse proxy:** by default the client IP used for rate limiting is the direct socket peer, so a proxy in front of Clarity would make every client share one bucket (the proxy's IP). Set `CLARITY_TRUSTED_PROXY_HOPS` to the number of trusted proxies in front of Clarity (usually `1`) to read the real client IP from `X-Forwarded-For` instead. Only raise this for a header your own infrastructure sets — trusting more hops than actually exist lets a client spoof its rate-limit identity.
- **Deploy extension and backend together:** the extension now uses `POST /api/check/batch`. A new extension pointed at a backend that predates the batch route will report an HTTP 404 error per claim and mark it Unverified — it never fabricates a verdict. Upgrade both sides together.
- **Response cache:** `CLARITY_CACHE_TTL` seconds (default 1800) controls how long checked-claim responses are cached.
- **Shared cache/rate-limit backend for multiple workers or replicas:** by default the cache and rate limiter are in-memory and per-process — fine for one worker, but each additional worker or replica gets its own cache (more misses) and its own rate-limit counters (the effective limit multiplies by worker count). Set `CLARITY_REDIS_URL` (e.g. `redis://localhost:6379/0`) and `pip install redis` to share both across every process instead. Optional and off by default; if the package isn't installed or the client can't be constructed, Clarity logs a warning and falls back to the in-memory backends rather than failing to start. A Redis outage fails the rate limiter open (not closed) and the cache to a miss — availability over strict enforcement.
- **No baked secrets:** `backend/.dockerignore` excludes `.env`; pass it at runtime with `docker run --env-file backend/.env`.
- **Network egress guard with a known residual:** fetches are allowlisted to curated registry domains and every redirect hop is re-validated against the same rules. DNS rebinding between that validation and httpx's own resolution is a known TOCTOU residual — run the backend on a trusted network and add transport-level IP pinning before exposing it to untrusted networks.

### Operational metrics

`GET /api/metrics` reports per-process counters: cache hit/miss, verdict distribution, rate-limit rejections, and LLM call counts + average latency by role (`normalize`, `classify`, `verdict`). Unauthenticated by default, matching `/api/health`; like the in-memory cache and rate limiter, counters are per-process and reset on restart — scrape each replica separately for a fleet-wide view. Firewall it separately from `/api/health` if you'd rather not expose call-volume counts publicly.

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
npm test          # 20 tests — extension, runs in ~190ms
npm run build     # → dist/

# Backend tests:
cd backend
pip install -r requirements-dev.txt
python3 -m pytest -q    # 162 tests — backend
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