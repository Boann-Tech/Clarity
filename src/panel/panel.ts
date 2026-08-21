/**
 * Side Panel — Clarity claim assessment results in a compact,
 * evidence-first card UI.
 */

import type { ClaimCheck } from "../shared/protocol.js"

/* ───────── DOM refs ───────── */

const checkBtn = document.getElementById("checkBtn") as HTMLButtonElement
const resultsEl = document.getElementById("results") as HTMLDivElement
const emptyState = document.getElementById("emptyState") as HTMLDivElement
const statusBadge = document.getElementById("statusBadge") as HTMLSpanElement

/* ───────── Helpers ───────── */

function setStatus(text: string, active = false) {
  statusBadge.textContent = text
  statusBadge.className = `status-badge${active ? " active" : ""}`
}

function setLoading(loading: boolean) {
  checkBtn.disabled = loading
  checkBtn.textContent = loading ? "Checking..." : "Check claims on this page"
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

/* ───────── Render ───────── */

function renderClaims(claims: ClaimCheck[]) {
  emptyState.style.display = "none"

  // Clear previous results
  const existing = resultsEl.querySelectorAll(".claim-card")
  existing.forEach((el) => el.remove())

  if (claims.length === 0) {
    emptyState.innerHTML = "<p>No checkable factual claims were found on this page.</p>"
    emptyState.style.display = "block"
    return
  }

  for (const c of claims) {
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
        meta.textContent = `${src.publisher} · ${src.publishedDate}`
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

    resultsEl.appendChild(card)
  }
}

/* ───────── Main action ───────── */

async function checkPage() {
  setLoading(true)
  setStatus("scanning...", true)

  try {
    // Get page text from content script
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab?.id) throw new Error("No active tab")

    const payload = await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_TEXT" })

    if (!payload?.text || payload.text.length < 50) {
      emptyState.innerHTML = "<p>Not enough readable text found on this page.</p>"
      emptyState.style.display = "block"
      setStatus("no text")
      return
    }

    // Send to background for verification
    setStatus("verifying...", true)
    const response = await chrome.runtime.sendMessage({
      type: "CHECK_PAGE",
      payload,
    })

    if (response.error) {
      emptyState.innerHTML = `<p>Error: ${response.error}</p>`
      emptyState.style.display = "block"
      setStatus("error")
      return
    }

    setStatus(`${response.claims.length} claims`)
    renderClaims(response.claims)
  } catch (err) {
    emptyState.innerHTML = `<p>Could not communicate with this page. Reload and try again.</p>`
    emptyState.style.display = "block"
    setStatus("error")
    console.error("[Verify] panel error:", err)
  } finally {
    setLoading(false)
  }
}

/* ───────── Events ───────── */

checkBtn.addEventListener("click", checkPage)

// Auto-run on open
checkPage()