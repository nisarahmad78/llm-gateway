"""Per-key rate limiting with an in-memory token bucket.

Each API key gets a bucket that refills at RATE_LIMIT_RPM tokens per minute.
This is intentionally small and dependency-free. For multi-process or
multi-instance deployments, replace TokenBucketLimiter with a Redis-backed
implementation (e.g. a Lua-scripted token bucket keyed by API key) — the
interface (`allow`) stays the same.
"""

from __future__ import annotations

import threading
import time


class _Bucket:
    __slots__ = ("tokens", "updated_at")

    def __init__(self, capacity: float) -> None:
        self.tokens = capacity
        self.updated_at = time.monotonic()


class TokenBucketLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.capacity = float(requests_per_minute)
        self.refill_per_second = requests_per_minute / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """Consume one token for `key`.

        Returns (allowed, retry_after_seconds). retry_after is 0 when allowed.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self.capacity)
                self._buckets[key] = bucket
            elapsed = now - bucket.updated_at
            bucket.tokens = min(
                self.capacity, bucket.tokens + elapsed * self.refill_per_second
            )
            bucket.updated_at = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0
            deficit = 1.0 - bucket.tokens
            return False, deficit / self.refill_per_second if self.refill_per_second else 60.0
