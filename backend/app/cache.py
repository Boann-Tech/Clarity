"""Pluggable TTL cache for completed claim checks.

In-memory by default: per-process, bounded, TTL-expiring. When
`CLARITY_REDIS_URL` is configured, `build_response_cache` returns a
Redis-backed cache instead, so a claim checked by one worker is a cache hit
on every other worker/replica rather than a per-process miss. The `redis`
package is optional and imported lazily — if it isn't installed, or the
client can't be constructed, Clarity logs a warning and falls back to the
in-memory cache rather than failing to start.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger("clarity.cache")


class ResponseCache:
    """In-memory TTL cache, bounded to `max_entries` (oldest-inserted evicted first)."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, dict]] = {}

    async def get(self, key: str) -> dict | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._entries.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: dict, ttl_seconds: float | None = None) -> None:
        from app.config import settings

        ttl = settings.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        if key in self._entries:
            self._entries.pop(key)
        elif len(self._entries) >= self.max_entries:
            self._entries.pop(next(iter(self._entries)))
        self._entries[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._entries.clear()


class RedisResponseCache:
    """Shared TTL cache backed by Redis, for multi-process/replica deployments.

    Values are JSON-encoded. Any Redis error during a request (timeout,
    connection drop) is treated as a cache miss on read or a no-op on write,
    never a failed request — the cache is a performance optimisation, not a
    dependency the check pipeline can fail on.
    """

    def __init__(self, client) -> None:
        self._client = client

    async def get(self, key: str) -> dict | None:
        try:
            raw = await self._client.get(key)
        except Exception as e:
            logger.warning("Redis cache read failed, treating as miss: %s", e)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    async def set(self, key: str, value: dict, ttl_seconds: float | None = None) -> None:
        from app.config import settings

        ttl = settings.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        try:
            await self._client.set(key, json.dumps(value), ex=int(ttl))
        except Exception as e:
            logger.warning("Redis cache write failed, ignoring: %s", e)

    def clear(self) -> None:
        # Not implemented: flushing an arbitrary key pattern needs a SCAN
        # sweep that isn't safe to run casually against a shared cache. Only
        # used by tests against the in-memory default, so this is never
        # exercised in the Redis-backed path.
        logger.warning("RedisResponseCache.clear() is a no-op — restart or flush Redis directly.")


def build_response_cache() -> ResponseCache | RedisResponseCache:
    """Build the configured response-cache backend.

    Falls back to the in-memory cache when `CLARITY_REDIS_URL` is unset, the
    `redis` package isn't installed, or the client can't be constructed.
    Connectivity itself isn't verified here (no blocking call at startup);
    a Redis that's briefly unreachable recovers per-request via the
    try/except in `RedisResponseCache`.
    """
    from app.config import settings

    if not settings.redis_url:
        return ResponseCache()
    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        logger.warning(
            "CLARITY_REDIS_URL is set but the 'redis' package is not installed — "
            "falling back to the in-memory cache. Run: pip install redis"
        )
        return ResponseCache()
    try:
        client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    except Exception as e:
        logger.warning("Failed to build Redis client (%s) — falling back to in-memory cache.", e)
        return ResponseCache()
    return RedisResponseCache(client)
