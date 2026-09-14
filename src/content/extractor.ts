/**
 * Content Script — page text extractor for the Clarity extension.
 *
 * Supports: articles, YouTube captions, Twitter/X, Reddit, Facebook web.
 * Runs on every page. When the side panel asks for text, this script
 * collects visible text and sends it as a PagePayload.
 */

const MAX_PAGE_TEXT = 20000

// Kept local (not imported) because this file is injected as a classic content
// script; any import/export makes tsc emit an ES module, which executeScript
// cannot inject. Keep in sync with protocol.isHostMatch.
function isHostMatch(host: string, domain: string): boolean {
  const h = host.toLowerCase()
  const d = domain.toLowerCase()
  return h === d || h.endsWith(`.${d}`)
}

type PageKind = "article" | "youtube" | "social" | "other"

type PagePayload = {
  title: string
  text: string
  url: string
  kind: PageKind
  publishedDate?: string
  author?: string
}

/* ───────── Page type detection ───────── */

function detectPageKind(): PagePayload["kind"] {
  const host = window.location.hostname
  if (isHostMatch(host, "youtube.com") || host === "youtu.be") return "youtube"
  if (isHostMatch(host, "twitter.com") || isHostMatch(host, "x.com")) return "social"
  if (isHostMatch(host, "reddit.com")) return "social"
  if (isHostMatch(host, "facebook.com")) return "social"
  return "article"
}

/**
 * Rendered text of an element, respecting layout-inserted whitespace at
 * block boundaries (paragraphs, list items, etc). Prefer this over
 * `.textContent`, which concatenates every descendant text node with no
 * separator at all — silently gluing adjacent paragraphs together
 * ("...credit cards.The spike...") and defeating the sentence-boundary
 * splitter downstream (extractCandidates in protocol.ts), which requires
 * whitespace after sentence punctuation to find a split point.
 */
function elementText(el: Element | null | undefined): string {
  if (!el) return ""
  return ((el as HTMLElement).innerText ?? el.textContent ?? "").trim()
}

/* ─── Platform-specific extractors ─── */

function extractTwitterText(): string {
  // X/Twitter: extract visible tweets
  const tweets: string[] = []
  // New X layout
  const tweetArticles = document.querySelectorAll('article[data-testid="tweet"]')
  if (tweetArticles.length > 0) {
    tweetArticles.forEach((article) => {
      const text = elementText(article.querySelector('[data-testid="tweetText"]'))
      if (text) tweets.push(text)
    })
    return tweets.join("\n")
  }
  // Fallback: general tweet divs
  const tweetDivs = document.querySelectorAll('div[data-testid="tweetText"]')
  tweetDivs.forEach((el) => {
    const text = elementText(el)
    if (text) tweets.push(text)
  })
  return tweets.join("\n")
}

function extractRedditText(): string {
  const parts: string[] = []

  // Post title
  const titleEl = document.querySelector(
    'shreddit-post[title], h1[slot="title"], div[data-testid="post-title"] a, h1',
  )
  const titleText = elementText(titleEl)
  if (titleText) parts.push(titleText)

  // Post body
  const bodyEl = document.querySelector(
    'shreddit-post [slot="text-body"], div[data-testid="post-container"] div[slot="text-body"], div.entry div.usertext-body div.md, div[data-testid="comment"]',
  )
  const bodyText = elementText(bodyEl)
  if (bodyText) parts.push(bodyText)

  // Comment text if visible
  const comments = document.querySelectorAll(
    'div[data-testid="comment"] div.md, shreddit-comment [slot="comment"]',
  )
  comments.forEach((el) => {
    const text = elementText(el)
    if (text.length > 40) parts.push(text)
  })

  return parts.join("\n")
}

function extractFacebookText(): string {
  const parts: string[] = []

  // Post messages
  const postMessages = document.querySelectorAll(
    'div[data-ad-preview="message"], div[data-ad-rendering-role="story_message"], div.userContent, div[role="article"] div[dir="auto"]',
  )
  postMessages.forEach((el) => {
    const text = elementText(el)
    if (text.length > 30) parts.push(text)
  })

  return parts.slice(0, 10).join("\n") // limit to 10 posts
}

