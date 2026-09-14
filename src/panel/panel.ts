/**
 * Side Panel — Clarity claim assessment results in a compact,
 * evidence-first card UI with tabs for Check, History, and Settings.
 */

import type { AppSettings, ClaimCheck } from "../shared/protocol.js"
import {
  DEFAULT_SETTINGS,
  assessPageUrl,
  mergeHistory,
  normalizeBackendUrl,
  resolveSettings,
  testBackendConnection,
} from "../shared/protocol.js"

/* ───────── DOM refs ───────── */

const checkBtn = document.getElementById("checkBtn") as HTMLButtonElement
const resultsEl = document.getElementById("results") as HTMLDivElement
const emptyState = document.getElementById("emptyState") as HTMLDivElement
const statusBadge = document.getElementById("statusBadge") as HTMLSpanElement
const progressBar = document.getElementById("progressBar") as HTMLDivElement
const progressContainer = document.getElementById("progressContainer") as HTMLDivElement

// Tab refs
const tabCheck = document.getElementById("tabCheck") as HTMLButtonElement
const tabHistory = document.getElementById("tabHistory") as HTMLButtonElement
const tabSettings = document.getElementById("tabSettings") as HTMLButtonElement
const panelCheck = document.getElementById("panelCheck") as HTMLDivElement
const panelHistory = document.getElementById("panelHistory") as HTMLDivElement
const panelSettings = document.getElementById("panelSettings") as HTMLDivElement

// Settings refs
const settingsBackendUrl = document.getElementById("settingsBackendUrl") as HTMLInputElement
const settingsBackendToken = document.getElementById("settingsBackendToken") as HTMLInputElement
const settingsMaxClaims = document.getElementById("settingsMaxClaims") as HTMLInputElement
const settingsStatus = document.getElementById("settingsStatus") as HTMLSpanElement
const saveSettingsBtn = document.getElementById("saveSettingsBtn") as HTMLButtonElement
const resetSettingsBtn = document.getElementById("resetSettingsBtn") as HTMLButtonElement
const testConnectionBtn = document.getElementById("testConnectionBtn") as HTMLButtonElement
const testConnectionStatus = document.getElementById("testConnectionStatus") as HTMLSpanElement

// History refs
const historyList = document.getElementById("historyList") as HTMLDivElement
const clearHistoryBtn = document.getElementById("clearHistoryBtn") as HTMLButtonElement

/* ───────── Constants ───────── */

const HISTORY_KEY = "clarity_claim_history"
const SETTINGS_KEY = "clarity_settings"
const PENDING_SELECTION_KEY = "clarity_pending_selection"
const MAX_HISTORY = 50
const PENDING_SELECTION_MAX_AGE_MS = 15_000

interface HistoryEntry {
  claim: string
  verdict: string
  confidence: number
  explanation: string
  checkedAt: string
  url: string
}

interface PendingSelection {
  text: string
  url: string
  ts: number
}

/* ───────── Tab switching ───────── */

function showTab(tab: "check" | "history" | "settings") {
  const tabs = [tabCheck, tabHistory, tabSettings] as const
  const panels = [panelCheck, panelHistory, panelSettings] as const
  tabs.forEach((t) => t?.classList.remove("tab-active"))
  panels.forEach((p) => { if (p) p.style.display = "none" })

  if (tab === "check") {
    tabCheck?.classList.add("tab-active")
    if (panelCheck) panelCheck.style.display = "block"
  } else if (tab === "history") {
    tabHistory?.classList.add("tab-active")
    if (panelHistory) panelHistory.style.display = "block"
    renderHistory()
  } else {
    tabSettings?.classList.add("tab-active")
    if (panelSettings) panelSettings.style.display = "block"
    loadSettings()
  }
}

tabCheck.addEventListener("click", () => showTab("check"))
tabHistory.addEventListener("click", () => showTab("history"))
tabSettings.addEventListener("click", () => showTab("settings"))

