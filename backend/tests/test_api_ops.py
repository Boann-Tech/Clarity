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

    monkeypatch.setattr(main, "retrieve_evidence_multi", no_evidence)
    main._rate_limiter.reset()
    main._response_cache.clear()
    yield
    main._rate_limiter.reset()
    main._response_cache.clear()


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host, headers=None):
        self.client = _FakeClient(host) if host else None
        self.headers = headers or {}


def test_client_ip_ignores_forwarded_header_by_default(monkeypatch):
    from app.main import _client_ip

    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 0)
    request = _FakeRequest("203.0.113.9", {"x-forwarded-for": "198.51.100.1"})
    assert _client_ip(request) == "203.0.113.9"


def test_client_ip_uses_forwarded_header_when_trusted(monkeypatch):
    from app.main import _client_ip

    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 1)
    # A client can put anything in a self-sent X-Forwarded-For ("6.6.6.6");
    # our single trusted proxy (nginx) appends the real peer IP it saw to
    # the end of the header, so with 1 trusted hop the rightmost entry is
    # the one to trust.
    request = _FakeRequest("10.0.0.5", {"x-forwarded-for": "6.6.6.6, 203.0.113.7"})
    assert _client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_when_header_missing_expected_hops(monkeypatch):
    from app.main import _client_ip

    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 3)
    request = _FakeRequest("10.0.0.5", {"x-forwarded-for": "198.51.100.1, 10.0.0.5"})
    assert _client_ip(request) == "10.0.0.5"


def test_client_ip_handles_missing_client(monkeypatch):
    from app.main import _client_ip

    monkeypatch.setattr(config.settings, "trusted_proxy_hops", 0)
    assert _client_ip(_FakeRequest(None)) == "unknown"


def test_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    first = {"claim": "Inflation fell to 2 percent in 2024."}
    second = {"claim": "Unemployment rose to 9 percent in 2024."}
    assert client.post("/api/check", json=first).status_code == 200
    assert client.post("/api/check", json=second).status_code == 429


def test_cache_hit_does_not_consume_rate_limit(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}
    assert client.post("/api/check", json=payload).status_code == 200
    assert client.post("/api/check", json=payload).status_code == 200
    assert client.post("/api/check", json=payload).status_code == 200


def test_rejected_request_does_not_consume(monkeypatch):
    from app import main

    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    assert client.post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."}).status_code == 200
    assert client.post("/api/check", json={"claim": "Unemployment rose to 9 percent in 2024."}).status_code == 429
    events = sum(len(queue) for queue in main._rate_limiter._events.values())
    assert events == 1


def test_allow_many_is_atomic():
    from app.ratelimit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter()

    async def run():
        assert await limiter.allow_many("k", 3, 10, 100) is True
        assert await limiter.allow_many("k", 8, 10, 100) is False
        assert await limiter.allow_many("k", 0, 10, 100) is True
        return len(limiter._events["k"])

    assert asyncio.run(run()) == 3


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


def test_metrics_tracks_cache_hit_and_miss(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    payload = {"claim": "Inflation fell to 2 percent in 2024."}

    client.post("/api/check", json=payload)  # miss
    client.post("/api/check", json=payload)  # hit

    body = client.get("/api/metrics").json()
    assert body["counters"]["cache_miss"] == 1
    assert body["counters"]["cache_hit"] == 1


def test_metrics_tracks_verdict_distribution(monkeypatch):
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    client.post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})

    body = client.get("/api/metrics").json()
    # No LLM, no evidence (stubbed by the module fixture) → deterministic unverified.
    assert body["counters"]["verdict:unverified"] == 1


def test_metrics_tracks_rate_limited_requests(monkeypatch):
    monkeypatch.setattr(config.settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(config.settings, "rate_limit_per_hour", 100)
    monkeypatch.setattr(config.settings, "api_token", None)
    client = TestClient(app)
    client.post("/api/check", json={"claim": "Inflation fell to 2 percent in 2024."})
    client.post("/api/check", json={"claim": "Unemployment rose to 9 percent in 2024."})

    body = client.get("/api/metrics").json()
    assert body["counters"]["rate_limited"] == 1


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
    asyncio.run(cache.set("a", {"v": 1}))
    assert asyncio.run(cache.get("a")) == {"v": 1}
    asyncio.run(cache.set("b", {"v": 2}))
    asyncio.run(cache.set("c", {"v": 3}))
    assert asyncio.run(cache.get("a")) is None


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

    monkeypatch.setattr(main, "retrieve_evidence_multi", counting_retrieve)

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