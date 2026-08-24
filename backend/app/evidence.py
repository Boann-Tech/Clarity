"""Evidence retrieval — search, fetch, and extract relevant passages.

Phases:
  1. DuckDuckGo search (no API key, rate-limited, free)
  2. Page fetch + text extraction
  3. Passage relevance scoring
  4. Source tiering via sources.py
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from app.config import settings
from app.sources import classify_domain, deduplicate_and_rank, tier_weight


# ── Search backends ──


async def search_ddg(query: str, max_results: int = 10) -> list[dict]:
    """Search DuckDuckGo via the lite API (no API key needed)."""
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": settings.user_agent,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"q": query}

    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            resp = await client.post(url, headers=headers, data=data)
            resp.raise_for_status()
    except Exception:
        return []

    # Parse the HTML response
    results = []
    # Very rough DDG lite HTML parser
    html = resp.text
    # Find result blocks
    blocks = re.findall(
        r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE,
    )
    seen = set()
    for href, title_text in blocks:
        if len(results) >= max_results:
            break
        # Clean title
        title = re.sub(r"<[^>]+>", "", title_text).strip()
        if not title or href in seen:
            continue
        seen.add(href)
        results.append({
            "title": title,
            "url": href,
            "snippet": "",
            "source": "duckduckgo",
        })

    return results


async def search_google(query: str, max_results: int = 10) -> list[dict]:
    """Search via Google Custom Search JSON API."""
    if not settings.google_api_key or not settings.google_cse_id:
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": settings.google_api_key,
        "cx": settings.google_cse_id,
        "q": query,
        "num": min(max_results, 10),
    }

    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "google_cse",
        })
    return results[:max_results]


async def search_evidence(query: str, max_results: int = 10) -> list[dict]:
    """Run search across all configured backends, deduplicate by URL.

    Returns a flat list of result dicts with title, url, snippet.
    """
    all_results: list[dict] = []

    # Run searches in parallel
    tasks = []
    if settings.ddg_enabled:
        tasks.append(search_ddg(query, max_results))
    if settings.google_api_key and settings.google_cse_id:
        tasks.append(search_google(query, max_results))

    if not tasks:
        # No search backends configured
        return []

    import asyncio
    search_results = await asyncio.gather(*tasks, return_exceptions=True)

    for sr in search_results:
        if isinstance(sr, list):
            all_results.extend(sr)

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        unique.append(r)

    return unique[:max_results]


# ── Page fetching ──


async def fetch_page(url: str) -> str | None:
    """Fetch a page and return its visible text content (first ~10K chars)."""
    headers = {"User-Agent": settings.user_agent}

    try:
        async with httpx.AsyncClient(
            timeout=settings.fetch_timeout,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return None

            html = resp.text
            if len(html) > 200_000:
                return None  # too large

            return html
    except Exception:
        return None


def extract_text_from_html(html: str, max_chars: int = 8000) -> str:
    """Extract readable text from HTML, stripping scripts, styles, nav."""
    # Remove scripts, styles, nav, header, footer
    for tag in r"<script[^>]*>.*?</script>", r"<style[^>]*>.*?</style>":
        html = re.sub(tag, " ", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", " ", html)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    # Extract meaningful lines
    lines = [l.strip() for l in text.split(".") if len(l.strip()) > 40]
    text = ". ".join(lines)

    return text[:max_chars]


def extract_relevant_passage(
    page_text: str,
    claim: str,
    max_chars: int = 600,
) -> str:
    """Find the passage in a page most relevant to the claim.

    Simple approach: find sentences that share significant words with the claim.
    """
    if not page_text:
        return ""

    # Simple word overlap scoring
    claim_words = set(claim.lower().split())
    stopwords = {
        "the", "a", "an", "is", "was", "were", "are", "be", "been",
        "in", "on", "at", "to", "for", "of", "by", "with", "and", "or",
        "but", "not", "it", "its", "this", "that", "these", "those",
        "from", "as", "has", "had", "have", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "can",
    }
    claim_content = claim_words - stopwords

    if not claim_content:
        # Fallback: first meaningful paragraph
        return page_text[:max_chars]

    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", page_text)

    best_score = 0
    best_passage = ""
    best_idx = 0

    for i, sent in enumerate(sentences):
        sent_words = set(sent.lower().split())
        overlap = len(claim_content & sent_words)
        if overlap > best_score:
            best_score = overlap
            best_passage = sent
            best_idx = i

    # Grab surrounding context
    if best_score > 0:
        start = max(0, best_idx - 1)
        end = min(len(sentences), best_idx + 2)
        passage = ". ".join(sentences[start:end])
    else:
        passage = page_text[:max_chars]

    return passage[:max_chars].strip()


def estimate_publish_date(html: str) -> str | None:
    """Try to extract a publication date from HTML meta tags."""
    patterns = [
        r'<meta[^>]*name=["\']date["\'][^>]*content=["\']([^"\']+)',
        r'<meta[^>]*property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)',
        r'<meta[^>]*itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)',
        r'<time[^>]*datetime=["\']([^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)[:10]  # YYYY-MM-DD
    return None


# ── Full evidence pipeline ──


async def retrieve_evidence(
    claim: str,
    max_sources: int = 8,
    use_llm: bool = False,
) -> list[dict]:
    """Full evidence retrieval pipeline.

    1. Search the web for the claim
    2. Fetch each result page
    3. Extract relevant passages
    4. Classify and rank by source quality
    5. Return deduplicated, ranked citations
    """
    # Step 1: Search
    search_results = await search_evidence(claim, max_results=15)
    if not search_results:
        return []

    # Step 2-3: Fetch + extract passages
    raw_sources: list[dict] = []
    for result in search_results[:max_sources]:
        url = result["url"]
        html = await fetch_page(url)
        if not html:
            raw_sources.append({
                "title": result["title"],
                "url": url,
                "snippet": result.get("snippet", ""),
                "published_date": None,
                "relevance": 0.3,
                "retrieval_status": "fetch_error",
            })
            continue

        text = extract_text_from_html(html)
        passage = extract_relevant_passage(text, claim)
        pub_date = estimate_publish_date(html)

        raw_sources.append({
            "title": result["title"],
            "url": url,
            "snippet": passage or result.get("snippet", ""),
            "published_date": pub_date,
            "relevance": 0.6 if passage else 0.3,
            "retrieval_status": "ok",
        })

    # Step 4: Deduplicate, classify, rank
    ranked = deduplicate_and_rank(raw_sources)

    # Step 4b: Optional LLM passage classification
    if use_llm and ranked:
        try:
            from app.llm import classify_passages

            passage_inputs = []
            for i, src in enumerate(ranked):
                passage_inputs.append({
                    "index": i,
                    "text": src.get("snippet", "")[:800],
                    "url": src.get("url", ""),
                    "tier": src.get("tier", "unknown"),
                })
            classified = classify_passages(claim, passage_inputs)
            # Merge LLM classifications back into ranked sources
            for classified_p in classified:
                idx = classified_p.get("index")
                if idx is not None and idx < len(ranked):
                    ranked[idx]["relation"] = classified_p.get("relation", "context")
                    ranked[idx]["llm_confidence"] = classified_p.get("llm_confidence", 0.5)
                    ranked[idx]["reasoning"] = classified_p.get("reasoning", "")
        except Exception:
            for src in ranked:
                src.setdefault("relation", "context")

    # Step 5: Format as citations
    now = datetime.now(timezone.utc).isoformat()
    citations = []
    for src in ranked[:max_sources]:
        sq = classify_domain(src["url"])
        citations.append({
            "title": src["title"],
            "publisher": sq.domain,
            "url": src["url"],
            "published_date": src.get("published_date"),
            "accessed_at": now,
            "tier": sq.tier,
            "snippet": src["snippet"],
            "relevance_score": round(src.get("relevance_score", 0), 2),
            "retrieval_status": src.get("retrieval_status", "ok"),
            # LLM annotations stay internal to the backend verdict stage;
            # extra keys are ignored by the public CitationSource model.
            "relation": src.get("relation", "context"),
            "llm_confidence": src.get("llm_confidence", 0.5),
            "reasoning": src.get("reasoning", ""),
        })

    return citations