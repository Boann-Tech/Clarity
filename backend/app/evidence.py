"""Evidence retrieval — search, fetch, and extract relevant passages.

Phases:
  1. DuckDuckGo search (no API key, rate-limited, free)
  2. Page fetch + text extraction
  3. Passage relevance scoring
  4. Source tiering via sources.py
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import defusedxml.ElementTree as ET
import httpx
from app.config import settings
from app.egress import build_pool
from app.sources import classify_domain, deduplicate_and_rank, tier_weight

logger = logging.getLogger("clarity.evidence")


# ── Search backends ──


def parse_ddg_results(html: str, max_results: int) -> list[dict]:
    results = []
    seen = set()
    pattern = re.compile(
        r'<a([^>]*class=["\'][^"\']*result-link[^"\']*["\'][^>]*)>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for attrs, title_html in pattern.findall(html):
        if len(results) >= max_results:
            break
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if not href_match:
            continue
        href = href_match.group(1)
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlparse(href)
        if "duckduckgo.com" in parsed.netloc:
            uddg = parse_qs(parsed.query).get("uddg")
            if not uddg:
                continue
            href = uddg[0]
        if not href.startswith(("http://", "https://")) or href in seen:
            continue
        title = re.sub(r"<[^>]+>", "", title_html).strip()
        if not title:
            continue
        seen.add(href)
        results.append({"title": title, "url": href, "snippet": "", "source": "duckduckgo"})
    return results


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
            # DDG returns HTTP 202 with a challenge/interstitial page when it
            # blocks automated Lite search. Treat it as unavailable, never as
            # an empty-but-valid result set. This is common from datacenter/
            # server IPs (e.g. a Docker host), not just misconfiguration.
            if resp.status_code != 200 or "duckduckgo.com" not in str(resp.url):
                logger.info(
                    "DDG search blocked or unavailable (status=%s) for %r — "
                    "treating as 0 results, not an error",
                    resp.status_code, query[:60],
                )
                return []
            resp.raise_for_status()
    except Exception as e:
        logger.warning("DDG search failed for %r: %s", query[:60], e)
        return []

    if resp.status_code != 200 or "duckduckgo.com" not in str(resp.url):
        return []
    results = parse_ddg_results(resp.text, max_results)
    logger.info("DDG search: %d result(s) for %r", len(results), query[:60])
    return results


def _unwrap_bing_news_link(link: str) -> str:
    """Bing News RSS wraps each item in an apiclick.aspx tracking redirect
    with the real destination in its `url` query param. Unwrap it so
    downstream domain classification sees the actual publisher, not bing.com.
    """
    parsed = urlparse(link)
    if parsed.netloc.endswith("bing.com"):
        target = parse_qs(parsed.query).get("url")
        if target:
            return target[0]
    return link


async def search_bing_rss(query: str, max_results: int = 10) -> list[dict]:
    """Search Bing News's RSS endpoint as a no-key fallback.

    Bing's classic `/search?format=rss` web-search RSS feed has been
    decommissioned — Microsoft now serves an unrelated generic content feed
    at that URL, dynamically retitled with the query but not actually driven
    by it. `/news/search?format=RSS` is still live and query-relevant, so
    that's what this hits. It is deliberately a fallback, not a primary
    evidence source: news-only coverage, and returned URLs still pass through
    Clarity's trusted-domain allowlist before anything is fetched or cited.
    """
    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            response = await client.get(
                "https://www.bing.com/news/search",
                params={"format": "RSS", "q": query},
                headers={"User-Agent": settings.user_agent},
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                logger.info("Bing News RSS response for %r exceeded 1MB — treating as unavailable", query[:60])
                return []
        root = ET.fromstring(response.content)
    except Exception as e:
        logger.warning("Bing News RSS search failed for %r: %s", query[:60], e)
        return []

    results = []
    for item in root.findall(".//item"):
        link = _unwrap_bing_news_link((item.findtext("link") or "").strip())
        title = (item.findtext("title") or "").strip()
        snippet = (item.findtext("description") or "").strip()
        if link and title:
            results.append({
                "title": title,
                "url": link,
                "snippet": snippet,
                "source": "bing_rss",
            })
        if len(results) >= max_results:
            break
    logger.info("Bing News RSS search: %d result(s) for %r", len(results), query[:60])
    return results


async def search_brave(query: str, max_results: int = 10) -> list[dict]:
    """Search Brave's web API when a production key is configured."""
    if not settings.brave_search_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(max_results, 20)},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.brave_search_api_key,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.warning("Brave search failed for %r: %s", query[:60], e)
        return []
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
            "source": "brave_search",
        }
        for item in payload.get("web", {}).get("results", [])
        if item.get("url")
    ][:max_results]
    logger.info("Brave search: %d result(s) for %r", len(results), query[:60])
    return results


