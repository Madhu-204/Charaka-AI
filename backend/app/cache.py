import hashlib
import threading
import time
from collections import OrderedDict


class LRUCache:
    """Thread-safe LRU cache with TTL, used to short-circuit identical /ask queries."""

    def __init__(self, capacity: int = 64, ttl: int = 3600):
        self._capacity = max(1, capacity)
        self._ttl = max(1, ttl)
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    @staticmethod
    def key_for(query: str, dosha_profile: str | None = None) -> str:
        norm = " ".join(query.strip().lower().split())
        return hashlib.sha1(
            f"{norm}|{dosha_profile or ''}".encode("utf-8")
        ).hexdigest()

    def get(self, key: str):
        with self._lock:
            if key not in self._data:
                self._misses += 1
                return None
            entry = self._data[key]
            if entry["expires_at"] < time.time():
                del self._data[key]
                self._misses += 1
                return None
            self._hits += 1
            self._data.move_to_end(key)
            return entry["value"]

    def set(self, key: str, value, ttl: int | None = None):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = {
                "value": value,
                "expires_at": time.time() + (ttl or self._ttl),
            }
            while len(self._data) > self._capacity:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                "capacity": self._capacity,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
            }