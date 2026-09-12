from fastapi.testclient import TestClient

from app import main
from app.main import app


def _client():
    return TestClient(app, raise_server_exceptions=False)


def _fake_retrieve(claim, max_sources=8, use_llm=False):
    async def _inner(*_args, **_kwargs):
        return [{
            "title": "Reuters fact check",
            "publisher": "reuters.com",
            "url": "https://reuters.com/x",
            "snippet": "Passage text.",
            "tier": "fact_check",
            "accessed_at": "2024-01-01T00:00:00Z",
            "relevance_score": 1.0,
            "retrieval_status": "ok",
            "relation": "supports",
        }]
    return _inner()


def test_null_limitations_does_not_500(monkeypatch, llm_enabled):
    monkeypatch.setattr(main, "retrieve_evidence", _fake_retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "supported", "confidence": 0.9, "explanation": "ok",
        "limitations": None, "domain": "economics_finance",
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    assert response.json()["assessment"]["domain"] == "economics_finance"


def test_null_snippet_and_long_title_are_coerced(monkeypatch, llm_enabled):
    async def retrieve(*_args, **_kwargs):
        return [{
            "title": None, "publisher": None, "url": "https://reuters.com/x", "snippet": None,
            "tier": "fact_check", "retrieval_status": "ok", "relation": "supports",
        }]

    monkeypatch.setattr(main, "retrieve_evidence", retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "supported", "confidence": "0.9", "explanation": "x" * 5000, "limitations": [],
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    body = response.json()
    assert body["citations"][0]["title"] == "Untitled"
    assert len(body["assessment"]["explanation"]) <= 600


def test_context_host_cannot_independently_support_misleading(monkeypatch, llm_enabled):
    async def retrieve(*_args, **_kwargs):
        return [
            {"title": "A", "publisher": "reuters.com", "url": "https://reuters.com/a", "snippet": "A", "tier": "fact_check", "retrieval_status": "ok", "relation": "supports"},
            {"title": "B", "publisher": "reuters.com", "url": "https://reuters.com/b", "snippet": "B", "tier": "fact_check", "retrieval_status": "ok", "relation": "contradicts"},
            {"title": "C", "publisher": "who.int", "url": "https://who.int/c", "snippet": "C", "tier": "primary", "retrieval_status": "ok", "relation": "context"},
        ]

    monkeypatch.setattr(main, "retrieve_evidence", retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "misleading", "confidence": 0.8, "explanation": "mixed", "limitations": [],
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    assert response.json()["assessment"]["verdict"] == "unverified"


def test_subdomain_citations_cannot_support_misleading(monkeypatch, llm_enabled):
    async def retrieve(*_args, **_kwargs):
        return [
            {"title": "A", "publisher": "reuters.com", "url": "https://www.reuters.com/a", "snippet": "A", "tier": "fact_check", "retrieval_status": "ok", "relation": "supports"},
            {"title": "B", "publisher": "reuters.com", "url": "https://jp.reuters.com/b", "snippet": "B", "tier": "fact_check", "retrieval_status": "ok", "relation": "contradicts"},
            {"title": "C", "publisher": "who.int", "url": "https://who.int/c", "snippet": "C", "tier": "primary", "retrieval_status": "ok", "relation": "context"},
        ]

    monkeypatch.setattr(main, "retrieve_evidence", retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "misleading", "confidence": 0.8, "explanation": "mixed", "limitations": [],
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    assert response.json()["assessment"]["verdict"] == "unverified"


def test_distinct_publishers_keep_misleading_verdict(monkeypatch, llm_enabled):
    async def retrieve(*_args, **_kwargs):
        return [
            {"title": "A", "publisher": "reuters.com", "url": "https://reuters.com/a", "snippet": "A", "tier": "fact_check", "retrieval_status": "ok", "relation": "supports"},
            {"title": "B", "publisher": "apnews.com", "url": "https://apnews.com/b", "snippet": "B", "tier": "fact_check", "retrieval_status": "ok", "relation": "contradicts"},
            {"title": "C", "publisher": "who.int", "url": "https://who.int/c", "snippet": "C", "tier": "primary", "retrieval_status": "ok", "relation": "context"},
        ]

    monkeypatch.setattr(main, "retrieve_evidence", retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "misleading", "confidence": 0.8, "explanation": "mixed", "limitations": [],
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    assert response.json()["assessment"]["verdict"] == "misleading"


def test_misleading_requires_support_and_contradiction_at_boundary(monkeypatch, llm_enabled):
    async def retrieve(*_args, **_kwargs):
        return [
            {"title": "A", "publisher": "reuters.com", "url": "https://reuters.com/a", "snippet": "A", "tier": "fact_check", "retrieval_status": "ok", "relation": "supports"},
            {"title": "B", "publisher": "apnews.com", "url": "https://apnews.com/b", "snippet": "B", "tier": "fact_check", "retrieval_status": "ok", "relation": "supports"},
        ]

    monkeypatch.setattr(main, "retrieve_evidence", retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "misleading", "confidence": 0.8, "explanation": "mixed", "limitations": [],
    })

    response = _client().post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    assert response.status_code == 200
    assert response.json()["assessment"]["verdict"] == "unverified"
