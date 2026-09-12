"""Tests for LLM module — claim normalisation, passage classification, verdict synthesis.

These tests verify the deterministic fallbacks (no Bifrost API key = graceful degradation).
With `CLARITY_BIFROST_API_KEY` and a deployed-model alias set, they also exercise the LLM path.
"""

import json

from app.llm import (
    _deterministic_fallback,
    classify_passages,
    normalize_claim,
    synthesize_verdict,
)


# ── Claim Normalization ──


def test_normalize_claim_fallback_without_api_key(monkeypatch):
    """An unavailable gateway returns a safe raw-claim normalization."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    result = normalize_claim("US inflation fell by 50% in 2024.")
    assert result["normalized_claim"] == "US inflation fell by 50% in 2024."
    assert result["checkable"] is True
    assert len(result["search_queries"]) >= 1
    assert "inflation" in result["search_queries"][0]


def test_normalize_claim_short(monkeypatch):
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    result = normalize_claim("Inflation is 3%.")
    assert result["normalized_claim"] == "Inflation is 3%."
    assert result["checkable"] is True


# ── Passage Classification ──


def test_classify_passages_empty():
    """Empty passages list returns empty list."""
    result = classify_passages("Test claim", [])
    assert result == []


def test_classify_passages_fallback(monkeypatch):
    """An unavailable gateway defaults passages to context."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    passages = [
        {"index": 0, "text": "Inflation rose by 2.3% in May 2026.", "url": "https://example.com/1"},
        {"index": 1, "text": "The economy grew by 3% in Q2.", "url": "https://example.com/2"},
    ]
    result = classify_passages("Inflation is rising.", passages)
    assert len(result) == 2
    for p in result:
        assert p["relation"] == "context"
        assert p["llm_confidence"] == 0.5


def test_classify_passages_accepts_bifrost_passages_response(monkeypatch):
    """Bifrost models may wrap classifications in a `passages` array."""
    from app import llm

    monkeypatch.setattr(
        llm,
        "_call_llm",
        lambda *args, **kwargs: '''{
          "passages": [{
            "index": 0,
            "relation": "irrelevant",
            "confidence": 1,
            "reasoning": "Generic Reuters landing page; no inflation data."
          }]
        }''',
    )
    passages = [{
        "index": 0,
        "text": "Reuters delivers news from around the world.",
        "url": "https://www.reuters.com/world/us/",
        "tier": "fact_check",
    }]

    result = llm.classify_passages("US inflation fell by 50% in 2024.", passages)

    assert result[0]["relation"] == "irrelevant"
    assert result[0]["llm_confidence"] == 1.0
    assert result[0]["reasoning"] == "Generic Reuters landing page; no inflation data."


# ── Verdict Synthesis ──


def test_synthesize_verdict_empty():
    """No passages → unverified."""
    result = synthesize_verdict("Test claim", [])
    assert result["verdict"] == "unverified"
    assert result["confidence"] == 0.0


def test_synthesize_verdict_json_array_falls_back(monkeypatch):
    from app import llm

    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: '["not", "a", "dict"]')
    result = llm.synthesize_verdict("Claim text", [
        {"tier": "primary", "relation": "supports", "url": "https://who.int/x", "text": "T", "retrieval_status": "ok"}
    ])
    assert result["verdict"] == "supported"


def test_synthesize_verdict_null_limitations(monkeypatch):
    from app import llm

    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: json.dumps({
        "verdict": "supported", "confidence": 0.9, "explanation": "ok",
        "limitations": None, "domain": "not_a_domain",
    }))
    result = llm.synthesize_verdict("Claim text", [
        {"tier": "primary", "relation": "supports", "url": "https://who.int/x", "text": "T", "retrieval_status": "ok"}
    ])
    assert result["limitations"] == []
    assert result["domain"] is None


