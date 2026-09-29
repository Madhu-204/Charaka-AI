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


class ConcurrencyGate:
    """Caps how many agent runs execute at once.

    The free LLM tier enforces a per-minute token ceiling (8K TPM for
    gpt-oss-120b). A single synthesize call is ~3.5K input tokens, so more
    than two overlapping runs exceed the ceiling and the provider returns
    429. Those 429s are swallowed by the per-node exception handlers and
    surface as a silent downgrade to template output, which is far harder
    to diagnose than a short wait. Queueing here keeps quality deterministic.
    """

    def __init__(self, slots: int = 2, timeout: float = 45.0):
        self._slots = max(1, int(slots))
        self._timeout = max(1.0, float(timeout))
        self._sem = threading.BoundedSemaphore(self._slots)
        self._lock = threading.Lock()
        self._in_flight = 0
        self._waited = 0
        self._timeouts = 0

    def acquire(self) -> bool:
        got = self._sem.acquire(timeout=self._timeout)
        with self._lock:
            if got:
                self._in_flight += 1
            else:
                self._timeouts += 1
        return got

    def release(self) -> None:
        with self._lock:
            if self._in_flight > 0:
                self._in_flight -= 1
        try:
            self._sem.release()
        except ValueError:
            pass

    def stats(self) -> dict:
        with self._lock:
            return {
                "slots": self._slots,
                "in_flight": self._in_flight,
                "timeouts": self._timeouts,
            }