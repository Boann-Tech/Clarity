"""Clarity API — FastAPI application.

Endpoints:
  POST /api/check    — Check a factual claim against curated evidence sources
  GET  /api/health   — Health check

Evidence-first invariant is enforced at the serialisation boundary:
no verdict without at least one qualifying citation URL.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.cache import build_response_cache
from app.config import settings
from app.evidence import retrieve_evidence_multi
from app.metrics import metrics
from app.models import (
    Assessment,
    BatchCheckRequest,
    BatchCheckResponse,
    CheckRequest,
    CheckResponse,
    CitationSource,
    Verdict,
)
from app.providers import get_llm_config
from app.ratelimit import build_rate_limiter
from app.sources import independence_group
from app.verdict import calculate_verdict, qualifying_citations

logger = logging.getLogger("clarity.api")

app = FastAPI(
    title="Clarity API",
    version="3.0.0",
    description="Evidence-first claim verification. Uses a configured OpenAI-compatible model for claim normalization, passage classification, and verdict synthesis — always over retrieved sources.",
    docs_url="/docs",
)

# ── Module state ──

_rate_limiter = build_rate_limiter()
_response_cache = build_response_cache()

# ── CORS ──

# Chrome extensions have per-install IDs, so a literal `chrome-extension://*`
# cannot be used in allow_origins. Use a strict origin regex instead.
CHROME_EXTENSION_ORIGIN_REGEX = r"^chrome-extension://[a-z]{32}$"

_configured_origins = [origin.strip() for origin in settings.cors_origins if origin.strip()]
_extension_wildcard = "chrome-extension://*" in _configured_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in _configured_origins if o != "chrome-extension://*"],
    allow_origin_regex=CHROME_EXTENSION_ORIGIN_REGEX if _extension_wildcard else None,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/api/health")
async def health():
    config = get_llm_config()
    return {
        "status": "ok",
        "version": "3.0.0",
        "llm_enabled": config.enabled,
        "provider": config.provider,
        "model_configured": bool(config.model),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/metrics")
async def get_metrics():
    """Per-process operational counters: cache hit rate, verdict
    distribution, rate-limit rejections, and LLM call counts/latency by
    role. Not shared across workers/replicas — see app.metrics.
    """
    return metrics.snapshot()


def _client_ip(request: Request) -> str:
    """Resolve the rate-limit key for a request's real client IP.

    Ignores X-Forwarded-For unless `CLARITY_TRUSTED_PROXY_HOPS` says how many
    trusted proxies sit in front of Clarity — trusting a client-supplied
    header by default would let any client spoof its rate-limit identity.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            chain = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
            if len(chain) >= hops:
                return chain[-hops]
    return request.client.host if request.client else "unknown"


async def _enforce_limits(request: Request, count: int = 1) -> None:
    client_key = _client_ip(request)
    allowed = await _rate_limiter.allow_many(
        client_key, count, settings.rate_limit_per_minute, settings.rate_limit_per_hour
    )
    if not allowed:
        metrics.incr("rate_limited", count)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