def test_synthesize_verdict_misleading_requires_conflicting_hosts(monkeypatch):
    from app import llm

    monkeypatch.setattr(llm, "_call_llm", lambda *a, **k: json.dumps({
        "verdict": "misleading", "confidence": 0.8, "explanation": "mixed",
    }))
    result = llm.synthesize_verdict("Claim text", [
        {"tier": "fact_check", "relation": "supports", "url": "https://reuters.com/a", "snippet": "A", "retrieval_status": "ok"},
        {"tier": "fact_check", "relation": "contradicts", "url": "https://reuters.com/b", "snippet": "B", "retrieval_status": "ok"},
        {"tier": "primary", "relation": "context", "url": "https://who.int/c", "snippet": "C", "retrieval_status": "ok"},
    ])
    assert result["verdict"] == "unverified"


def test_synthesize_verdict_fallback_supported(monkeypatch):
    """LLM unavailable → deterministic fallback with qualifying sources."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    passages = [
        {"tier": "primary", "relation": "supports", "url": "https://who.int/doc", "text": "WHO report data.", "snippet": "WHO report data."},
        {"tier": "fact_check", "relation": "supports", "url": "https://reuters.com/factcheck", "text": "Reuters confirms.", "snippet": "Reuters confirms."},
    ]
    result = synthesize_verdict("Health claim test", passages)
    assert result["verdict"] == "supported"
    assert result["confidence"] > 0.5


def test_synthesize_verdict_cannot_label_checkable_claim_not_checkable(monkeypatch):
    """Only claim normalization can decide checkability, never evidence synthesis."""
    from app import llm

    monkeypatch.setattr(
        llm,
        "_call_llm",
        lambda *args, **kwargs: """{
          "verdict": "not_checkable",
          "confidence": 1.0,
          "explanation": "The passages do not address the claim."
        }""",
    )
    result = llm.synthesize_verdict(
        "US inflation fell by 50% in 2024.",
        [{
            "tier": "primary",
            "relation": "irrelevant",
            "url": "https://www.cso.ie/en/statistics/prices/consumerpriceindex/",
            "text": "Irish CPI data.",
        }],
    )

    assert result["verdict"] == "unverified"
    assert result["confidence"] == 0.0


def test_synthesize_verdict_fallback_contradicted(monkeypatch):
    """Contradicting evidence → contradicted verdict."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    passages = [
        {"tier": "primary", "relation": "contradicts", "url": "https://bls.gov/data", "text": "BLS data contradicts claim.", "snippet": "BLS data contradicts claim."},
    ]
    result = synthesize_verdict("Economic claim test", passages)
    assert result["verdict"] == "contradicted"


def test_synthesize_verdict_fallback_mixed(monkeypatch):
    """Mixed evidence → misleading."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    passages = [
        {"tier": "primary", "relation": "supports", "url": "https://reuters.com/a", "text": "Supports.", "snippet": "Supports."},
        {"tier": "fact_check", "relation": "contradicts", "url": "https://apnews.com/b", "text": "Contradicts.", "snippet": "Contradicts."},
    ]
    result = synthesize_verdict("Mixed claim", passages)
    assert result["verdict"] == "misleading"


def test_synthesize_verdict_fallback_secondary_only(monkeypatch):
    """Only secondary news → unverified with low confidence."""
    from app import llm
    monkeypatch.setattr(llm, "_call_llm", lambda *args, **kwargs: None)
    passages = [
        {"tier": "secondary_news", "relation": "supports", "url": "https://bbc.com/news", "text": "BBC report.", "snippet": "BBC report."},
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
        [{"tier": "primary", "relation": "contradicts", "url": "https://bls.gov/data", "snippet": "BLS data."}],
        [],
        [{"tier": "primary", "relation": "contradicts", "url": "https://bls.gov/data", "snippet": "BLS data."}],
        1,
    )
    assert result["verdict"] == "contradicted"


def test_deterministic_fallback_supported():
    result = _deterministic_fallback(
        "test",
        [{"tier": "primary", "relation": "supports", "url": "https://who.int/x", "snippet": "WHO data."}],
        [{"tier": "primary", "relation": "supports", "url": "https://who.int/x", "snippet": "WHO data."}],
        [],
        1,
    )
    assert result["verdict"] == "supported"