async def search_serpapi(query: str, max_results: int = 10) -> list[dict]:
    """Search SerpAPI's Google engine when a production key is configured."""
    if not settings.serpapi_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            response = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google",
                    "q": query,
                    "api_key": settings.serpapi_key,
                    "num": min(max_results, 10),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.warning("SerpAPI search failed for %r: %s", query[:60], e)
        return []
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "serpapi",
        }
        for item in payload.get("organic_results", [])
        if item.get("link")
    ][:max_results]
    logger.info("SerpAPI search: %d result(s) for %r", len(results), query[:60])
    return results


US_MARKERS = re.compile(r"\b(?:u\.?s\.?a?|united states|american)\b", re.IGNORECASE)
INFLATION_MARKERS = re.compile(r"\b(?:inflation|cpi|consumer price)\b", re.IGNORECASE)


async def search_bls_cpi(claim: str) -> list[dict]:
    """Retrieve US CPI-U annual evidence directly from the public BLS API.

    This narrow connector bypasses generic search for US inflation claims and
    returns a source card backed by BLS's CPI-U series (CUUR0000SA0).
    """
    if not US_MARKERS.search(claim) or not INFLATION_MARKERS.search(claim):
        return []

    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", claim)]
    end_year = max(years) if years else datetime.now(timezone.utc).year - 1
    start_year = max(1948, end_year - 1)
    try:
        async with httpx.AsyncClient(timeout=settings.fetch_timeout) as client:
            response = await client.get(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0",
                params={"startyear": str(start_year), "endyear": str(end_year)},
                headers={"User-Agent": settings.user_agent},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.warning("BLS CPI API request failed: %s", e)
        return []

    try:
        if payload.get("status") != "REQUEST_SUCCEEDED":
            logger.info("BLS CPI API returned status=%r, not evidence for this claim", payload.get("status"))
            return []
        series = payload.get("Results", {}).get("series", [])
        data = series[0].get("data", []) if series else []
        values = {
            int(point["year"]): point["value"]
            for point in data
            if point.get("period") == "M12" and point.get("value") not in {None, "-"}
        }
        if end_year not in values or start_year not in values:
            return []
        current = float(values[end_year])
        prior = float(values[start_year])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return []
    annual_change = ((current - prior) / prior) * 100
    snippet = (
        f"BLS CPI-U (not seasonally adjusted) was {current:.3f} in December {end_year}, "
        f"compared with {prior:.3f} in December {start_year}: a {annual_change:.1f}% "
        f"year-over-year increase."
    )
    logger.info("BLS CPI direct connector matched — returning primary-source evidence, skipping generic search")
    return [{
        "title": f"Consumer Price Index for All Urban Consumers (CPI-U), {end_year}",
        "url": "https://www.bls.gov/cpi/",
        "snippet": snippet,
        "source": "bls_cpi_api",
        "published_date": f"{end_year}-12-31",
        "retrieval_status": "ok",
        "relevance": 1.0,
    }]


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
    except Exception as e:
        logger.warning("Google CSE search failed for %r: %s", query[:60], e)
        return []

    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "google_cse",
        })
    results = results[:max_results]
    logger.info("Google CSE search: %d result(s) for %r", len(results), query[:60])
    return results


