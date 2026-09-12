import threading
import time
from collections import defaultdict


class TokenBucket:
    def __init__(self, capacity: float, refill_per_sec: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_sec = refill_per_sec
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, n: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            self.tokens = min(
                self.capacity,
                self.tokens + (now - self.updated) * self.refill_per_sec,
            )
            self.updated = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False


class RateLimiter:
    """Per-client token-bucket limiter keyed by client id (IP / API key)."""

    def __init__(self, per_minute: int = 30, burst: int = 60):
        self._per_minute = max(1, int(per_minute))
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                max(1, burst), self._per_minute / 60.0
            )
        )
        self._lock = threading.Lock()

    def allow(self, client_id: str, n: float = 1.0) -> bool:
        with self._lock:
            return self._buckets[client_id].consume(n)

    def remaining(self, client_id: str) -> float:
        with self._lock:
            bucket = self._buckets.get(client_id)
            return bucket.tokens if bucket else 0.0