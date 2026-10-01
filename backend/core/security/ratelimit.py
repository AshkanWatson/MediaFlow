"""Small in-memory sliding-window rate limiter (single-process)."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from core.errors import RateLimited


class RateLimiter:
    def __init__(self, limit_per_minute: int, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit_per_minute, window, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = self.clock()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise RateLimited()
        q.append(now)
        if len(self._hits) > 10_000:  # bound memory
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                self._hits.pop(k, None)