async def search_evidence(query: str, max_results: int = 10) -> list[dict]:
    """Run search across all configured backends, deduplicate by URL.

    Returns a flat list of result dicts with title, url, snippet.
    """
    all_results: list[dict] = []

    # Direct primary-source connectors run first. They bypass generic search
    # for domains where an authoritative structured API is available.
    direct_results = await search_bls_cpi(query)

    # A direct primary connector has already supplied structured, attributable
    # evidence. Do not dilute it with generic search results for the same
    # narrow claim type.
    if direct_results:
        return direct_results[:max_results]

    # Run configured discovery searches in parallel. Bing RSS remains a
    # no-key fallback; all returned pages still pass curated-domain filtering.
    backends: list[tuple[str, object]] = []
    if settings.ddg_enabled:
        backends.append(("ddg", search_ddg(query, max_results)))
    if settings.google_api_key and settings.google_cse_id:
        backends.append(("google_cse", search_google(query, max_results)))
    if settings.brave_search_api_key:
        backends.append(("brave", search_brave(query, max_results)))
    if settings.serpapi_key:
        backends.append(("serpapi", search_serpapi(query, max_results)))
    # Last-resort no-key discovery fallback. It is not used when a direct
    # connector supplies evidence, and all results still require validation.
    backends.append(("bing_rss", search_bing_rss(query, max_results)))

    if len(backends) == 1:
        logger.info(
            "Only the keyless bing_rss fallback is configured — set "
            "CLARITY_BRAVE_SEARCH_API_KEY (recommended), CLARITY_SERPAPI_KEY, "
            "or CLARITY_GOOGLE_API_KEY/CLARITY_GOOGLE_CSE_ID for reliable search."
        )

    search_results = await asyncio.gather(*(coro for _, coro in backends), return_exceptions=True)
    all_results.extend(direct_results)

    per_backend_counts = {}
    for (name, _), sr in zip(backends, search_results):
        if isinstance(sr, list):
            per_backend_counts[name] = len(sr)
            all_results.extend(sr)
        elif isinstance(sr, BaseException):
            per_backend_counts[name] = "error"
            logger.warning("%s search raised unexpectedly for %r: %s", name, query[:60], sr)

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        unique.append(r)

    logger.info(
        "search_evidence(%r): %s -> %d unique result(s)",
        query[:60],
        ", ".join(f"{name}={count}" for name, count in per_backend_counts.items()),
        len(unique),
    )
    return unique[:max_results]


# ── Page fetching ──

CURATED_TIERS = {"primary", "fact_check", "secondary_news"}
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class FetchedPage:
    html: str
    final_url: str


def is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _decode_body(body: bytes, headers: dict[str, str]) -> str:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    encoding = match.group(1).strip("\"'") if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def _request(pool, url: str, headers: dict[str, str], max_bytes: int):
    """One validated hop. Returns (status, headers, body_or_None)."""
    timeout = settings.fetch_timeout
    extensions = {"timeout": {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}}
    async with pool.stream("GET", url, headers=headers, extensions=extensions) as response:
        status = response.status
        response_headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in response.headers
        }
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_stream():
            total += len(chunk)
            if total > max_bytes:
                return status, response_headers, None
            chunks.append(chunk)
        return status, response_headers, b"".join(chunks)


