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
    monkeypatch.setattr(config.settings, "bifrost_api_key", None)
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


def test_health_does_not_leak_model(monkeypatch):
    monkeypatch.setattr(config.settings, "bifrost_api_key", None)
    body = TestClient(app).get("/api/health").json()
    assert "model" not in body
    assert body["model_configured"] is False


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