/* ───────── Helpers ───────── */

function setStatus(text: string, active = false) {
  statusBadge.textContent = text
  statusBadge.className = `status-badge${active ? " active" : ""}`
}

function setLoading(loading: boolean) {
  checkBtn.disabled = loading
  checkBtn.textContent = loading ? "Checking..." : "Check claims on this page"
  progressContainer.style.display = loading ? "block" : "none"
}

function setProgress(pct: number) {
  progressBar.style.width = `${pct}%`
}

/* ───────── Settings ───────── */

async function getSettings(): Promise<AppSettings> {
  try {
    const result = await chrome.storage.local.get(SETTINGS_KEY)
    return resolveSettings(result[SETTINGS_KEY])
  } catch {
    return DEFAULT_SETTINGS
  }
}

async function loadSettings() {
  const s = await getSettings()
  settingsBackendUrl.value = s.backendUrl
  settingsBackendToken.value = s.backendToken
  settingsMaxClaims.value = String(s.maxClaims)
}

async function saveSettings() {
  const settings: AppSettings = {
    backendUrl: normalizeBackendUrl(settingsBackendUrl.value),
    backendToken: settingsBackendToken.value.trim(),
    maxClaims: Math.min(Math.max(parseInt(settingsMaxClaims.value) || DEFAULT_SETTINGS.maxClaims, 1), 20),
  }
  await chrome.storage.local.set({ [SETTINGS_KEY]: settings })
  settingsBackendUrl.value = settings.backendUrl
  settingsStatus.textContent = "Saved"
  setTimeout(() => { settingsStatus.textContent = "" }, 2000)
}

async function resetSettings() {
  await chrome.storage.local.set({ [SETTINGS_KEY]: DEFAULT_SETTINGS })
  settingsBackendUrl.value = DEFAULT_SETTINGS.backendUrl
  settingsBackendToken.value = DEFAULT_SETTINGS.backendToken
  settingsMaxClaims.value = String(DEFAULT_SETTINGS.maxClaims)
  settingsStatus.textContent = "Defaults restored"
  setTimeout(() => { settingsStatus.textContent = "" }, 2000)
}

async function testConnection() {
  testConnectionStatus.textContent = "Testing…"
  const ok = await testBackendConnection(settingsBackendUrl.value, settingsBackendToken.value.trim())
  testConnectionStatus.textContent = ok ? "Connected" : "Could not reach backend"
  setTimeout(() => { testConnectionStatus.textContent = "" }, 3000)
}

saveSettingsBtn.addEventListener("click", saveSettings)
resetSettingsBtn.addEventListener("click", resetSettings)
testConnectionBtn.addEventListener("click", testConnection)

/* ───────── History ───────── */

async function getHistory(): Promise<HistoryEntry[]> {
  try {
    const result = await chrome.storage.local.get(HISTORY_KEY)
    return (result[HISTORY_KEY] as HistoryEntry[]) ?? []
  } catch {
    return []
  }
}

async function clearHistory() {
  await chrome.storage.local.set({ [HISTORY_KEY]: [] })
  historyList.innerHTML = "<p style='color:var(--text-muted);text-align:center;padding:16px;'>No checks yet.</p>"
}

clearHistoryBtn.addEventListener("click", clearHistory)

function renderHistory() {
  getHistory().then((history) => {
    if (history.length === 0) {
      historyList.innerHTML = "<p style='color:var(--text-muted);text-align:center;padding:16px;'>No checks yet.</p>"
      return
    }
    historyList.innerHTML = ""
    for (const h of history) {
      const card = document.createElement("div")
      card.className = "history-card"
      card.innerHTML = `
        <div class="history-claim">"${escapeHtml(h.claim.slice(0, 80))}${h.claim.length > 80 ? "…" : ""}"</div>
        <div class="history-meta">
          <span class="verdict-label ${verdictClass(h.verdict)}">${verdictLabel(h.verdict)}</span>
          <span class="history-date">${new Date(h.checkedAt).toLocaleDateString()}</span>
        </div>
      `
      historyList.appendChild(card)
    }
  })
}

