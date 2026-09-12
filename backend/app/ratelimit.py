"""In-memory sliding-window rate limiting for the public API."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque


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

    async def allow(self, key: str, per_minute: int, per_hour: int) -> bool:
        now = time.monotonic()
        async with self._lock:
            self._evict_stale(now)
            events = self._events.get(key)
            if events is None:
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)
            while events and now - events[0] > 3600:
                events.popleft()
            minute_count = sum(1 for ts in events if now - ts <= 60)
            if minute_count >= per_minute or len(events) >= per_hour:
                if not events:
                    self._events.pop(key, None)
                return False
            events.append(now)
            if len(self._events) > self.max_keys:
                self._events.popitem(last=False)
            return True

    def reset(self) -> None:
        self._events.clear()