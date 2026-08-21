# Clarity — Evidence for what you read.

**Clarity** is a Chrome extension that helps you navigate the information you encounter online. When someone makes a factual claim — in an article, a YouTube video, or on social media — Clarity finds real evidence from authoritative sources and shows you the full picture.

It's not a "truth detector." Claims are complicated. Some are supported by evidence. Some are contradicted. Many are misleading because they leave out context. And plenty aren't checkable at all — opinions, predictions, value statements.

Clarity's job is to surface the evidence so **you** can make up your own mind.

## How it works

1. Open any article or YouTube video
2. Open the Clarity side panel (click the icon)
3. Click **Check claims on this page**
4. Clarity scans the page text, extracts factual claims, and retrieves evidence
5. Each claim gets a transparent assessment with cited sources

## Verdicts

| Verdict | Meaning |
|---|---|
| Supported | The available evidence backs this claim |
| Contradicted | The available evidence contradicts this claim |
| Misleading | The claim omits important context (requires 2+ independent sources) |
| Unverified | No verified evidence could be found — we don't know |
| Not checkable | This is an opinion, prediction, or value statement |

> **No citations? No verdict.** Clarity will never show Supported, Contradicted, or Misleading without at least one valid, cited source. Without evidence, the answer is always **Unverified** — and that's honest.

## Source quality

Sources are ranked by authority:

1. **Primary** — government statistics, WHO, CDC, legislation, central banks, court filings, research publications
2. **Fact check** — Reuters, AP, PolitiFact, Snopes, FactCheck.org, Full Fact
3. **Secondary news** — BBC, Guardian, NYT (used when primary is unavailable)

## Architecture

```
Clarity/
├── src/
│   ├── shared/protocol.ts       — Types, verdict contracts, evidence-before-verdict
│   ├── background/worker.ts     — Service worker: verification pipeline, caching
│   ├── content/extractor.ts     — Page text extraction (articles, YouTube captions)
│   └── panel/                   — Side panel UI (HTML + controller)
├── scripts/build.mjs            — Compiles TS + copies static assets
├── manifest.json                — MV3 manifest
└── vitest.config.ts
```

## Running

```bash
npm install
npm test               # 8 tests — runs in under 200ms
npm run build          # → dist/
```

Load `dist/` as an unpacked extension at `chrome://extensions`.

## Status

MVP Phase 1. Evidence search currently returns `[]` — every claim correctly shows **Unverified**. Phase 2 adds a backend API that queries curated sources and fact-check databases.

## Fighting misinformation

Misinformation thrives when claims go unchecked and context is stripped away. Clarity fights it not by telling you what to believe, but by showing you where claims come from, what the evidence actually says, and where the uncertainty lies. An informed reader is the best defence against misinformation.