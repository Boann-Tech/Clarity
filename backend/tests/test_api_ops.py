import asyncio

import pytest
from fastapi.testclient import TestClient

from app import config
from app.cache import ResponseCache
from app.main import app
from app.ratelimit import SlidingWindowLimiter


@pytest.fixture(autouse=True)
def _offline_and_reset(monkeypatch):
    from app import main

    async def no_evidence(*_args, **_kwargs):
        return []

    monkeypatch.setattr(main, "retrieve_evidence", no_evidence)
    main._rate_limiter.reset()
    main._response_cache.clear()
    yield
    main._rate_limiter.reset()
    main._response_cache.clear()


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    assert client.post("/api/check", json=payload).status_code == 200
    assert client.post("/api/check", json=payload).status_code == 429


def test_api_token_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", "secret-token")
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    assert client.post("/api/check", json=payload).status_code == 401
    ok = client.post("/api/check", json=payload, headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200


def test_health_does_not_leak_model():
    body = TestClient(app).get("/api/health").json()
    assert "model" not in body
    assert "gateway" not in body
    assert body["model_configured"] is False
    assert body["provider"] == "none"


def test_health_reports_enabled_llm(llm_enabled):
    body = TestClient(app).get("/api/health").json()
    assert body["llm_enabled"] is True
    assert body["provider"] == "custom"
    assert body["model_configured"] is True
    assert "model" not in body
    assert "gateway" not in body


def test_cache_returns_same_request_id(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    first = client.post("/api/check", json=payload).json()
    second = client.post("/api/check", json=payload).json()
    assert first["request_id"] == second["request_id"]


def test_response_cache_expires_and_bounds():
    cache = ResponseCache(max_entries=2)
    cache.set("a", {"v": 1})
    assert cache.get("a") == {"v": 1}
    cache.set("b", {"v": 2})
    cache.set("c", {"v": 3})
    assert cache.get("a") is None


def test_not_checkable_cache_hit_uses_canonical_key(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(config.settings, "api_token", None)

    calls = {"normalize": 0}

    def fake_normalize(claim):
        calls["normalize"] += 1
        return {
            "normalized_claim": "Rewritten normalized text",
            "checkable": False,
            "reasoning": "value statement",
            "search_queries": [claim],
        }

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", fake_normalize)

    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    first = client.post("/api/check", json=payload).json()
    second = client.post("/api/check", json=payload).json()

    assert first["assessment"]["verdict"] == "not_checkable"
    assert first["normalized_claim"] == "Rewritten normalized text"
    assert first["request_id"] == second["request_id"]
    assert calls["normalize"] == 1


def test_cache_hit_skips_evidence_retrieval(monkeypatch, llm_enabled):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(config.settings, "api_token", None)

    from app import main

    calls = {"retrieve": 0}

    async def counting_retrieve(*_args, **_kwargs):
        calls["retrieve"] += 1
        return []

    monkeypatch.setattr(main, "retrieve_evidence", counting_retrieve)

    import app.llm as llm

    monkeypatch.setattr(llm, "normalize_claim", lambda claim: {
        "normalized_claim": claim, "checkable": True, "search_queries": [claim]
    })

    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    first = client.post("/api/check", json=payload).json()
    second = client.post("/api/check", json=payload).json()

    assert first["request_id"] == second["request_id"]
    assert calls["retrieve"] == 1


def test_rate_limiter_bounds_key_state():
    limiter = SlidingWindowLimiter(max_keys=8)

    async def hammer():
        for i in range(100):
            await limiter.allow(f"client-{i}", 10, 100)

    asyncio.run(hammer())

    assert len(limiter._events) <= 8


def test_rate_limiter_evicts_stale_keys(monkeypatch):
    class _Clock:
        def __init__(self):
            self.now = 1000.0

        def monotonic(self):
            return self.now

    clock = _Clock()
    monkeypatch.setattr("app.ratelimit.time", clock)

    limiter = SlidingWindowLimiter()
    asyncio.run(limiter.allow("a", 10, 100))
    asyncio.run(limiter.allow("b", 10, 100))
    assert set(limiter._events) == {"a", "b"}

    clock.now += 3601.0
    asyncio.run(limiter.allow("c", 10, 100))

    assert set(limiter._events) == {"c"}