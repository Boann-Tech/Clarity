"""Tests for LLM module — claim normalisation, passage classification, verdict synthesis.

These tests verify the deterministic fallbacks (no Bifrost API key = graceful degradation).
With `CLARITY_BIFROST_API_KEY` and a deployed-model alias set, they also exercise the LLM path.
"""

import os

from app.llm import (
    _deterministic_fallback,
    classify_passages,
    normalize_claim,
    synthesize_verdict,
)


# ── Claim Normalization ──


def test_normalize_claim_fallback_without_api_key():
    """Without API key, normalize_claim returns the raw claim as default."""
    result = normalize_claim("US inflation fell by 50% in 2024.")
    assert result["normalized_claim"] == "US inflation fell by 50% in 2024."
    assert result["checkable"] is True
    assert len(result["search_queries"]) >= 1
    assert "inflation" in result["search_queries"][0]


def test_normalize_claim_short():
    result = normalize_claim("Inflation is 3%.")
    assert result["normalized_claim"] == "Inflation is 3%."
    assert result["checkable"] is True


# ── Passage Classification ──


def test_classify_passages_empty():
    """Empty passages list returns empty list."""
    result = classify_passages("Test claim", [])
    assert result == []


def test_classify_passages_fallback():
    """Without API key, all passages default to 'context' relation."""
    passages = [
        {"index": 0, "text": "Inflation rose by 2.3% in May 2026.", "url": "https://example.com/1"},
        {"index": 1, "text": "The economy grew by 3% in Q2.", "url": "https://example.com/2"},
    ]
    result = classify_passages("Inflation is rising.", passages)
    assert len(result) == 2
    for p in result:
        assert p["relation"] == "context"
        assert p["llm_confidence"] == 0.5


# ── Verdict Synthesis ──


def test_synthesize_verdict_empty():
    """No passages → unverified."""
    result = synthesize_verdict("Test claim", [])
    assert result["verdict"] == "unverified"
    assert result["confidence"] == 0.0


def test_synthesize_verdict_fallback_supported():
    """LLM unavailable → deterministic fallback with qualifying sources."""
    passages = [
        {"tier": "primary", "relation": "context", "url": "https://who.int/doc", "text": "WHO report data."},
        {"tier": "fact_check", "relation": "context", "url": "https://reuters.com/factcheck", "text": "Reuters confirms."},
    ]
    result = synthesize_verdict("Health claim test", passages)
    assert result["verdict"] == "supported"
    assert result["confidence"] > 0.5


def test_synthesize_verdict_fallback_contradicted():
    """Contradicting evidence → contradicted verdict."""
    passages = [
        {"tier": "primary", "relation": "contradicts", "url": "https://bls.gov/data", "text": "BLS data contradicts claim."},
    ]
    result = synthesize_verdict("Economic claim test", passages)
    assert result["verdict"] == "contradicted"


def test_synthesize_verdict_fallback_mixed():
    """Mixed evidence → misleading."""
    passages = [
        {"tier": "primary", "relation": "supports", "url": "https://example.com/a", "text": "Supports."},
        {"tier": "fact_check", "relation": "contradicts", "url": "https://example.com/b", "text": "Contradicts."},
    ]
    result = synthesize_verdict("Mixed claim", passages)
    assert result["verdict"] == "misleading"


def test_synthesize_verdict_fallback_secondary_only():
    """Only secondary news → unverified with low confidence."""
    passages = [
        {"tier": "secondary_news", "relation": "supports", "url": "https://bbc.com/news", "text": "BBC report."},
    ]
    result = synthesize_verdict("News claim", passages)
    assert result["verdict"] == "unverified"
    assert result["confidence"] == 0.2


# ── Deterministic fallback (tested directly) ──


def test_deterministic_fallback_empty():
    result = _deterministic_fallback("test", [], [], [], 0)
    assert result["verdict"] == "unverified"
    assert result["confidence"] == 0.0


def test_deterministic_fallback_contradicted():
    result = _deterministic_fallback(
        "test",
        [{"tier": "primary", "relation": "contradicts"}],
        [],
        [{"tier": "primary", "relation": "contradicts"}],
        1,
    )
    assert result["verdict"] == "contradicted"


def test_deterministic_fallback_supported():
    result = _deterministic_fallback(
        "test",
        [{"tier": "primary", "relation": "supports"}],
        [{"tier": "primary", "relation": "supports"}],
        [],
        1,
    )
    assert result["verdict"] == "supported"