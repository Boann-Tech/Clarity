"""A minimal in-process stand-in for redis.asyncio.Redis, used to exercise
RedisResponseCache / RedisRateLimiter logic without a real Redis server.
"""

from __future__ import annotations


class FakePipeline:
    def __init__(self, store: dict):
        self._store = store
        self._ops: list[tuple[str, str, int]] = []

    def incrby(self, key: str, amount: int):
        self._ops.append(("incrby", key, amount))
        return self

    def decrby(self, key: str, amount: int):
        self._ops.append(("decrby", key, amount))
        return self

    def expire(self, key: str, _ttl: int):
        self._ops.append(("expire", key, 0))
        return self

    async def execute(self) -> list:
        results = []
        for op, key, amount in self._ops:
            if op == "incrby":
                self._store[key] = self._store.get(key, 0) + amount
                results.append(self._store[key])
            elif op == "decrby":
                self._store[key] = self._store.get(key, 0) - amount
                results.append(self._store[key])
            elif op == "expire":
                results.append(True)
        return results


class FakeRedisClient:
    """Supports just the get/set/pipeline surface RedisResponseCache and
    RedisRateLimiter use.
    """

    def __init__(self, fail: bool = False):
        self.fail = fail
        self._kv: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    async def get(self, key: str):
        if self.fail:
            raise ConnectionError("simulated redis outage")
        return self._kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self.fail:
            raise ConnectionError("simulated redis outage")
        self._kv[key] = value

    def pipeline(self):
        if self.fail:
            return _FailingPipeline()
        return FakePipeline(self._counters)


class _FailingPipeline:
    def incrby(self, *_a, **_k):
        return self

    def decrby(self, *_a, **_k):
        return self

    def expire(self, *_a, **_k):
        return self

    async def execute(self):
        raise ConnectionError("simulated redis outage")
