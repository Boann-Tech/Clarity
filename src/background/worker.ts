/**
 * Background Service Worker — the core verification engine.
 *
 * Responsibilities:
 *   - Receives page text from content scripts
 *   - Routes claims to the verification pipeline
 *   - Calls the Clarity backend API for evidence retrieval
 *   - Caches results in memory
 *   - Opens the side panel on click
 *
 * Evidence-before-verdict rule: every supported/contradicted/misleading
 * verdict requires at least one fetched and validated citation URL.
 */

import type { PagePayload, ClaimCheck, Citation } from "../shared/protocol.js"
import { extractCandidates, selectCheckableClaims, assessmentFromResponse } from "../shared/protocol.js"

/* ───────── Configuration ───────── */

const DEFAULT_BACKEND_URL = "http://localhost:8080"
const STORAGE_KEY_BACKEND_URL = "clarity_backend_url"

type BackendCheckResponse = {
  claim?: string
  assessment?: { verdict?: string; confidence?: number; explanation?: string }
  citations?: Array<Record<string, unknown>>
  checked_at?: string
}

async function getBackendUrl(): Promise<string> {
  try {
    const result = await chrome.storage.local.get(STORAGE_KEY_BACKEND_URL)
    return (result[STORAGE_KEY_BACKEND_URL] as string) || DEFAULT_BACKEND_URL
  } catch {
    return DEFAULT_BACKEND_URL
  }
}

/* ───────── State ───────── */

const claimCache = new Map<string, { result: ClaimCheck; timestamp: number }>()
const CACHE_TTL_MS = 30 * 60 * 1000 // 30 minutes

/* ───────── Entry point ───────── */

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Clarity] Extension installed. Side panel available.")
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
  message: { type: string; payload?: PagePayload; data?: Record<string, unknown> },
  _sender,
  sendResponse,
) => {
  if (message.type === "CHECK_PAGE" && message.payload) {
    handlePageCheck(message.payload)
      .then(sendResponse)
      .catch((err) => sendResponse({ error: err.message }))
    return true
  }
  if (message.type === "GET_PAGE_TEXT_FOR_TAB" && typeof message.data?.tabId === "number") {
    getPagePayloadForTab(message.data.tabId)
      .then(sendResponse)
      .catch((err) => sendResponse({ error: err instanceof Error ? err.message : String(err) }))
    return true
  }
  if (message.type === "GET_BACKEND_URL") {
    getBackendUrl().then(sendResponse)
    return true
  }
})

/* ───────── Page extraction bridge ───────── */

async function getPagePayloadForTab(tabId: number): Promise<PagePayload> {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "GET_PAGE_TEXT" }) as PagePayload
  } catch {
    // Content scripts are not retroactively injected into a page opened before
    // install/reload. Inject only after the user's explicit Check action;
    // activeTab grants temporary access without broad host permissions.
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content/extractor.js"],
    })
    return await chrome.tabs.sendMessage(tabId, { type: "GET_PAGE_TEXT" }) as PagePayload
  }
}

/* ───────── Verification pipeline ───────── */

async function handlePageCheck(payload: PagePayload): Promise<{ claims: ClaimCheck[]; error?: string }> {
  const candidates = extractCandidates(payload)
  const checkableClaims = selectCheckableClaims(candidates, 10)

  if (checkableClaims.length === 0) {
    return { claims: [] }
  }

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

  // 2. Run evidence search via backend
  const backendResult = await searchEvidence(claimText)

  // 3. Preserve the backend's evidence-guarded assessment verbatim. The
  // extension may add UI safeguards, but must never rewrite a contradiction
  // into "supported" merely because citations exist.
  let raw: { claim: string; verdict: string; confidence: number; explanation: string; citations: Citation[]; checkedAt: string }

  if (!backendResult) {
    raw = { claim: claimText, verdict: "unverified", confidence: 0, explanation: "Offline — the Clarity backend could not be reached. Check your connection or backend URL in Settings.", citations: [], checkedAt: new Date().toISOString() }
  } else {
    raw = {
      claim: String(backendResult.claim ?? claimText),
      verdict: String(backendResult.assessment?.verdict ?? "unverified"),
      confidence: Number(backendResult.assessment?.confidence ?? 0),
      explanation: String(backendResult.assessment?.explanation ?? "No validated citations could be retrieved for this claim."),
      citations: mapBackendCitations(backendResult.citations ?? []),
      checkedAt: String(backendResult.checked_at ?? new Date().toISOString()),
    }
  }

  const result = assessmentFromResponse(raw)

  // 4. Cache
  claimCache.set(claimText, { result, timestamp: Date.now() })

  return result
}

/* ───────── Evidence retrieval via backend API ───────── */

async function searchEvidence(claimText: string): Promise<BackendCheckResponse | null> {
  const backendUrl = await getBackendUrl()

  try {
    const response = await fetch(`${backendUrl}/api/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim: claimText }),
      signal: AbortSignal.timeout(15000), // 15s timeout
    })

    if (!response.ok) return null
    return await response.json() as BackendCheckResponse
  } catch {
    return null
  }
}

function mapBackendCitations(backendCitations: Array<Record<string, unknown>>): Citation[] {
  return backendCitations
    .filter((c) => c.url && typeof c.url === "string" && c.url.startsWith("http"))
    .map((c) => ({
      title: String(c.title ?? "Untitled"),
      publisher: String(c.publisher ?? c.tier ?? "unknown"),
      url: String(c.url),
      publishedDate: String(c.published_date ?? c.publishedDate ?? ""),
      snippet: String(c.snippet ?? "").slice(0, 800),
      sourceTier: mapTier(String(c.tier ?? "secondary_news")),
    }))
}

function mapTier(tier: string): Citation["sourceTier"] {
  if (tier === "primary") return "primary"
  if (tier === "fact_check") return "fact_check"
  return "secondary_news"
}

/* ───────── Settings helpers (shared with panel) ───────── */

export async function saveBackendUrl(url: string): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY_BACKEND_URL]: url })
}

export async function testBackendConnection(url: string): Promise<boolean> {
  try {
    const response = await fetch(`${url}/api/health`, {
      signal: AbortSignal.timeout(5000),
    })
    return response.ok
  } catch {
    return false
  }
}