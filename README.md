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
    <img src="https://img.shields.io/badge/tests-8%20passing-green.svg" alt="Tests" />
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
- **No secrets in the extension:** No API keys, no tokens, no service credentials. The evidence search backend (Phase 2) owns all secrets.
- **Evidence before verdict:** The protocol contract enforces that a verdict requires fetched-and-validated source citations. The LLM can't fabricate a conclusion.
- **No remote code:** All logic is bundled. No eval, no remote scripts, no CSP violations.

## Quick start

### Install from source

```bash
git clone https://github.com/boanntech/clarity
cd clarity
npm install
npm test          # 8 tests — runs in ~120ms
npm run build     # → dist/
```

Then load in Chrome:
1. Go to `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `dist/` directory

### Load the side panel

Click the Clarity icon in the toolbar, or use the keyboard shortcut (default configurable at `chrome://extensions/shortcuts`).

## Status

**MVP Phase 1 completed.** The extension UI, extraction pipeline, verdict contract, and safety architecture are fully functional. The evidence search (`searchEvidence()` in worker.ts) currently returns an empty array — every claim correctly shows **Unverified**. Phase 2 adds a backend API that queries curated sources and fact-check databases.

## Roadmap

- **Phase 1** ✅ — Extension UI, text extraction, verdict protocol, build pipeline
- **Phase 2** 🏗️ — Backend API (FastAPI), curated source index, evidence retrieval, citation validation
- **Phase 3** — Cross-platform support (Twitter, Reddit, Facebook web), claim history
- **Phase 4** — Audio transcription for YouTube videos without captions, multi-language

## Contributing

Contributions are welcome. Open an issue or PR. Please keep the evidence-before-verdict principle sacred — no verdict without a sourced citation.

## License

MIT — BoannTech, Dundalk, Co. Louth.