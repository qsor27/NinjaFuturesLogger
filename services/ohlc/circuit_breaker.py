import threading
from collections.abc import Callable
from typing import Literal

State = Literal["closed", "open", "half_open"]


def _is_fast_trip(error: BaseException) -> bool:
    """True iff this exception should immediately open the breaker.

    Spec: a single HTTPError with status 429 or any 5xx code opens the
    breaker without waiting for three consecutive failures. We detect this
    by looking for a `.response.status_code` attribute, which is what
    `requests.HTTPError` carries; if a future adapter raises a different
    exception type with the same shape, this still works.
    """
    response = getattr(error, "response", None)
    code = getattr(response, "status_code", None)
    if code is None:
        return False
    return code == 429 or 500 <= code < 600


class CircuitBreaker:
    """Per-source three-state circuit breaker.

    Closed: normal. Open: skip the source until the cooldown expires.
    Half-open: one probationary call is allowed; success closes, failure
    re-opens with a fresh cooldown.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int,
        cooldown_seconds: int,
        clock: Callable[[], int],
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self.state: State = "closed"
        self.consecutive_failures: int = 0
        self.opened_at: int | None = None
        self.last_failure_at: int | None = None
        self.last_success_at: int | None = None
        self.last_error: str | None = None

    def allows(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "half_open":
                return True
            # open — check whether cooldown has elapsed
            assert self.opened_at is not None
            if self._clock() - self.opened_at >= self.cooldown_seconds:
                self.state = "half_open"
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self.state = "closed"
            self.consecutive_failures = 0
            self.opened_at = None
            self.last_success_at = self._clock()

    def record_failure(self, error: BaseException) -> None:
        with self._lock:
            now = self._clock()
            self.consecutive_failures += 1
            self.last_failure_at = now
            self.last_error = repr(error)
            if self.state == "half_open":
                self._open(now)
                return
            if _is_fast_trip(error) or self.consecutive_failures >= self.failure_threshold:
                self._open(now)

    def status_snapshot(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "opened_at": self.opened_at,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }

    def _open(self, now: int) -> None:
        self.state = "open"
        self.opened_at = now
