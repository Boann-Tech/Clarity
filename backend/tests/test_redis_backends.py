"""Tests for the optional Redis-backed cache and rate-limiter."""

import asyncio

from app import config
from app.cache import RedisResponseCache, build_response_cache
from app.ratelimit import RedisRateLimiter, build_rate_limiter
from fake_redis import FakeRedisClient


def _run(coro):
    return asyncio.run(coro)


# ── RedisResponseCache ──


def test_redis_cache_roundtrip(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    cache = RedisResponseCache(FakeRedisClient())
    assert _run(cache.get("k")) is None
    _run(cache.set("k", {"v": 1}))
    assert _run(cache.get("k")) == {"v": 1}


def test_redis_cache_skips_write_when_ttl_not_positive(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 0)
    cache = RedisResponseCache(FakeRedisClient())
    _run(cache.set("k", {"v": 1}))
    assert _run(cache.get("k")) is None


def test_redis_cache_read_failure_is_a_miss_not_an_exception(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    cache = RedisResponseCache(FakeRedisClient(fail=True))
    assert _run(cache.get("k")) is None


def test_redis_cache_write_failure_is_silent(monkeypatch):
    monkeypatch.setattr(config.settings, "cache_ttl_seconds", 60)
    cache = RedisResponseCache(FakeRedisClient(fail=True))
    # Must not raise.
    _run(cache.set("k", {"v": 1}))


# ── RedisRateLimiter ──


def test_redis_rate_limiter_allows_until_minute_limit():
    limiter = RedisRateLimiter(FakeRedisClient())
    assert _run(limiter.allow_many("client", 3, per_minute=3, per_hour=100)) is True
    assert _run(limiter.allow_many("client", 1, per_minute=3, per_hour=100)) is False


def test_redis_rate_limiter_rejection_does_not_consume_capacity():
    """A rejected reservation must be rolled back so it doesn't permanently
    eat into the caller's remaining budget.
    """
    limiter = RedisRateLimiter(FakeRedisClient())
    assert _run(limiter.allow_many("client", 8, per_minute=10, per_hour=100)) is True
    # 8 + 5 = 13 > 10: rejected. If this weren't rolled back, the next
    # request would see 13 already reserved instead of 8.
    assert _run(limiter.allow_many("client", 5, per_minute=10, per_hour=100)) is False
    assert _run(limiter.allow_many("client", 2, per_minute=10, per_hour=100)) is True


def test_redis_rate_limiter_enforces_hour_limit_independently():
    limiter = RedisRateLimiter(FakeRedisClient())
    assert _run(limiter.allow_many("client", 5, per_minute=100, per_hour=5)) is True
    assert _run(limiter.allow_many("client", 1, per_minute=100, per_hour=5)) is False


def test_redis_rate_limiter_fails_open_on_outage():
    limiter = RedisRateLimiter(FakeRedisClient(fail=True))
    assert _run(limiter.allow_many("client", 1, per_minute=1, per_hour=1)) is True


# ── Factories fall back to in-memory ──


def test_build_response_cache_defaults_to_in_memory(monkeypatch):
    monkeypatch.setattr(config.settings, "redis_url", None)
    cache = build_response_cache()
    assert type(cache).__name__ == "ResponseCache"


def test_build_response_cache_falls_back_without_redis_package(monkeypatch):
    # The `redis` package is not a project dependency, so this exercises the
    # real ImportError fallback path, not a simulated one.
    monkeypatch.setattr(config.settings, "redis_url", "redis://localhost:6379/0")
    cache = build_response_cache()
    assert type(cache).__name__ == "ResponseCache"


def test_build_rate_limiter_defaults_to_in_memory(monkeypatch):
    monkeypatch.setattr(config.settings, "redis_url", None)
    limiter = build_rate_limiter()
    assert type(limiter).__name__ == "SlidingWindowLimiter"


def test_build_rate_limiter_falls_back_without_redis_package(monkeypatch):
    monkeypatch.setattr(config.settings, "redis_url", "redis://localhost:6379/0")
    limiter = build_rate_limiter()
    assert type(limiter).__name__ == "SlidingWindowLimiter"
