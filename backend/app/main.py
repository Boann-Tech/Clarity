"""Clarity API — FastAPI application.

Endpoints:
  POST /api/check    — Check a factual claim against curated evidence sources
  GET  /api/health   — Health check
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
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

app = FastAPI(
    title="Clarity API",
    version="2.0.0",
    description="Evidence-first claim verification. Finds authoritative sources and presents transparent assessments.",
    docs_url="/docs",
)

# ── CORS ──

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# ── Health ──


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Claim check ──


@app.post("/api/check")
async def check_claim(req: CheckRequest) -> CheckResponse:
    """Check a factual claim against curated evidence sources.

    The evidence-before-verdict invariant is enforced here: if no qualifying
    citations are found, the verdict is always "unverified" with confidence 0.
    """
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Normalise
    normalized_claim = " ".join(req.claim.split())

    # Retrieve evidence
    citations = await retrieve_evidence(normalized_claim)

    # Calculate verdict
    assessment = calculate_verdict(citations)

    # Evidence-first invariant: enforce at serialisation boundary
    if assessment.verdict in (Verdict.supported, Verdict.contradicted, Verdict.misleading):
        qualifying = [c for c in citations if c.get("tier") in ("primary", "fact_check")]
        if not qualifying:
            # Downgrade: evidence was lost or degraded between retrieval and verdict
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
    if not citations:
        limitations.append("no_sources_found")
    elif not any(c.get("tier") in ("primary", "fact_check") for c in citations):
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
        limitations=limitations,
        policy_version="2.0",
    )