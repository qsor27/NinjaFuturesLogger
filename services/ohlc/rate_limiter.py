"""Global token bucket gating every OHLC provider call.

Capacity 30, refill 0.5/sec (= 30/min). Shared across sources, shared
across jobs. The fetcher acquires one token before each source.fetch()
call. Blocking acquire with bounded wait — callers that time out
defer to the next cycle rather than queueing indefinitely.
"""

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager


class TokenBucket:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_sec: float,
        clock: Callable[[], float],
    ) -> None:
        self._capacity = capacity
        self._refill_per_sec = refill_per_sec
        self._clock = clock
        self._tokens = float(capacity)
        self._last_refill = clock()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._acquired_total = 0
        self._waited_total_ms = 0
        self._timeouts_total = 0

    def _refill_locked(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(
            float(self._capacity),
            self._tokens + elapsed * self._refill_per_sec,
        )
        self._last_refill = now

    def available(self) -> int:
        with self._lock:
            self._refill_locked()
            return int(self._tokens)

    @contextmanager
    def acquire(self, *, timeout: float):
        # Real-time deadline for the wait budget; the injected clock drives
        # refill accounting but may be a FakeClock in tests so cannot be
        # trusted for bounding actual blocking time.
        start_wall = time.monotonic()
        with self._cond:
            while True:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._acquired_total += 1
                    break
                waited_wall = time.monotonic() - start_wall
                if waited_wall >= timeout:
                    self._timeouts_total += 1
                    raise TimeoutError("token bucket timed out")
                self._cond.wait(timeout=max(0.01, timeout - waited_wall))
        waited_ms = int((time.monotonic() - start_wall) * 1000)
        self._waited_total_ms += waited_ms
        try:
            yield
        finally:
            pass

    def wake_waiters(self) -> None:
        """Test-only hook: notify waiters after a fake-clock advance."""
        with self._cond:
            self._cond.notify_all()

    def stats(self) -> dict:
        with self._lock:
            self._refill_locked()
            return {
                "capacity": self._capacity,
                "available": int(self._tokens),
                "refill_per_sec": self._refill_per_sec,
                "acquired_total": self._acquired_total,
                "waited_total_ms": self._waited_total_ms,
                "timeouts_total": self._timeouts_total,
            }