/* ───────── Verdict styling ───────── */

function verdictClass(verdict: string): string {
  const map: Record<string, string> = {
    supported: "verdict-supported",
    contradicted: "verdict-contradicted",
    misleading: "verdict-misleading",
    unverified: "verdict-unverified",
  }
  return map[verdict] ?? "verdict-unverified"
}

function verdictLabel(verdict: string): string {
  const map: Record<string, string> = {
    supported: "Supported",
    contradicted: "Contradicted",
    misleading: "Misleading",
    unverified: "Unverified",
    not_checkable: "Not checkable",
  }
  return map[verdict] ?? verdict
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return "var(--green)"
  if (confidence >= 0.4) return "var(--amber)"
  return "var(--red)"
}

function escapeHtml(s: string): string {
  const div = document.createElement("div")
  div.textContent = s
  return div.innerHTML
}

/* ───────── Render results ───────── */

function buildClaimCard(c: ClaimCheck): HTMLDivElement {
  const card = document.createElement("div")
  card.className = "claim-card"

  // Claim quote
  const quote = document.createElement("div")
  quote.className = "claim-quote"
  quote.textContent = `"${c.claim}"`
  card.appendChild(quote)

  // Verdict row
  const verdictRow = document.createElement("div")
  verdictRow.className = "verdict-row"
  const vLabel = document.createElement("span")
  vLabel.className = `verdict-label ${verdictClass(c.verdict)}`
  vLabel.textContent = verdictLabel(c.verdict)
  verdictRow.appendChild(vLabel)

  // Confidence score
  const confScore = document.createElement("span")
  confScore.style.cssText = "font-size:11px;color:var(--text-muted);margin-left:auto;"
  confScore.textContent = `${Math.round(c.confidence * 100)}% confidence`
  verdictRow.appendChild(confScore)

  card.appendChild(verdictRow)

  // Confidence bar
  if (c.confidence > 0) {
    const bar = document.createElement("div")
    bar.className = "confidence-bar"
    const fill = document.createElement("div")
    fill.className = "confidence-fill"
    fill.style.width = `${c.confidence * 100}%`
    fill.style.background = confidenceColor(c.confidence)
    bar.appendChild(fill)
    card.appendChild(bar)
  }

  // Explanation
  const expl = document.createElement("div")
  expl.className = "explanation"
  expl.textContent = c.explanation
  card.appendChild(expl)

  // Citations
  if (c.citations.length > 0) {
    const citSection = document.createElement("div")
    citSection.className = "citations"
    for (const src of c.citations) {
      const cit = document.createElement("div")
      cit.className = "citation"
      const link = document.createElement("a")
      link.href = src.url
      link.textContent = src.title
      link.target = "_blank"
      cit.appendChild(link)

      const meta = document.createElement("div")
      meta.className = "citation-meta"
      meta.textContent = `${src.publisher} · ${src.publishedDate || "no date"} · ${src.sourceTier}`
      cit.appendChild(meta)

      citSection.appendChild(cit)
    }
    card.appendChild(citSection)
  }

  // Needs human review flag
  if (c.needsHumanReview) {
    const hr = document.createElement("div")
    hr.style.cssText = "font-size:11px; color:var(--amber); margin-top:6px;"
    hr.textContent = "⚑ Review recommended — confidence is low or evidence is limited."
    card.appendChild(hr)
  }

  // Report incorrect button
  const reportRow = document.createElement("div")
  reportRow.style.cssText = "margin-top:8px; font-size:11px;"
  const reportLink = document.createElement("a")
  reportLink.href = `mailto:clarity@boanntech.com?subject=Incorrect%20verdict%20report&body=Claim:%20${encodeURIComponent(c.claim)}%0AVerdict:%20${c.verdict}%0AConfidence:%20${c.confidence}%0A`
  reportLink.textContent = "Report incorrect"
  reportLink.style.cssText = "color:var(--text-muted);text-decoration:none;"
  reportLink.addEventListener("click", () => {
    setTimeout(() => {
      const thanks = document.createElement("span")
      thanks.textContent = " ✓ Thanks"
      thanks.style.cssText = "color:var(--green);"
      reportRow.appendChild(thanks)
    }, 100)
  })
  reportRow.appendChild(reportLink)
  card.appendChild(reportRow)

  return card
}