async def _require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def _clean_text(value: object, limit: int, default: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
    elif value is None:
        text = ""
    else:
        text = str(value).strip()
    return (text or default)[:limit]


def _clean_limitations(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean_text(item, 120)
        if text and text not in out:
            out.append(text)
    return out[:10]


def _clean_queries(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    queries = [_clean_text(item, 300) for item in value]
    queries = [q for q in queries if len(q) >= 3][:3]
    return queries or fallback


def _clean_tier(value: object) -> str:
    tier = _clean_text(value, 32)
    return tier if tier in {"primary", "fact_check", "secondary_news"} else "secondary_news"


async def _check_normalized(
    req: CheckRequest,
    normalized_claim: str,
    llm_available: bool,
    request_id: str,
    now: str,
) -> CheckResponse:
    """Run the evidence pipeline for an already-normalised, cache-missed claim."""
    # Step 1b: Optional LLM claim normalisation for better search queries
    search_queries = [normalized_claim]
    if llm_available:
        try:
            from app.llm import normalize_claim

            normalized = await asyncio.to_thread(normalize_claim, normalized_claim)
            if normalized.get("checkable", True) is False:
                # LLM says this isn't a checkable factual claim
                response = CheckResponse(
                    request_id=request_id,
                    claim=req.claim,
                    normalized_claim=_clean_text(normalized.get("normalized_claim"), 500, normalized_claim),
                    checked_at=now,
                    assessment=Assessment(
                        verdict=Verdict.not_checkable,
                        confidence=0.0,
                        explanation=_clean_text(
                            normalized.get("reasoning"),
                            600,
                            "This appears to be an opinion, prediction, or value statement, not a checkable factual claim.",
                        ),
                    ),
                    citations=[],
                    limitations=["not_checkable"],
                    policy_version="3.0",
                )
                metrics.incr("verdict:not_checkable")
                await _response_cache.set(normalized_claim, response.model_dump())
                return response

            # Use LLM-generated search queries for better results
            search_queries = _clean_queries(normalized.get("search_queries"), search_queries)
            logger.info(
                "LLM normalisation: %s → %s",
                normalized_claim,
                search_queries[0],
            )
        except Exception as e:
            logger.warning("LLM normalisation failed: %s — falling back to raw claim", e)

    # Step 2-4: Retrieve evidence across every generated query, fetching and
    # LLM-classifying each candidate URL only once even when more than one
    # query surfaces it.
    citations = await retrieve_evidence_multi(
        normalized_claim,
        search_queries,
        max_sources=settings.max_sources_per_claim,
        use_llm=llm_available,
    )

    # Sources marked irrelevant by the LLM evidence classifier must never
    # be rendered as citations, even if a prior process was running older code.
    citations = [
        citation for citation in citations
        if citation.get("relation", "context") != "irrelevant"
    ]

    # Step 5: Calculate verdict
    if llm_available and citations:
        try:
            from app.llm import synthesize_verdict

            # Build passage list for LLM verdict synthesis
            classified_passages = []
            for i, c in enumerate(citations):
                classified_passages.append({
                    "index": i,
                    "text": c.get("snippet", ""),
                    "url": c.get("url", ""),
                    "tier": c.get("tier", "unknown"),
                    "relation": c.get("relation", "context"),
                    "llm_confidence": c.get("llm_confidence", 0.5),
                    "reasoning": c.get("reasoning", ""),
                    "published_date": c.get("published_date"),
                    "retrieval_status": c.get("retrieval_status", "ok"),
                })

            llm_result = await asyncio.to_thread(synthesize_verdict, normalized_claim, classified_passages)
            assessment = Assessment(
                verdict=llm_result.get("verdict", "unverified"),
                confidence=max(0.0, min(float(llm_result.get("confidence", 0.0) or 0.0), 1.0)),
                explanation=_clean_text(llm_result.get("explanation"), 600, ""),
                domain=llm_result.get("domain") or None,
            )
            llm_limitations = _clean_limitations(llm_result.get("limitations"))
            logger.info(
                "LLM verdict: %s (%.2f) — %d passages",
                assessment.verdict,
                assessment.confidence,
                len(classified_passages),
            )
        except Exception as e:
            logger.warning("LLM verdict synthesis failed: %s — using deterministic", e)
            assessment = calculate_verdict(citations)
            llm_limitations = []
    else:
        assessment = calculate_verdict(citations)
        llm_limitations = []

    # Step 6: Evidence-first invariant — enforce at serialisation boundary
    if assessment.verdict in (Verdict.supported, Verdict.contradicted, Verdict.misleading):
        qualifying = qualifying_citations(citations)
        if assessment.verdict == Verdict.misleading:
            conflicting = [c for c in qualifying if c.get("relation") in ("supports", "contradicts")]
            publishers = {independence_group(c.get("url", "")) for c in conflicting}
            has_both_relations = any(
                c.get("relation") == "supports" for c in conflicting
            ) and any(c.get("relation") == "contradicts" for c in conflicting)
            if len(publishers) < 2 or not has_both_relations:
                qualifying = []
        if not qualifying:
            assessment = Assessment(
                verdict=Verdict.unverified,
                confidence=0.0,
                explanation=(
                    "The available evidence could not be validated against "
                    "authoritative source requirements."
                ),
            )

    metrics.incr(f"verdict:{assessment.verdict.value}")
    logger.info(
        "check complete: claim=%r verdict=%s confidence=%.2f citations=%d",
        normalized_claim[:80], assessment.verdict.value, assessment.confidence, len(citations),
    )

    # Build limitations
    limitations = []
    limitations.extend(llm_limitations)
    if not citations:
        limitations.append("no_sources_found")
    elif not any(c.get("tier") in ("primary", "fact_check") for c in citations):
        if "no_qualifying_sources" not in limitations:
            limitations.append("no_qualifying_sources")

    # Format citations
    formatted_citations = [
        CitationSource(
            title=_clean_text(c.get("title"), 300, "Untitled"),
            publisher=_clean_text(c.get("publisher"), 200, _clean_tier(c.get("tier"))),
            url=_clean_text(c.get("url"), 2048),
            published_date=_clean_text(c.get("published_date"), 64) or None,
            accessed_at=_clean_text(c.get("accessed_at"), 64, now),
            tier=_clean_tier(c.get("tier")),
            snippet=_clean_text(c.get("snippet"), 800),
            relevance_score=max(0.0, min(float(c.get("relevance_score") or 0.0), 1.0)),
            retrieval_status=_clean_text(c.get("retrieval_status"), 32, "ok"),
        )
        for c in citations
        if str(c.get("url") or "").startswith("http")
    ]

    response = CheckResponse(
        request_id=request_id,
        claim=req.claim,
        normalized_claim=normalized_claim,
        checked_at=now,
        assessment=assessment,
        citations=formatted_citations,
        limitations=sorted(set(limitations)),
        policy_version="3.0",
    )
    await _response_cache.set(normalized_claim, response.model_dump())
    return response


@app.post("/api/check")
async def check_claim(
    req: CheckRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> CheckResponse:
    """Check a factual claim against curated evidence sources.

    Pipeline:
      1. Normalise claim + optional LLM claim normalisation for better search
      2. Search web for evidence
      3. Fetch and extract relevant passages
      4. Classify passages (optional LLM: supports/contradicts/context)
      5. Calculate verdict (LLM-powered if available, deterministic fallback)
      6. Enforce evidence-first invariant at serialisation boundary
    """
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    normalized_claim = " ".join(req.claim.split())

    cached = await _response_cache.get(normalized_claim)
    if cached is not None:
        metrics.incr("cache_hit")
        return CheckResponse.model_validate(cached)
    metrics.incr("cache_miss")

    await _enforce_limits(request, 1)
    return await _check_normalized(req, normalized_claim, get_llm_config().enabled, request_id, now)


@app.post("/api/check/batch")
async def check_batch(
    req: BatchCheckRequest,
    request: Request,
    _: None = Depends(_require_token),
) -> BatchCheckResponse:
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    llm_available = get_llm_config().enabled

    results: list[CheckResponse | None] = [None] * len(req.claims)
    pending: dict[str, list[int]] = {}
    for index, claim in enumerate(req.claims):
        cached = await _response_cache.get(claim)
        if cached is not None:
            metrics.incr("cache_hit")
            results[index] = CheckResponse.model_validate(cached)
        else:
            metrics.incr("cache_miss")
            pending.setdefault(claim, []).append(index)

    await _enforce_limits(request, len(pending))

    semaphore = asyncio.Semaphore(3)

    async def run(claim: str, indices: list[int]) -> None:
        async with semaphore:
            single = CheckRequest(claim=claim)
            result = await _check_normalized(
                single, claim, llm_available, str(uuid.uuid4()), now
            )
            for index in indices:
                results[index] = result

    await asyncio.gather(*(run(claim, indices) for claim, indices in pending.items()))
    return BatchCheckResponse(request_id=request_id, results=[r for r in results if r is not None])