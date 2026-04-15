"""Tests for the adaptive-backoff extensions to CircuitBreaker.

See `docs/superpowers/plans/2026-04-14-18-adaptive-breakers.md` task 2.
"""

from __future__ import annotations

from services.ohlc.circuit_breaker import CircuitBreaker, FailureClassification


class _Clock:
    def __init__(self, t: int = 1_000_000):
        self.t = t

    def __call__(self) -> int:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += seconds


def _no_jitter() -> float:
    return 0.5  # centered — (0.5 - 0.5) * 2 * jitter_fraction = 0


def _make(
    clock,
    *,
    threshold: int = 3,
    base: int = 300,
    base_rate_limit: int = 900,
    maxc: int = 14400,
    multiplier: float = 2.0,
    jitter: float = 0.0,
    rng=_no_jitter,
):
    return CircuitBreaker(
        name="test",
        failure_threshold=threshold,
        base_cooldown_seconds=base,
        base_cooldown_rate_limit_seconds=base_rate_limit,
        max_cooldown_seconds=maxc,
        backoff_multiplier=multiplier,
        jitter_fraction=jitter,
        clock=clock,
        rng=rng,
    )


def _classify(cls: str, retry_after: int | None = None) -> RuntimeError:
    err = RuntimeError(f"synthetic {cls}")
    err.ftl_failure = FailureClassification(failure_class=cls, retry_after_seconds=retry_after)
    return err


def test_first_trip_uses_base_cooldown():
    clock = _Clock()
    cb = _make(clock, base=300)
    for _ in range(3):
        cb.record_failure(RuntimeError("generic"))
    assert cb.state == "open"
    assert cb.current_cooldown_seconds == 300
    assert cb.consecutive_trips == 1


def test_second_trip_doubles_cooldown():
    clock = _Clock()
    cb = _make(clock, base=300, multiplier=2.0)
    for _ in range(3):
        cb.record_failure(RuntimeError("a"))
    clock.advance(301)
    cb.allows()  # → half_open
    cb.record_failure(RuntimeError("b"))  # half_open failure re-opens
    assert cb.state == "open"
    assert cb.consecutive_trips == 2
    assert cb.current_cooldown_seconds == 600


def test_third_trip_quadruples_cooldown():
    clock = _Clock()
    cb = _make(clock, base=300, multiplier=2.0)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    clock.advance(601)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.consecutive_trips == 3
    assert cb.current_cooldown_seconds == 1200


def test_escalation_capped_at_max_cooldown():
    clock = _Clock()
    cb = _make(clock, base=300, multiplier=2.0, maxc=1000)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 600
    clock.advance(601)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 1000
    clock.advance(1001)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 1000


def test_success_resets_trip_counter_and_cooldown():
    clock = _Clock()
    cb = _make(clock, base=300)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.consecutive_trips == 2

    clock.advance(601)
    cb.allows()
    cb.record_success()
    assert cb.consecutive_trips == 0
    assert cb.consecutive_failures == 0
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 300


def test_rate_limit_uses_separate_base():
    clock = _Clock()
    cb = _make(clock, base=300, base_rate_limit=900)
    cb.record_failure(_classify("rate_limit"))
    assert cb.state == "open"
    assert cb.current_cooldown_seconds == 900
    assert cb.last_failure_class == "rate_limit"


def test_server_error_uses_normal_base():
    clock = _Clock()
    cb = _make(clock, base=300, base_rate_limit=900)
    cb.record_failure(_classify("server_error"))
    assert cb.state == "open"
    assert cb.current_cooldown_seconds == 300
    assert cb.last_failure_class == "server_error"


def test_network_error_uses_normal_base():
    clock = _Clock()
    cb = _make(clock, base=300)
    cb.record_failure(_classify("network"))
    assert cb.state == "open"
    assert cb.current_cooldown_seconds == 300
    assert cb.last_failure_class == "network"


def test_retry_after_raises_cooldown_floor():
    clock = _Clock()
    cb = _make(clock, base=300)
    cb.record_failure(_classify("rate_limit", retry_after=1800))
    assert cb.current_cooldown_seconds == 1800


def test_retry_after_ignored_when_shorter_than_computed():
    clock = _Clock()
    cb = _make(clock, base=300, base_rate_limit=900)
    cb.record_failure(_classify("rate_limit", retry_after=10))
    assert cb.current_cooldown_seconds == 900


def test_other_failure_counts_toward_slow_trip():
    clock = _Clock()
    cb = _make(clock, base=300, threshold=3)
    cb.record_failure(_classify("other"))
    cb.record_failure(_classify("other"))
    assert cb.state == "closed"
    cb.record_failure(_classify("other"))
    assert cb.state == "open"
    assert cb.last_failure_class == "other"


def test_jitter_produces_upper_bound_when_rng_is_one():
    clock = _Clock()
    cb = _make(clock, base=300, jitter=0.15, rng=lambda: 1.0)
    cb.record_failure(RuntimeError("x"))
    cb.record_failure(RuntimeError("x"))
    cb.record_failure(RuntimeError("x"))
    # rng=1.0 → multiplier = 1 + (1.0 - 0.5) * 2 * 0.15 = 1.15
    assert cb.current_cooldown_seconds == int(300 * 1.15)


def test_jitter_produces_lower_bound_when_rng_is_zero():
    clock = _Clock()
    cb = _make(clock, base=300, jitter=0.15, rng=lambda: 0.0)
    cb.record_failure(RuntimeError("x"))
    cb.record_failure(RuntimeError("x"))
    cb.record_failure(RuntimeError("x"))
    # rng=0.0 → multiplier = 1 + (0.0 - 0.5) * 2 * 0.15 = 0.85
    assert cb.current_cooldown_seconds == int(300 * 0.85)


def test_allows_uses_current_cooldown_not_base():
    clock = _Clock()
    cb = _make(clock, base=300)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))  # trip 2, current = 600
    clock.advance(301)
    assert cb.allows() is False
    clock.advance(301)
    assert cb.allows() is True


def test_status_snapshot_contains_new_fields():
    clock = _Clock()
    cb = _make(clock, base=300, base_rate_limit=900)
    cb.record_failure(_classify("rate_limit"))
    snap = cb.status_snapshot()
    assert snap["consecutive_trips"] == 1
    assert snap["current_cooldown_seconds"] == 900
    assert snap["next_retry_at"] == clock.t + snap["current_cooldown_seconds"]
    assert snap["last_failure_class"] == "rate_limit"


def test_classify_http_error_parses_retry_after_seconds():
    from services.ohlc._classify import classify_http_error

    class _Resp:
        def __init__(self, code, retry_after=None):
            self.status_code = code
            self.headers = {"Retry-After": retry_after} if retry_after else {}

    class _Err(Exception):
        def __init__(self, code, retry_after=None):
            self.response = _Resp(code, retry_after)

    cls, ra = classify_http_error(_Err(429, "600"))
    assert cls == "rate_limit"
    assert ra == 600

    cls, ra = classify_http_error(_Err(503))
    assert cls == "server_error"
    assert ra is None

    cls, ra = classify_http_error(_Err(404))
    assert cls == "other"


def test_attach_classification_sets_ftl_failure_attribute():
    from services.ohlc._classify import attach_classification

    err = RuntimeError("boom")
    returned = attach_classification(err, failure_class="network")
    assert returned is err
    assert err.ftl_failure.failure_class == "network"
    assert err.ftl_failure.retry_after_seconds is None