async def fetch_page(url: str) -> FetchedPage | None:
    """Fetch a curated page, validating every hop against SSRF and tier rules.

    Unknown or excluded domains are never requested. Every connection dials a
    pre-validated public IP (see app.egress). Redirects are followed manually
    (max 5) and every hop must be a public http(s) URL on a curated domain.
    """
    current = url
    pool = build_pool()
    try:
        for hop in range(MAX_REDIRECTS + 1):
            if not is_public_http_url(current):
                logger.info("fetch_page: rejecting %r — not a public http(s) URL", current)
                return None
            tier = classify_domain(current).tier
            if tier not in CURATED_TIERS:
                logger.info("fetch_page: rejecting %r — tier=%r not curated", current, tier)
                return None
            max_bytes = 2_000_000 if tier in {"primary", "fact_check"} else 200_000
            status, headers, body = await _request(
                pool, current, {"User-Agent": settings.user_agent}, max_bytes
            )
            if status in {401, 403, 429}:
                status, headers, body = await _request(pool, current, BROWSER_HEADERS, max_bytes)
            if status in REDIRECT_CODES:
                location = headers.get("location")
                if not location:
                    logger.info("fetch_page: %r sent redirect status=%s with no Location header", current, status)
                    return None
                current = urljoin(current, location)
                continue
            if status >= 400 or body is None:
                logger.info(
                    "fetch_page: rejecting %r — status=%s%s",
                    current, status, "" if body is not None else " (body exceeded max size)",
                )
                return None
            content_type = headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                logger.info("fetch_page: rejecting %r — content-type=%r", current, content_type)
                return None
            if classify_domain(current).tier not in CURATED_TIERS:
                logger.info("fetch_page: rejecting %r — redirected to a non-curated domain", current)
                return None
            if hop > 0:
                logger.info("fetch_page: fetched %r (via %d redirect hop(s) from %r)", current, hop, url)
            return FetchedPage(html=_decode_body(body, headers), final_url=current)
        logger.info("fetch_page: rejecting %r — exceeded %d redirect hops", url, MAX_REDIRECTS)
        return None
    except Exception as e:
        logger.warning("fetch_page: %r raised during fetch: %s", current, e)
        return None
    finally:
        await pool.aclose()


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


PASSAGE_MIN_CHARS = 40


def _curate_search_results(search_results: list[dict]) -> list[dict]:
    """Dedupe by URL and keep only curated-tier candidates, in order."""
    curated: list[dict] = []
    seen_urls: set[str] = set()
    for result in search_results:
        url = result.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if classify_domain(url).tier not in CURATED_TIERS:
            continue
        curated.append(result)
    logger.info(
        "curation: %d/%d search result(s) are on a curated (trusted) domain",
        len(curated), len(search_results),
    )
    return curated


async def _fetch_and_rank(claim: str, curated: list[dict], max_sources: int) -> list[dict]:
    """Fetch each curated candidate once, score its most relevant passage
    against `claim`, and return the results ranked by source quality.
    """
    semaphore = asyncio.Semaphore(4)

    async def build_source(result: dict) -> dict | None:
        if result.get("source") == "bls_cpi_api":
            return result.copy()
        async with semaphore:
            fetched = await fetch_page(result["url"])
        if fetched is None:
            return None
        text = extract_text_from_html(fetched.html)
        passage = extract_relevant_passage(text, claim)
        if len(passage.strip()) < PASSAGE_MIN_CHARS:
            return None
        return {
            "title": result.get("title", "Untitled"),
            "url": fetched.final_url,
            "snippet": passage,
            "published_date": estimate_publish_date(fetched.html),
            "relevance": 0.6,
            "retrieval_status": "ok",
        }

    attempted = curated[:max_sources]
    built = await asyncio.gather(*(build_source(r) for r in attempted))
    raw_sources = [source for source in built if source is not None]
    logger.info("fetch: %d/%d candidate page(s) fetched and yielded a usable passage", len(raw_sources), len(attempted))
    if not raw_sources:
        return []
    return deduplicate_and_rank(raw_sources)


