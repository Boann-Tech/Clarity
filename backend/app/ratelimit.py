"""In-memory sliding-window rate limiting for the public API."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str, per_minute: int, per_hour: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > 3600:
                events.popleft()
            minute_count = sum(1 for ts in events if now - ts <= 60)
            if minute_count >= per_minute or len(events) >= per_hour:
                return False
            events.append(now)
            return True

    def reset(self) -> None:
        self._events.clear()