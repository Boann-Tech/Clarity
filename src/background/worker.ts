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

import type { PagePayload, ClaimCheck, Citation, AppSettings } from "../shared/protocol.js"
import {
  DEFAULT_SETTINGS,
  assessmentFromResponse,
  extractCandidates,
  fetchBatchAssessments,
  mapTier,
  resolveSettings,
  selectCheckableClaims,
} from "../shared/protocol.js"

/* ───────── Configuration ───────── */

const SETTINGS_KEY = "clarity_settings"

async function getSettings(): Promise<AppSettings> {
  try {
    const result = await chrome.storage.local.get(SETTINGS_KEY)
    return resolveSettings(result[SETTINGS_KEY])
  } catch {
    return DEFAULT_SETTINGS
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
  message: { type: string; payload?: PagePayload; data?: Record<string, unknown>; settings?: { maxClaims?: number } },
  _sender,
  sendResponse,
) => {
  if (message.type === "CHECK_PAGE" && message.payload) {
    handlePageCheck(message.payload, message.settings?.maxClaims)
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

async function handlePageCheck(payload: PagePayload, maxClaims = 10): Promise<{ claims: ClaimCheck[]; error?: string }> {
  const candidates = extractCandidates(payload)
  const limit = Math.min(Math.max(maxClaims, 1), 20)
  const checkableClaims = selectCheckableClaims(candidates, limit)

  if (checkableClaims.length === 0) {
    return { claims: [] }
  }

  const resolved = new Map<string, ClaimCheck>()
  const pending: string[] = []
  for (const claim of checkableClaims) {
    const cached = claimCache.get(claim)
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      resolved.set(claim, cached.result)
    } else {
      pending.push(claim)
    }
  }

  if (pending.length > 0) {
    const settings = await getSettings()
    const outcome = await fetchBatchAssessments(pending, settings)
    if (outcome && "results" in outcome) {
      pending.forEach((claim, index) => {
        const raw = outcome.results[index]
        const result = assessmentFromResponse({
          claim: String(raw?.claim ?? claim),
          verdict: String(raw?.assessment?.verdict ?? "unverified"),
          confidence: Number(raw?.assessment?.confidence ?? 0),
          explanation: String(raw?.assessment?.explanation ?? "No validated citations could be retrieved for this claim."),
          citations: mapBackendCitations(raw?.citations ?? []),
          checkedAt: String(raw?.checked_at ?? new Date().toISOString()),
        })
        claimCache.set(claim, { result, timestamp: Date.now() })
        resolved.set(claim, result)
      })
    } else {
      const explanation = outcome && "error" in outcome
        ? `The Clarity backend rejected the request (${outcome.error}). Check the backend URL/token in Settings.`
        : "Offline — the Clarity backend could not be reached. Check your connection or backend URL in Settings."
      for (const claim of pending) {
        const result = assessmentFromResponse({
          claim,
          verdict: "unverified",
          confidence: 0,
          explanation,
          citations: [],
          checkedAt: new Date().toISOString(),
        })
        claimCache.set(claim, { result, timestamp: Date.now() })
        resolved.set(claim, result)
      }
    }
  }

  return { claims: checkableClaims.map((claim) => resolved.get(claim)!) }
}

/* ───────── Evidence retrieval via backend API ───────── */

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