async def _classify_and_format(
    claim: str, ranked: list[dict], use_llm: bool, max_sources: int
) -> list[dict]:
    """Optionally LLM-classify each ranked source once against `claim`, then
    shape the public citation dicts.
    """
    if use_llm and ranked:
        try:
            from app.llm import classify_passages

            passage_inputs = [
                {
                    "index": i,
                    "text": src.get("snippet", "")[:800],
                    "url": src.get("url", ""),
                    "tier": src.get("tier", "unknown"),
                }
                for i, src in enumerate(ranked)
            ]
            classified = await asyncio.to_thread(classify_passages, claim, passage_inputs)
            for classified_p in classified:
                idx = classified_p.get("index")
                if isinstance(idx, int) and 0 <= idx < len(ranked):
                    ranked[idx]["relation"] = classified_p.get("relation", "context")
                    ranked[idx]["llm_confidence"] = classified_p.get("llm_confidence", 0.5)
                    ranked[idx]["reasoning"] = classified_p.get("reasoning", "")
            before = len(ranked)
            ranked = [src for src in ranked if src.get("relation", "context") != "irrelevant"]
            logger.info("LLM classification: kept %d/%d passage(s) as relevant", len(ranked), before)
        except Exception as e:
            logger.warning("LLM classification failed, defaulting %d passage(s) to 'context': %s", len(ranked), e)
            for src in ranked:
                src.setdefault("relation", "context")

    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "title": src["title"],
            "publisher": classify_domain(src["url"]).domain,
            "url": src["url"],
            "published_date": src.get("published_date"),
            "accessed_at": now,
            "tier": classify_domain(src["url"]).tier,
            "snippet": src["snippet"],
            "relevance_score": round(src.get("relevance_score", 0), 2),
            "retrieval_status": src.get("retrieval_status", "ok"),
            "relation": src.get("relation", "context"),
            "llm_confidence": src.get("llm_confidence", 0.5),
            "reasoning": src.get("reasoning", ""),
        }
        for src in ranked[:max_sources]
    ]


async def retrieve_evidence(claim: str, max_sources: int = 8, use_llm: bool = False) -> list[dict]:
    search_results = await search_evidence(claim, max_results=15)
    if not search_results:
        logger.info("retrieve_evidence(%r): search returned nothing — 0 citations", claim[:80])
        return []
    curated = _curate_search_results(search_results)
    if not curated:
        logger.info("retrieve_evidence(%r): no search result was on a curated domain — 0 citations", claim[:80])
        return []
    ranked = await _fetch_and_rank(claim, curated, max_sources)
    if not ranked:
        logger.info("retrieve_evidence(%r): no candidate page could be fetched — 0 citations", claim[:80])
        return []
    citations = await _classify_and_format(claim, ranked, use_llm, max_sources)
    logger.info("retrieve_evidence(%r): %d citation(s)", claim[:80], len(citations))
    return citations


async def retrieve_evidence_multi(
    claim: str,
    search_queries: list[str],
    max_sources: int = 8,
    use_llm: bool = False,
) -> list[dict]:
    """Retrieve evidence for one claim across several search queries,
    fetching and classifying each candidate URL only once.

    `search_queries` typically comes from `app.llm.normalize_claim`: 2-3
    keyword-optimised variants of the same claim. Calling `retrieve_evidence`
    once per query and merging citations afterwards — the original approach —
    fetches and LLM-classifies the same URL again every time a different
    query happens to surface it too. This merges and dedupes candidate URLs
    *before* fetching, so overlap between queries costs nothing extra, and it
    scores/classifies every passage against the original claim text rather
    than a keyword-optimised sub-query.
    """
    queries = list(dict.fromkeys(q.strip() for q in search_queries if q and q.strip())) or [claim]
    logger.info("retrieve_evidence_multi(%r): searching %d quer(ies): %s", claim[:80], len(queries), queries)

    search_result_lists = await asyncio.gather(
        *(search_evidence(query, max_results=15) for query in queries),
        return_exceptions=True,
    )
    merged: list[dict] = []
    for query, result_list in zip(queries, search_result_lists):
        if isinstance(result_list, list):
            merged.extend(result_list)
        elif isinstance(result_list, BaseException):
            logger.warning("search_evidence raised unexpectedly for query %r: %s", query[:60], result_list)
    if not merged:
        logger.info("retrieve_evidence_multi(%r): no query returned results — 0 citations", claim[:80])
        return []

    curated = _curate_search_results(merged)
    if not curated:
        logger.info("retrieve_evidence_multi(%r): no search result was on a curated domain — 0 citations", claim[:80])
        return []
    ranked = await _fetch_and_rank(claim, curated, max_sources)
    if not ranked:
        logger.info("retrieve_evidence_multi(%r): no candidate page could be fetched — 0 citations", claim[:80])
        return []
    citations = await _classify_and_format(claim, ranked, use_llm, max_sources)
    logger.info("retrieve_evidence_multi(%r): %d citation(s)", claim[:80], len(citations))
    return citations