/* ───────── Generic article text extraction ───────── */

function extractArticleText(): string {
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
    const text = elementText(document.querySelector(sel))
    if (text.length > 100) return text
  }

  const body = document.body
  if (body) {
    const text = body.innerText?.trim() ?? ""
    return text.slice(0, 10000)
  }

  return ""
}

/* ───────── YouTube caption extraction ───────── */

function extractYouTubeCaptions(): string {
  // Visible transcript segments if user opened the transcript panel
  const segments = document.querySelectorAll(
    'ytd-transcript-segment-renderer .segment-text, [id^="segments-container"] .segment, div.segment',
  )
  if (segments.length > 0) {
    return Array.from(segments)
      .map((s) => s.textContent?.trim())
      .filter(Boolean)
      .join(" ")
  }

  // Fallback: title + description
  const title = document.querySelector("h1 yt-formatted-string")?.textContent ?? ""
  const description = document.querySelector("#description yt-formatted-string")?.textContent ?? ""
  return `${title}. ${description}`.trim()
}

/* ───────── Public API ───────── */

function collectPagePayload(): PagePayload {
  const kind = detectPageKind()
  let text = ""
  const host = window.location.hostname

  if (kind === "youtube") {
    text = extractYouTubeCaptions()
  } else if (isHostMatch(host, "twitter.com") || isHostMatch(host, "x.com")) {
    text = extractTwitterText()
  } else if (isHostMatch(host, "reddit.com")) {
    text = extractRedditText()
  } else if (isHostMatch(host, "facebook.com")) {
    text = extractFacebookText()
  } else {
    text = extractArticleText()
  }

  const title = document.title || window.location.pathname

  return {
    title,
    text: text.slice(0, MAX_PAGE_TEXT),
    url: window.location.href,
    kind,
  }
}

/* ───────── Highlight checked claims on the page ───────── */

const HIGHLIGHT_CLASS = "clarity-hl"
const HIGHLIGHT_STYLE_ID = "clarity-hl-style"

function ensureHighlightStyles(): void {
  if (document.getElementById(HIGHLIGHT_STYLE_ID)) return
  const style = document.createElement("style")
  style.id = HIGHLIGHT_STYLE_ID
  style.textContent = `
    .${HIGHLIGHT_CLASS} { border-radius: 2px; box-shadow: 0 0 0 1px rgba(0,0,0,0.06); }
    .${HIGHLIGHT_CLASS}-supported { background: rgba(34,197,94,0.30); }
    .${HIGHLIGHT_CLASS}-contradicted { background: rgba(239,68,68,0.30); }
    .${HIGHLIGHT_CLASS}-misleading { background: rgba(245,158,11,0.32); }
    .${HIGHLIGHT_CLASS}-unverified { background: rgba(148,163,184,0.32); }
    .${HIGHLIGHT_CLASS}-not_checkable { background: rgba(148,163,184,0.18); }
  `
  document.documentElement.appendChild(style)
}

/** Remove any highlights from a previous check, merging split text nodes back. */
function clearHighlights(): void {
  document.querySelectorAll(`.${HIGHLIGHT_CLASS}`).forEach((el) => {
    const parent = el.parentNode
    if (!parent) return
    parent.replaceChild(document.createTextNode(el.textContent ?? ""), el)
    parent.normalize()
  })
}

function normalizeForMatch(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase()
}

/**
 * Wrap the first occurrence of `claimText` found inside a single text node
 * in a highlight span. Deliberately single-node only (never spans multiple
 * DOM nodes/elements) — Range.surroundContents throws when a range doesn't
 * cleanly contain whole non-text nodes, which a naive multi-node wrap would
 * hit constantly on real article markup (inline links, bold/italic spans).
 * A claim split across such inline markup is simply left unhighlighted;
 * this is a "best effort" visual aid, not a guarantee.
 */
