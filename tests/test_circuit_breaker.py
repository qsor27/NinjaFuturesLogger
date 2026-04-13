import pytest

from services.ohlc.circuit_breaker import CircuitBreaker


class _Clock:
    def __init__(self, t: int = 1_000_000):
        self.t = t

    def __call__(self) -> int:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += seconds


class _FakeResponse:
    def __init__(self, code: int):
        self.status_code = code


class _FakeHTTPError(Exception):
    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.response = _FakeResponse(code)


def _make(clock: _Clock, *, threshold: int = 3, cooldown: int = 600):
    return CircuitBreaker(
        name="test",
        failure_threshold=threshold,
        cooldown_seconds=cooldown,
        clock=clock,
    )


def test_starts_closed_and_allows():
    cb = _make(_Clock())
    assert cb.state == "closed"
    assert cb.allows() is True


def test_record_success_keeps_closed():
    cb = _make(_Clock())
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_three_failures_opens():
    cb = _make(_Clock())
    for _ in range(3):
        cb.record_failure(RuntimeError("boom"))
    assert cb.state == "open"
    assert cb.allows() is False


def test_two_failures_then_success_resets():
    cb = _make(_Clock())
    cb.record_failure(RuntimeError("a"))
    cb.record_failure(RuntimeError("b"))
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_fast_trip_on_429():
    cb = _make(_Clock())
    cb.record_failure(_FakeHTTPError(429))
    assert cb.state == "open"


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_fast_trip_on_5xx(code):
    cb = _make(_Clock())
    cb.record_failure(_FakeHTTPError(code))
    assert cb.state == "open"


def test_open_to_half_open_after_cooldown():
    clock = _Clock()
    cb = _make(clock, cooldown=600)
    for _ in range(3):
        cb.record_failure(RuntimeError("boom"))
    assert cb.state == "open"
    assert cb.allows() is False

    clock.advance(599)
    assert cb.allows() is False  # still cooling

    clock.advance(2)  # past the cooldown
    assert cb.allows() is True  # half-open: probationary call allowed
    assert cb.state == "half_open"


def test_half_open_success_closes():
    clock = _Clock()
    cb = _make(clock, cooldown=10)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(11)
    cb.allows()  # transitions to half_open
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_half_open_failure_reopens_with_fresh_cooldown():
    clock = _Clock()
    cb = _make(clock, cooldown=10)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(11)
    cb.allows()  # half_open
    cb.record_failure(RuntimeError("still broken"))
    assert cb.state == "open"

    clock.advance(5)
    assert cb.allows() is False
    clock.advance(6)
    assert cb.allows() is True


def test_status_snapshot_returns_introspection_dict():
    cb = _make(_Clock())
    cb.record_failure(RuntimeError("nope"))
    snap = cb.status_snapshot()
    assert snap["name"] == "test"
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 1
    assert "last_failure_at" in snap
    assert "last_error" in snap