function renderClaims(claims: ClaimCheck[]) {
  emptyState.style.display = "none"

  const existing = resultsEl.querySelectorAll(".claim-card")
  existing.forEach((el) => el.remove())

  if (claims.length === 0) {
    emptyState.innerHTML = "<p>No checkable factual claims were found on this page.</p>"
    emptyState.style.display = "block"
    return
  }

  for (const c of claims) {
    resultsEl.appendChild(buildClaimCard(c))
  }
}

/** Add one ad-hoc claim (from the right-click "Check this claim" menu) to
 * the top of the results without discarding whatever's already there.
 */
function prependClaim(claim: ClaimCheck) {
  emptyState.style.display = "none"
  resultsEl.insertBefore(buildClaimCard(claim), resultsEl.firstChild)
}

/* ───────── Highlight checked claims on the page ───────── */

async function highlightCheckedClaims(tabId: number, claims: ClaimCheck[]) {
  const targets = claims
    .filter((c) => c.verdict !== "not_checkable")
    .map((c) => ({ text: c.claim, verdict: c.verdict }))
  try {
    await chrome.tabs.sendMessage(tabId, { type: "HIGHLIGHT_CLAIMS", claims: targets })
  } catch {
    // Content script may be gone (page navigated away mid-check) — highlighting
    // is a visual aid, not required for the check itself to have succeeded.
  }
}

/* ───────── Main action ───────── */

async function checkPage() {
  setLoading(true)
  setStatus("scanning...", true)
  setProgress(10)

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab?.id) throw new Error("No active tab")

    const eligibility = assessPageUrl(tab.url ?? "")
    if (eligibility) {
      emptyState.innerHTML = `<p>${escapeHtml(eligibility)}</p>`
      emptyState.style.display = "block"
      setStatus("ineligible")
      return
    }

    setProgress(25)
    const pageResponse = await chrome.runtime.sendMessage({
      type: "GET_PAGE_TEXT_FOR_TAB",
      data: { tabId: tab.id },
    })
    if (pageResponse?.error) throw new Error(pageResponse.error)
    const payload = pageResponse

    if (!payload?.text || payload.text.length < 50) {
      const kind = String(payload?.kind ?? "unknown page")
      const length = typeof payload?.text === "string" ? payload.text.length : 0
      emptyState.innerHTML = `<p>Clarity captured only ${length} readable characters from this ${escapeHtml(kind)} page. Reload the extension and webpage, then try a public article or post.</p>`
      emptyState.style.display = "block"
      setStatus("no text")
      return
    }

    setProgress(50)
    setStatus("verifying...", true)

    const settings = await getSettings()
    const response = await chrome.runtime.sendMessage({
      type: "CHECK_PAGE",
      payload,
      settings: { maxClaims: settings.maxClaims },
    })

    setProgress(90)

    if (response.error) {
      emptyState.innerHTML = `<p>Error: ${escapeHtml(response.error)}</p>`
      emptyState.style.display = "block"
      setStatus("error")
      return
    }

    setProgress(100)
    setStatus(`${response.claims.length} claims`)

    // Check for backend offline indicator in any claim
    const hasOffline = response.claims.some(
      (c: ClaimCheck) => c.explanation.includes("Offline") || c.explanation.includes("could not be reached"),
    )
    if (hasOffline) {
      setStatus("offline")
    }

    renderClaims(response.claims)
    void highlightCheckedClaims(tab.id, response.claims)

    // Save to history — one merged write, newest first
    const entries: HistoryEntry[] = response.claims.map((c: ClaimCheck) => ({
      claim: c.claim,
      verdict: c.verdict,
      confidence: c.confidence,
      explanation: c.explanation,
      checkedAt: c.checkedAt,
      url: payload.url || "",
    }))
    const merged = mergeHistory(await getHistory(), entries, MAX_HISTORY)
    await chrome.storage.local.set({ [HISTORY_KEY]: merged })
  } catch (err) {
    emptyState.innerHTML = "<p>Could not communicate with this page. Reload and try again.</p>"
    emptyState.style.display = "block"
    setStatus("error")
    console.error("[Clarity] panel error:", err)
  } finally {
    setLoading(false)
  }
}

