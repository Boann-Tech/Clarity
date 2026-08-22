"""Clarity API — FastAPI application.

Endpoints:
  POST /api/check    — Check a factual claim against curated evidence sources
  GET  /api/health   — Health check

Evidence-first invariant is enforced at the serialisation boundary:
no verdict without at least one qualifying citation URL.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.evidence import retrieve_evidence
from app.models import (
    Assessment,
    CheckRequest,
    CheckResponse,
    CitationSource,
    Verdict,
)
from app.verdict import calculate_verdict

logger = logging.getLogger("clarity.api")

app = FastAPI(
    title="Clarity API",
    version="3.0.0",
    description="Evidence-first claim verification. Uses DeepSeek Pro for claim normalization, passage classification, and verdict synthesis — always over retrieved sources.",
    docs_url="/docs",
)

# ── CORS ──

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0.0",
        "llm_enabled": settings.llm_enabled and bool(settings.deepseek_api_key),
        "model": settings.deepseek_model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/check")
async def check_claim(req: CheckRequest) -> CheckResponse:
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

    # Step 1: Normalise
    normalized_claim = " ".join(req.claim.split())
    llm_available = settings.llm_enabled and bool(settings.deepseek_api_key)

    # Step 1b: Optional LLM claim normalisation for better search queries
    search_queries = [normalized_claim]
    if llm_available:
        try:
            from app.llm import normalize_claim

            normalized = normalize_claim(normalized_claim)
            if normalized.get("checkable", True) is False:
                # LLM says this isn't a checkable factual claim
                return CheckResponse(
                    request_id=request_id,
                    claim=req.claim,
                    normalized_claim=normalized.get("normalized_claim", normalized_claim),
                    checked_at=now,
                    assessment=Assessment(
                        verdict=Verdict.not_checkable,
                        confidence=0.0,
                        explanation=normalized.get(
                            "reasoning",
                            "This appears to be an opinion, prediction, or value statement, not a checkable factual claim.",
                        ),
                    ),
                    citations=[],
                    limitations=["not_checkable"],
                    policy_version="3.0",
                )

            # Use LLM-generated search queries for better results
            llm_queries = normalized.get("search_queries", [])
            if llm_queries and llm_queries[0]:
                search_queries = llm_queries[:3]
                logger.info(
                    "LLM normalisation: %s → %s",
                    normalized_claim,
                    search_queries[0],
                )
        except Exception as e:
            logger.warning("LLM normalisation failed: %s — falling back to raw claim", e)

    # Step 2-4: Retrieve evidence with optional LLM passage classification
    all_citations = []
    for query in search_queries:
        batch = await retrieve_evidence(query, max_sources=settings.max_sources_per_claim, use_llm=llm_available)
        all_citations.extend(batch)

    # Deduplicate across queries
    seen_urls = set()
    citations = []
    for c in all_citations:
        url = c.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        citations.append(c)

    # Limit
    citations = citations[:settings.max_sources_per_claim]

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
                })

            llm_result = synthesize_verdict(normalized_claim, classified_passages)
            assessment = Assessment(
                verdict=llm_result.get("verdict", "unverified"),
                confidence=llm_result.get("confidence", 0.0),
                explanation=llm_result.get("explanation", ""),
            )
            llm_limitations = llm_result.get("limitations", [])
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
        qualifying = [c for c in citations if c.get("tier") in ("primary", "fact_check")]
        if not qualifying:
            assessment = Assessment(
                verdict=Verdict.unverified,
                confidence=0.0,
                explanation=(
                    "The available evidence could not be validated against "
                    "authoritative source requirements."
                ),
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
            title=c.get("title", "Untitled"),
            publisher=c.get("publisher", c.get("tier", "unknown")),
            url=c.get("url", ""),
            published_date=c.get("published_date"),
            accessed_at=c.get("accessed_at", now),
            tier=c.get("tier", "unknown"),
            snippet=c.get("snippet", "")[:800],
            relevance_score=min(c.get("relevance_score", 0.0), 1.0),
            retrieval_status=c.get("retrieval_status", "ok"),
        )
        for c in citations
        if c.get("url")
    ]

    return CheckResponse(
        request_id=request_id,
        claim=req.claim,
        normalized_claim=normalized_claim,
        checked_at=now,
        assessment=assessment,
        citations=formatted_citations,
        limitations=sorted(set(limitations)),
        policy_version="3.0",
    )