/**
 * Content Script — page text extractor for the Clarity extension.
 *
 * Runs on every page. When the side panel or background asks for text,
 * this script collects visible article/body text and sends it as a
 * PagePayload to the background service worker.
 */

import type { PagePayload } from "../shared/protocol.js"

/* ───────── Page type detection ───────── */

function detectPageKind(): PagePayload["kind"] {
  const host = window.location.hostname
  if (host.includes("youtube.com") || host.includes("youtu.be")) return "youtube"
  if (host.includes("twitter.com") || host.includes("x.com") || host.includes("reddit.com")) return "social"
  return "article"
}

/* ───────── Text extraction ───────── */

function extractArticleText(): string {
  // Try common article containers
  const selectors = [
    "article",
    '[role="article"]',
    ".post-content",
    ".entry-content",
    ".article-body",
    '[itemprop="articleBody"]',
    "main",
  ]

  for (const sel of selectors) {
    const el = document.querySelector(sel)
    if (el && el.textContent) {
      const text = el.textContent.trim()
      if (text.length > 100) return text
    }
  }

  // Fallback: body text
  const body = document.body
  if (body) {
    const text = body.innerText?.trim() ?? ""
    return text.slice(0, 10000) // cap at 10K chars
  }

  return ""
}

function extractYouTubeCaptions(): string {
  // YouTube captions are loaded dynamically into the transcript panel.
  // MVP: read the visible transcript segments if the user opened it.
  const segments = document.querySelectorAll(
    'ytd-transcript-segment-renderer .segment-text, [id^="segments-container"] .segment',
  )
  if (segments.length > 0) {
    return Array.from(segments)
      .map((s) => s.textContent?.trim())
      .filter(Boolean)
      .join(" ")
  }

  // Fallback: read the video title + description
  const title = document.querySelector("h1 yt-formatted-string")?.textContent ?? ""
  const description = document.querySelector("#description yt-formatted-string")?.textContent ?? ""
  return `${title}. ${description}`.trim()
}

/* ───────── Public API ───────── */

export function collectPagePayload(): PagePayload {
  const kind = detectPageKind()
  const text = kind === "youtube" ? extractYouTubeCaptions() : extractArticleText()
  const title = document.title || window.location.pathname

  return {
    title,
    text,
    url: window.location.href,
    kind,
  }
}

/* ───────── Listen for requests from background ───────── */

chrome.runtime.onMessage.addListener(
  (message: { type: string }, _sender, sendResponse) => {
    if (message.type === "GET_PAGE_TEXT") {
      const payload = collectPagePayload()
      sendResponse(payload)
    }
  },
)