function highlightClaimInNode(textNode: Text, claimText: string, verdict: string): boolean {
  const raw = textNode.nodeValue ?? ""
  const target = normalizeForMatch(claimText)
  if (!target) return false
  const normRaw = normalizeForMatch(raw)
  const matchIndex = normRaw.indexOf(target)
  if (matchIndex === -1) return false

  // Map an index into the whitespace-collapsed normRaw string back to the
  // corresponding index in the original (uncollapsed) raw string.
  const rawIndexAt = (normIndex: number): number => {
    let n = 0
    let inRun = false
    for (let r = 0; r < raw.length; r++) {
      const isSpace = /\s/.test(raw[r])
      if (isSpace) {
        if (!inRun) {
          if (n === normIndex) return r
          n++
          inRun = true
        }
      } else {
        if (n === normIndex) return r
        n++
        inRun = false
      }
    }
    return raw.length
  }

  const start = rawIndexAt(matchIndex)
  const end = rawIndexAt(matchIndex + target.length)
  if (end <= start) return false

  const range = document.createRange()
  range.setStart(textNode, start)
  range.setEnd(textNode, end)

  const span = document.createElement("span")
  span.className = `${HIGHLIGHT_CLASS} ${HIGHLIGHT_CLASS}-${verdict}`
  span.title = `Clarity checked this claim: ${verdict.replace(/_/g, " ")}`
  try {
    range.surroundContents(span)
  } catch {
    return false
  }
  return true
}

function collectTextNodes(root: Node): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const tag = node.parentElement?.tagName
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT" || tag === "TEXTAREA") {
        return NodeFilter.FILTER_REJECT
      }
      if (!node.nodeValue || node.nodeValue.trim().length < 20) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const nodes: Text[] = []
  let node: Node | null
  while ((node = walker.nextNode())) nodes.push(node as Text)
  return nodes
}

/** Highlight each checked claim's text where it's found on the page. Best
 * effort: claims not found verbatim (rare rewording, or split across inline
 * markup) are silently skipped. Returns how many were highlighted.
 */
function highlightClaimsOnPage(claims: Array<{ text: string; verdict: string }>): number {
  clearHighlights()
  if (claims.length === 0) return 0
  ensureHighlightStyles()

  let highlighted = 0
  for (const { text, verdict } of claims) {
    const textNodes = collectTextNodes(document.body)
    for (const node of textNodes) {
      if (highlightClaimInNode(node, text, verdict)) {
        highlighted++
        break
      }
    }
  }
  return highlighted
}

/* ───────── Listen for requests from background ───────── */

// getPagePayloadForTab (worker.ts) re-injects this script via
// chrome.scripting.executeScript whenever a plain sendMessage to an
// already-injected instance fails — e.g. a stale instance left over from
// before the extension itself was reloaded. Re-running this file would
// otherwise register a second onMessage listener alongside the first,
// racing to answer every future message. Guard with a flag on `window`
// (survives across separate injections into the same document, unlike a
// module-scope variable, since each injection gets a fresh script scope)
// so a re-injection only ever adds the listener once.
const INJECTED_FLAG = "__clarityExtractorListening"
if (!(window as unknown as Record<string, boolean>)[INJECTED_FLAG]) {
  ;(window as unknown as Record<string, boolean>)[INJECTED_FLAG] = true

  chrome.runtime.onMessage.addListener(
    (
      message: { type: string; claims?: Array<{ text: string; verdict: string }> },
      _sender,
      sendResponse,
    ) => {
      if (message.type === "GET_PAGE_TEXT") {
        const payload = collectPagePayload()
        sendResponse(payload)
        return
      }
      if (message.type === "HIGHLIGHT_CLAIMS") {
        const highlighted = highlightClaimsOnPage(message.claims ?? [])
        sendResponse({ highlighted })
        return
      }
      if (message.type === "CLEAR_HIGHLIGHTS") {
        clearHighlights()
        sendResponse({ ok: true })
        return
      }
    },
  )
}