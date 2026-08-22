"""Verdict calculation from gathered evidence.

Rules:
  - supported: ≥1 qualifying source (primary or fact_check), no material contradiction
  - contradicted: ≥1 qualifying source contradicting the claim
  - misleading: ≥2 qualifying sources that provide missing context
  - unverified: no qualifying sources, or sources are secondary_news/unknown only
  - not_checkable: opinion, prediction, value judgment (called by LLM in Phase 3)

Evidence-first invariant enforced at serialisation boundary in main.py.
"""

from __future__ import annotations

from app.models import Assessment, SourceTier, Verdict


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
    if not citations:
        return Assessment(
            verdict=Verdict.unverified,
            confidence=0.0,
            explanation="No validated citations could be retrieved for this claim.",
        )

    # Separate qualifying vs non-qualifying sources
    tier_rank = {
        "primary": 3,
        "fact_check": 2,
        "secondary_news": 1,
        "unknown": 0,
    }

    qualifying = [c for c in citations if tier_rank.get(c.get("tier", ""), 0) >= 2]
    secondary = [c for c in citations if tier_rank.get(c.get("tier", ""), 0) == 1]
    weak = [c for c in citations if tier_rank.get(c.get("tier", ""), 0) == 0]

    if not qualifying:
        if secondary:
            return Assessment(
                verdict=Verdict.unverified,
                confidence=0.2,
                explanation=(
                    f"Found {len(secondary)} source(s) from secondary news, "
                    "but no primary or fact-check sources. More authoritative "
                    "evidence is needed for a confident assessment."
                ),
            )
        if weak:
            return Assessment(
                verdict=Verdict.unverified,
                confidence=0.0,
                explanation=(
                    "The sources found could not be verified as authoritative. "
                    "No citation from a trusted fact-check or primary source."
                ),
            )
        return Assessment(
            verdict=Verdict.unverified,
            confidence=0.0,
            explanation="No validated citations could be retrieved for this claim.",
        )

    # We have qualifying sources — check for agreement patterns
    # For MVP: if all qualifying sources agree, that determines the verdict.
    top_tier = max(tier_rank.get(c.get("tier", ""), 0) for c in qualifying)
    primary_count = sum(1 for c in qualifying if c.get("tier") == "primary")
    fact_check_count = sum(1 for c in qualifying if c.get("tier") == "fact_check")

    n_qualifying = len(qualifying)

    # Confidence scales with quantity and quality of qualifying sources
    base_confidence = min(0.5 + (n_qualifying * 0.08), 0.92)
    if primary_count >= 2:
        base_confidence = min(base_confidence + 0.1, 0.95)
    if top_tier == 3:  # primary
        base_confidence = min(base_confidence + 0.05, 0.95)

    # For the MVP, we default to supported for qualifying evidence
    # Phase 4 will add LLM-based contradiction/misleading classification
    if n_qualifying >= 2 and primary_count >= 1:
        return Assessment(
            verdict=Verdict.supported,
            confidence=round(base_confidence, 2),
            explanation=(
                f"Found {n_qualifying} qualifying source(s) including "
                f"{primary_count} primary source(s) and {fact_check_count} "
                f"fact-check source(s). The available evidence supports "
                f"this claim."
            ),
        )

    if n_qualifying >= 1:
        return Assessment(
            verdict=Verdict.supported,
            confidence=round(base_confidence, 2),
            explanation=(
                f"Found {n_qualifying} qualifying source(s) "
                f"({primary_count} primary, {fact_check_count} fact-check). "
                f"The available evidence is consistent with this claim."
            ),
        )

    # Fallback — should not reach here if qualifying is non-empty
    return Assessment(
        verdict=Verdict.unverified,
        confidence=0.0,
        explanation="Could not form a confident assessment from the available evidence.",
    )