import threading
import time

import pytest

from services.ohlc.rate_limiter import TokenBucket


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_bucket_starts_full():
    clock = FakeClock()
    b = TokenBucket(capacity=30, refill_per_sec=0.5, clock=clock)
    assert b.available() == 30


def test_acquire_consumes_one_token():
    clock = FakeClock()
    b = TokenBucket(capacity=30, refill_per_sec=0.5, clock=clock)
    with b.acquire(timeout=0):
        pass
    assert b.available() == 29


def test_refills_over_time():
    clock = FakeClock()
    b = TokenBucket(capacity=30, refill_per_sec=0.5, clock=clock)
    for _ in range(30):
        with b.acquire(timeout=0):
            pass
    assert b.available() == 0
    clock.advance(4)
    assert b.available() == 2


def test_refill_capped_at_capacity():
    clock = FakeClock()
    b = TokenBucket(capacity=30, refill_per_sec=0.5, clock=clock)
    clock.advance(10_000)
    assert b.available() == 30


def test_acquire_blocks_until_refill():
    clock = FakeClock()
    b = TokenBucket(capacity=1, refill_per_sec=1.0, clock=clock)
    with b.acquire(timeout=0):
        pass
    assert b.available() == 0
    started = threading.Event()
    released = threading.Event()

    def worker():
        started.set()
        with b.acquire(timeout=5):
            released.set()

    t = threading.Thread(target=worker)
    t.start()
    started.wait()
    time.sleep(0.05)
    assert not released.is_set()
    clock.advance(1.0)
    b.wake_waiters()
    released.wait(timeout=2)
    assert released.is_set()
    t.join()


def test_acquire_times_out():
    clock = FakeClock()
    b = TokenBucket(capacity=1, refill_per_sec=0.0, clock=clock)
    with b.acquire(timeout=0):
        pass
    with pytest.raises(TimeoutError):
        with b.acquire(timeout=0.05):
            pass


def test_stats_snapshot_shape():
    clock = FakeClock()
    b = TokenBucket(capacity=30, refill_per_sec=0.5, clock=clock)
    snap = b.stats()
    assert set(snap.keys()) >= {
        "capacity",
        "available",
        "refill_per_sec",
        "acquired_total",
        "waited_total_ms",
        "timeouts_total",
    }
    assert snap["capacity"] == 30
    assert snap["available"] == 30
