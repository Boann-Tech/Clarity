"""Bounded TTL cache for completed claim checks."""

from __future__ import annotations

import time


class ResponseCache:
    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, dict]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict, ttl_seconds: float | None = None) -> None:
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