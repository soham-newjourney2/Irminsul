"""In-memory sliding-window rate limiter (single instance)."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record an attempt; False when the key is over its limit."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 10_000:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or q[-1] <= now - self.window_s]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()


login_limiter = RateLimiter(limit=5, window_s=60)  # per email + IP
login_ip_limiter = RateLimiter(limit=30, window_s=60)  # per IP, any account
