"""Verdict calculation from gathered evidence.

Rules:
  - supported: ≥1 fetched qualifying source (primary or fact_check) supporting the claim
  - contradicted: ≥1 fetched qualifying source contradicting the claim
  - misleading: both support and contradiction, from ≥2 distinct publisher hosts
  - unverified: no fetched qualifying sources, or only context/unknown relations
  - not_checkable: opinion, prediction, value judgment (called by LLM in Phase 3)

Evidence-first invariant enforced at serialisation boundary in main.py.
"""

from __future__ import annotations

from app.models import Assessment, Verdict
from app.sources import url_host


def qualifying_citations(citations: list[dict]) -> list[dict]:
    return [
        c
        for c in citations
        if c.get("tier") in ("primary", "fact_check")
        and c.get("retrieval_status", "ok") == "ok"
        and str(c.get("snippet") or c.get("text") or "").strip()
    ]


def calculate_verdict(
    citations: list[dict],
    domain: str | None = None,
) -> Assessment:
    """Determine verdict based on gathered, classified citations.

    Args:
        citations: List of citation dicts (already classified with 'tier').
        domain: Optional claim domain hint.

    Returns:
        Assessment with verdict, confidence, explanation.
    """
    qualifying = qualifying_citations(citations)
    secondary = [c for c in citations if c.get("tier") == "secondary_news"]

    if not qualifying:
        if secondary:
            return Assessment(
                verdict=Verdict.unverified,
                confidence=0.2,
                explanation=(
                    f"Found {len(secondary)} source(s) from secondary news, but no "
                    "primary or fact-check sources. More authoritative evidence is needed."
                ),
            )
        return Assessment(
            verdict=Verdict.unverified,
            confidence=0.0,
            explanation="No fetched, qualifying citations could be retrieved for this claim.",
        )

    supports = [c for c in qualifying if c.get("relation") == "supports"]
    contradicts = [c for c in qualifying if c.get("relation") == "contradicts"]
    hosts = {url_host(c.get("url", "")) for c in supports + contradicts}
    primary_count = sum(1 for c in qualifying if c.get("tier") == "primary")

    base_confidence = min(0.5 + (len(qualifying) * 0.08), 0.92)
    if primary_count >= 2:
        base_confidence = min(base_confidence + 0.1, 0.95)

    if contradicts and not supports:
        return Assessment(
            verdict=Verdict.contradicted,
            confidence=round(base_confidence, 2),
            explanation=f"Found {len(contradicts)} qualifying source(s) contradicting this claim.",
        )
    if supports and contradicts:
        if len(hosts) >= 2:
            return Assessment(
                verdict=Verdict.misleading,
                confidence=round(base_confidence * 0.8, 2),
                explanation=(
                    f"Evidence is mixed: {len(supports)} source(s) support and "
                    f"{len(contradicts)} contradict. The picture is more nuanced than stated."
                ),
            )
        return Assessment(
            verdict=Verdict.unverified,
            confidence=0.0,
            explanation=(
                "Conflicting evidence comes from a single publisher; at least two "
                "independent sources are required for a misleading verdict."
            ),
        )
    if supports:
        return Assessment(
            verdict=Verdict.supported,
            confidence=round(base_confidence, 2),
            explanation=f"Found {len(supports)} qualifying source(s) supporting this claim.",
        )

    return Assessment(
        verdict=Verdict.unverified,
        confidence=0.0,
        explanation=(
            "Fetched, qualifying sources were found but none could be classified as "
            "supporting or contradicting this claim."
        ),
    )
