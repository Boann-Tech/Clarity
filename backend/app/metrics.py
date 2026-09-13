"""Lightweight in-process metrics for the evidence pipeline.

Per-process only — like the in-memory cache and rate limiter, these counters
reset on restart and aren't shared across workers/replicas. Good enough for
a single-process deployment or as a per-replica signal; aggregate externally
(scrape `/api/metrics` on each replica) for a fleet-wide view.
"""

from __future__ import annotations

import threading
import time
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._llm_calls: Counter[str] = Counter()
        self._llm_latency_total: Counter[str] = Counter()
        self.started_at = time.monotonic()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe_llm_call(self, role: str, latency_seconds: float, ok: bool) -> None:
        """Record one LLM call. `role` is e.g. "normalize", "classify", "verdict"."""
        with self._lock:
            self._llm_calls[f"{role}:{'ok' if ok else 'error'}"] += 1
            self._llm_latency_total[role] += latency_seconds

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._llm_calls.clear()
            self._llm_latency_total.clear()
            self.started_at = time.monotonic()

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            llm: dict[str, dict] = {}
            for key, calls in self._llm_calls.items():
                role, status = key.split(":", 1)
                llm.setdefault(role, {"ok": 0, "error": 0, "avg_latency_seconds": 0.0})
                llm[role][status] = calls
            for role, total_latency in self._llm_latency_total.items():
                stats = llm.setdefault(role, {"ok": 0, "error": 0, "avg_latency_seconds": 0.0})
                calls = stats["ok"] + stats["error"]
                if calls:
                    stats["avg_latency_seconds"] = round(total_latency / calls, 3)
            return {
                "uptime_seconds": round(time.monotonic() - self.started_at, 1),
                "counters": counters,
                "llm": llm,
            }


metrics = Metrics()
