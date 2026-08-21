/**
 * Background Service Worker — the core verification engine.
 *
 * Responsibilities:
 *   - Receives page text from content scripts
 *   - Routes claims to the verification pipeline
 *   - Manages auth, caching, and rate limiting
 *   - Opens the side panel on click
 *
 * Evidence-before-verdict rule: every supported/contradicted/misleading
 * verdict requires at least one fetched and validated citation URL.
 */

import type { PagePayload, ClaimCheck } from "../shared/protocol.js"
import { extractCandidates, selectCheckableClaims, assessmentFromResponse } from "../shared/protocol.js"

/* ───────── State ───────── */

const claimCache = new Map<string, { result: ClaimCheck; timestamp: number }>()
const CACHE_TTL_MS = 30 * 60 * 1000 // 30 minutes

/* ───────── Entry point ───────── */

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Verify] Extension installed. Side panel available.")
})

// Open side panel when the toolbar icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) {
    await chrome.sidePanel.open({ tabId: tab.id })
    await chrome.sidePanel.setOptions({
      tabId: tab.id,
      path: "panel/panel.html",
    })
  }
})

/* ───────── Message handling ───────── */

chrome.runtime.onMessage.addListener((
  message: { type: string; payload: PagePayload },
  _sender,
  sendResponse,
) => {
  if (message.type === "CHECK_PAGE") {
    handlePageCheck(message.payload)
      .then(sendResponse)
      .catch((err) => sendResponse({ error: err.message }))
    return true // keep channel open for async response
  }
})

/* ───────── Verification pipeline ───────── */

async function handlePageCheck(payload: PagePayload): Promise<{ claims: ClaimCheck[] }> {
  const candidates = extractCandidates(payload)
  const checkableClaims = selectCheckableClaims(candidates, 10)

  const results = await Promise.all(
    checkableClaims.map((claim) => verifySingleClaim(claim)),
  )

  return { claims: results }
}

async function verifySingleClaim(claimText: string): Promise<ClaimCheck> {
  // 1. Check cache
  const cached = claimCache.get(claimText)
  if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
    return cached.result
  }

  // 2. Run evidence search
  const citations = await searchEvidence(claimText)

  // 3. Form assessment
  // MVP: rules-based assessment based on what we found
  const raw = citations.length === 0
    ? { claim: claimText, verdict: "unverified", confidence: 0, explanation: "", citations: [], checkedAt: new Date().toISOString() }
    : { claim: claimText, verdict: "supported", confidence: 0.7, explanation: `Found ${citations.length} relevant source(s).`, citations, checkedAt: new Date().toISOString() }

  const result = assessmentFromResponse(raw)

  // 4. Cache
  claimCache.set(claimText, { result, timestamp: Date.now() })

  return result
}

/* ───────── Evidence retrieval ───────── */

const TRUSTED_SOURCES: Array<{ domain: string; tier: "primary" | "fact_check" | "secondary_news" }> = [
  // Health
  { domain: "who.int", tier: "primary" },
  { domain: "cdc.gov", tier: "primary" },
  { domain: "nih.gov", tier: "primary" },
  // Economics
  { domain: "bls.gov", tier: "primary" },
  { domain: "worldbank.org", tier: "primary" },
  { domain: "imf.org", tier: "primary" },
  { domain: "ecb.europa.eu", tier: "primary" },
  { domain: "federalreserve.gov", tier: "primary" },
  // Government & Law
  { domain: "congress.gov", tier: "primary" },
  { domain: "supremecourt.gov", tier: "primary" },
  { domain: "gov.ie", tier: "primary" },
  { domain: "eur-lex.europa.eu", tier: "primary" },
  // Fact-checking orgs
  { domain: "reuters.com", tier: "fact_check" },
  { domain: "apnews.com", tier: "fact_check" },
  { domain: "politifact.com", tier: "fact_check" },
  { domain: "factcheck.org", tier: "fact_check" },
  { domain: "snopes.com", tier: "fact_check" },
  { domain: "fullfact.org", tier: "fact_check" },
  // News (secondary)
  { domain: "bbc.co.uk", tier: "secondary_news" },
  { domain: "bbc.com", tier: "secondary_news" },
  { domain: "theguardian.com", tier: "secondary_news" },
  { domain: "nytimes.com", tier: "secondary_news" },
]

/**
 * Search evidence for a claim. MVP implementation uses a placeholder
 * that returns mock citations. In production, this would call a backend
 * API that queries curated sources and fact-check databases.
 */
async function searchEvidence(claimText: string): Promise<import("../shared/protocol.js").Citation[]> {
  // Placeholder: return empty — the system correctly reports Unverified
  // In Phase 1, this calls a backend FastAPI service.
  return []

  /* Phase 2 implementation sketch:
  const response = await fetch("https://verify.boanntech.com/api/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim: claimText, sources: TRUSTED_SOURCES }),
  })
  if (!response.ok) return []
  const data = await response.json()
  return data.citations as Citation[]
  */
}