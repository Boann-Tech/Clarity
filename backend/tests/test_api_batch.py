from fastapi.testclient import TestClient

from app import config, main
from app.main import app


def _client():
    return TestClient(app, raise_server_exceptions=False)


async def _fake_retrieve(claim, max_sources=8, use_llm=False):
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


def _stub_llm(monkeypatch):
    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })
    monkeypatch.setattr(llm, "synthesize_verdict", lambda claim, passages: {
        "verdict": "supported", "confidence": 0.9, "explanation": "ok", "limitations": [],
    })


def test_batch_preserves_order_and_charges_uncached(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 10)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(main, "retrieve_evidence", _fake_retrieve)
    _stub_llm(monkeypatch)

    claims = [
        "Inflation fell to 2 percent in 2024.",
        "Unemployment rose to 9 percent in 2024.",
        "GDP grew by 1 percent in 2024.",
    ]
    body = _client().post("/api/check/batch", json={"claims": claims}).json()

    assert [result["claim"] for result in body["results"]] == claims
    assert all(result["assessment"]["verdict"] == "supported" for result in body["results"])


def test_batch_cache_hits_are_free_and_skip_retrieval(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)

    calls = {"retrieve": 0}

    async def counting_retrieve(*_args, **_kwargs):
        calls["retrieve"] += 1
        return []

    monkeypatch.setattr(main, "retrieve_evidence", counting_retrieve)
    _stub_llm(monkeypatch)

    payload = {"claims": ["Inflation fell to 2 percent in 2024."]}
    first = _client().post("/api/check/batch", json=payload)
    second = _client().post("/api/check/batch", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["retrieve"] == 1


def test_batch_deduplicates_repeated_claim_and_charges_once(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)

    calls = {"retrieve": 0}

    async def counting_retrieve(*_args, **_kwargs):
        calls["retrieve"] += 1
        return await _fake_retrieve(*_args, **_kwargs)

    monkeypatch.setattr(main, "retrieve_evidence", counting_retrieve)
    _stub_llm(monkeypatch)

    claim = "Inflation fell to 2 percent in 2024."
    response = _client().post("/api/check/batch", json={"claims": [claim, claim]})

    assert response.status_code == 200
    body = response.json()
    assert [result["claim"] for result in body["results"]] == [claim, claim]
    assert body["results"][0] == body["results"][1]
    assert calls["retrieve"] == 1


def test_batch_over_budget_returns_429(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 2)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    monkeypatch.setattr(main, "retrieve_evidence", _fake_retrieve)
    _stub_llm(monkeypatch)

    payload = {"claims": [
        "Inflation fell to 2 percent in 2024.",
        "Unemployment rose to 9 percent in 2024.",
        "GDP grew by 1 percent in 2024.",
    ]}
    assert _client().post("/api/check/batch", json=payload).status_code == 429


def test_batch_rejects_too_many_or_invalid_claims(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", None)
    too_many = {"claims": [f"Claim number {index} says something." for index in range(11)]}
    assert _client().post("/api/check/batch", json=too_many).status_code == 422
    short = {"claims": ["too short"]}
    assert _client().post("/api/check/batch", json=short).status_code == 422


def test_batch_requires_token(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", "secret")
    body = {"claims": ["Inflation fell to 2 percent in 2024."]}
    assert _client().post("/api/check/batch", json=body).status_code == 401