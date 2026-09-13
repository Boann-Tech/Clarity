"""Pluggable rate limiting for the public API.

In-memory sliding-window by default: per-process, exact within its own
process. When `CLARITY_REDIS_URL` is configured, `build_rate_limiter`
returns a Redis-backed limiter instead, so the limit is enforced across
every worker/replica rather than once per process. The Redis backend trades
sliding-window precision for two independent fixed windows (minute, hour)
via atomic `INCR`/`EXPIRE` — simpler to reason about and to run without a
Lua script, at the cost of the classic fixed-window boundary burst (up to
~2x the limit for requests that straddle a window edge).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque

logger = logging.getLogger("clarity.ratelimit")


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 10_000) -> None:
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def _evict_stale(self, now: float) -> None:
        while self._events:
            events = next(iter(self._events.values()))
            if events and now - events[-1] <= 3600:
                break
            self._events.popitem(last=False)

    async def allow_many(self, key: str, count: int, per_minute: int, per_hour: int) -> bool:
        """Check capacity for `count` events and append them atomically."""
        if count <= 0:
            return True
        now = time.monotonic()
        async with self._lock:
            self._evict_stale(now)
            events = self._events.get(key)
            if events is None:
                events = deque()
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and now - events[0] > 3600:
                events.popleft()
            minute_count = sum(1 for ts in events if now - ts <= 60)
            if minute_count + count > per_minute or len(events) + count > per_hour:
                if not events:
                    self._events.pop(key, None)
                return False
            events.extend([now] * count)
            return True

    async def allow(self, key: str, per_minute: int, per_hour: int) -> bool:
        return await self.allow_many(key, 1, per_minute, per_hour)

    def reset(self) -> None:
        self._events.clear()


class RedisRateLimiter:
    """Shared fixed-window rate limiter backed by Redis.

    A Redis outage fails *open* (requests are allowed) rather than closed —
    consistent with the cache's "never fail the request over the
    optimisation" stance. This means an unreachable Redis disables rate
    limiting entirely until it recovers; that's a deliberate availability
    trade-off, not an oversight, since the limiter is a cost/abuse guard, not
    a correctness requirement of a single request.
    """

    def __init__(self, client) -> None:
        self._client = client

    async def allow_many(self, key: str, count: int, per_minute: int, per_hour: int) -> bool:
        if count <= 0:
            return True
        now = int(time.time())
        minute_key = f"clarity:rl:{key}:m:{now // 60}"
        hour_key = f"clarity:rl:{key}:h:{now // 3600}"
        try:
            pipe = self._client.pipeline()
            pipe.incrby(minute_key, count)
            pipe.expire(minute_key, 60)
            pipe.incrby(hour_key, count)
            pipe.expire(hour_key, 3600)
            minute_total, _, hour_total, _ = await pipe.execute()
        except Exception as e:
            logger.warning("Redis rate limit check failed, failing open: %s", e)
            return True

        if int(minute_total) > per_minute or int(hour_total) > per_hour:
            # Roll back this reservation so a rejected request doesn't
            # permanently consume capacity it was never granted.
            try:
                pipe = self._client.pipeline()
                pipe.decrby(minute_key, count)
                pipe.decrby(hour_key, count)
                await pipe.execute()
            except Exception as e:
                logger.warning("Redis rate limit rollback failed: %s", e)
            return False
        return True

    async def allow(self, key: str, per_minute: int, per_hour: int) -> bool:
        return await self.allow_many(key, 1, per_minute, per_hour)

    def reset(self) -> None:
        # Not implemented: clearing arbitrary window keys needs a SCAN sweep
        # that isn't safe to run casually against a shared limiter. Only
        # used by tests against the in-memory default, so this is never
        # exercised in the Redis-backed path.
        logger.warning("RedisRateLimiter.reset() is a no-op — restart or flush Redis directly.")


def build_rate_limiter() -> SlidingWindowLimiter | RedisRateLimiter:
    """Build the configured rate-limiter backend.

    Falls back to the in-memory limiter when `CLARITY_REDIS_URL` is unset,
    the `redis` package isn't installed, or the client can't be constructed.
    """
    from app.config import settings

    if not settings.redis_url:
        return SlidingWindowLimiter()
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        logger.warning(
            "CLARITY_REDIS_URL is set but the 'redis' package is not installed — "
            "falling back to the in-memory rate limiter. Run: pip install redis"
        )
        return SlidingWindowLimiter()
    try:
        client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    except Exception as e:
        logger.warning("Failed to build Redis client (%s) — falling back to in-memory rate limiter.", e)
        return SlidingWindowLimiter()
    return RedisRateLimiter(client)