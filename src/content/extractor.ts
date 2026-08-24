/**
 * Content Script — page text extractor for the Clarity extension.
 *
 * Supports: articles, YouTube captions, Twitter/X, Reddit, Facebook web.
 * Runs on every page. When the side panel asks for text, this script
 * collects visible text and sends it as a PagePayload.
 */

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
  if (host.includes("youtube.com") || host.includes("youtu.be")) return "youtube"
  if (host.includes("twitter.com") || host.includes("x.com")) return "social"
  if (host.includes("reddit.com")) return "social"
  if (host.includes("facebook.com")) return "social"
  return "article"
}

/* ─── Platform-specific extractors ─── */

function extractTwitterText(): string {
  // X/Twitter: extract visible tweets
  const tweets: string[] = []
  // New X layout
  const tweetArticles = document.querySelectorAll('article[data-testid="tweet"]')
  if (tweetArticles.length > 0) {
    tweetArticles.forEach((article) => {
      const textEl = article.querySelector('[data-testid="tweetText"]')
      if (textEl?.textContent) tweets.push(textEl.textContent.trim())
    })
    return tweets.join("\n")
  }
  // Fallback: general tweet divs
  const tweetDivs = document.querySelectorAll('div[data-testid="tweetText"]')
  tweetDivs.forEach((el) => {
    if (el.textContent) tweets.push(el.textContent.trim())
  })
  return tweets.join("\n")
}

function extractRedditText(): string {
  const parts: string[] = []

  // Post title
  const titleEl = document.querySelector(
    'shreddit-post[title], h1[slot="title"], div[data-testid="post-title"] a, h1',
  )
  if (titleEl?.textContent) parts.push(titleEl.textContent.trim())

  // Post body
  const bodyEl = document.querySelector(
    'shreddit-post [slot="text-body"], div[data-testid="post-container"] div[slot="text-body"], div.entry div.usertext-body div.md, div[data-testid="comment"]',
  )
  if (bodyEl?.textContent) parts.push(bodyEl.textContent.trim())

  // Comment text if visible
  const comments = document.querySelectorAll(
    'div[data-testid="comment"] div.md, shreddit-comment [slot="comment"]',
  )
  comments.forEach((el) => {
    if (el.textContent && el.textContent.length > 40) {
      parts.push(el.textContent.trim())
    }
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
    if (el.textContent && el.textContent.length > 30) {
      parts.push(el.textContent.trim())
    }
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
    const el = document.querySelector(sel)
    if (el?.textContent) {
      const text = el.textContent.trim()
      if (text.length > 100) return text
    }
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
  } else if (host.includes("twitter.com") || host.includes("x.com")) {
    text = extractTwitterText()
  } else if (host.includes("reddit.com")) {
    text = extractRedditText()
  } else if (host.includes("facebook.com")) {
    text = extractFacebookText()
  } else {
    text = extractArticleText()
  }

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