/* ───────── Check a single selected claim (right-click menu) ───────── */

async function checkSingleClaim(claimText: string) {
  const trimmed = claimText.trim()
  if (!trimmed) return

  showTab("check")
  setStatus("checking selection...", true)

  try {
    const response = await chrome.runtime.sendMessage({ type: "CHECK_CLAIM_TEXT", claim: trimmed })
    if (response?.error) {
      setStatus("error")
      console.error("[Clarity] selection check error:", response.error)
      return
    }

    const claims: ClaimCheck[] = response.claims ?? []
    setStatus(claims.length > 0 ? "1 claim checked" : "not checkable")
    for (const c of claims) prependClaim(c)

    if (claims.length > 0) {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
      const entries: HistoryEntry[] = claims.map((c) => ({
        claim: c.claim,
        verdict: c.verdict,
        confidence: c.confidence,
        explanation: c.explanation,
        checkedAt: c.checkedAt,
        url: tab?.url ?? "",
      }))
      const merged = mergeHistory(await getHistory(), entries, MAX_HISTORY)
      await chrome.storage.local.set({ [HISTORY_KEY]: merged })
    }
  } catch (err) {
    setStatus("error")
    console.error("[Clarity] selection check failed:", err)
  }
}

/** A right-click "Check this claim" hands off the selection two ways: a
 * live runtime message (for an already-open panel) and a short-lived
 * storage entry (for a panel that was just opened and is only now loading).
 * Both paths funnel through here rather than each calling checkSingleClaim
 * directly — if the panel's own (re)load happens to race with the live
 * message (both landing on the same freshly-loaded listener), storage is
 * the single source of truth: whichever call reads-then-removes the
 * pending entry first wins, and the other finds it already gone. The
 * synchronous in-flight guard closes the remaining race within this one
 * document, where both calls run on the same single JS thread: without
 * it, two concurrent calls could both read the entry before either
 * removes it, and both would proceed to check the same claim twice.
 */
let handlingPendingSelection = false

async function checkPendingSelection() {
  if (handlingPendingSelection) return
  handlingPendingSelection = true
  try {
    const result = await chrome.storage.local.get(PENDING_SELECTION_KEY)
    const pending = result[PENDING_SELECTION_KEY] as PendingSelection | undefined
    if (!pending || Date.now() - pending.ts > PENDING_SELECTION_MAX_AGE_MS) return
    await chrome.storage.local.remove(PENDING_SELECTION_KEY)
    await checkSingleClaim(pending.text)
  } catch {
    // No stored selection, or storage unavailable — nothing to do.
  } finally {
    handlingPendingSelection = false
  }
}

chrome.runtime.onMessage.addListener((message: { type: string }) => {
  if (message.type === "CHECK_SELECTION") {
    void checkPendingSelection()
  }
})

/* ───────── Events ───────── */

checkBtn.addEventListener("click", checkPage)
void checkPendingSelection()
