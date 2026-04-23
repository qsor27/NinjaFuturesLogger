import threading
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

State = Literal["closed", "open", "half_open"]

FailureClass = Literal["rate_limit", "server_error", "network", "other"]


class FailureClassification(BaseModel):
    """Optional structured failure signal attached to adapter exceptions.

    Adapters that know *why* a call failed (HTTP status code, explicit
    Retry-After header, connection error) should attach an instance of
    this model to the exception as an attribute named `ftl_failure`.
    CircuitBreaker.record_failure looks for that attribute and falls back
    to classifying from the exception shape if absent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    failure_class: FailureClass
    retry_after_seconds: int | None = None


class CircuitBreaker:
    """Per-source three-state circuit breaker with adaptive backoff.

    Closed: normal. Open: skip the source until the cooldown expires.
    Half-open: one probationary call is allowed; success closes, failure
    re-opens with a fresh (escalated) cooldown.

    Plan 18:
    - consecutive_trips counts re-opens since the last successful call.
    - cooldown escalates as base * multiplier ** (trips - 1), capped.
    - Rate-limit failures use a separate (longer) base cooldown.
    - Retry-After header acts as a cooldown floor, never a replacement.
    - Bounded jitter (±jitter_fraction) on cooldown to avoid lockstep
      re-probes across simultaneously-tripped sources.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int,
        base_cooldown_seconds: int,
        clock: Callable[[], int],
        base_cooldown_rate_limit_seconds: int | None = None,
        max_cooldown_seconds: int | None = None,
        backoff_multiplier: float = 2.0,
        jitter_fraction: float = 0.0,
        rng: Callable[[], float] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.base_cooldown_seconds = base_cooldown_seconds
        self.base_cooldown_rate_limit_seconds = (
            base_cooldown_rate_limit_seconds
            if base_cooldown_rate_limit_seconds is not None
            else base_cooldown_seconds
        )
        self.max_cooldown_seconds = (
            max_cooldown_seconds if max_cooldown_seconds is not None else base_cooldown_seconds * 48
        )
        self.backoff_multiplier = backoff_multiplier
        self.jitter_fraction = jitter_fraction
        self._clock = clock
        self._rng = rng or (lambda: 0.5)  # 0.5 → no jitter
        self._lock = threading.Lock()

        self.state: State = "closed"
        self.consecutive_failures: int = 0
        self.consecutive_trips: int = 0
        self.current_cooldown_seconds: int = base_cooldown_seconds
        self.opened_at: int | None = None
        self.next_retry_at: int | None = None
        self.last_failure_at: int | None = None
        self.last_success_at: int | None = None
        self.last_error: str | None = None
        self.last_failure_class: FailureClass | None = None

    def allows(self) -> bool:
        with self._lock:
            if self.state == "closed" or self.state == "half_open":
                return True
            assert self.opened_at is not None
            if self._clock() - self.opened_at >= self.current_cooldown_seconds:
                self.state = "half_open"
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self.state = "closed"
            self.consecutive_failures = 0
            self.consecutive_trips = 0
            self.current_cooldown_seconds = self.base_cooldown_seconds
            self.opened_at = None
            self.next_retry_at = None
            self.last_success_at = self._clock()
            # last_failure_class stays so operators can see the last reason.

    def record_failure(self, error: BaseException) -> None:
        with self._lock:
            now = self._clock()
            cls, retry_after = self._classify(error)
            self.consecutive_failures += 1
            self.last_failure_at = now
            self.last_error = repr(error)
            # Half-open failure → immediate re-open regardless of class.
            if self.state == "half_open":
                self._open(now, cls, retry_after)
                return
            fast_trip = cls in ("rate_limit", "server_error", "network")
            slow_trip = self.consecutive_failures >= self.failure_threshold
            if fast_trip or slow_trip:
                self._open(now, cls, retry_after)

    def status_snapshot(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_trips": self.consecutive_trips,
            "current_cooldown_seconds": self.current_cooldown_seconds,
            "opened_at": self.opened_at,
            "next_retry_at": self.next_retry_at,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "last_failure_class": self.last_failure_class,
        }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "consecutive_failures": self.consecutive_failures,
                "consecutive_trips": self.consecutive_trips,
                "current_cooldown_seconds": self.current_cooldown_seconds,
                "opened_at": self.opened_at,
                "next_retry_at": self.next_retry_at,
                "last_failure_at": self.last_failure_at,
                "last_success_at": self.last_success_at,
                "last_error": self.last_error,
                "last_failure_class": self.last_failure_class,
            }

    def restore(self, row: dict) -> None:
        with self._lock:
            self.state = row["state"]
            self.consecutive_failures = int(row["consecutive_failures"])
            self.consecutive_trips = int(row["consecutive_trips"])
            self.current_cooldown_seconds = int(row["current_cooldown_seconds"])
            self.opened_at = row["opened_at"]
            self.next_retry_at = row["next_retry_at"]
            self.last_failure_at = row["last_failure_at"]
            self.last_success_at = row["last_success_at"]
            self.last_error = row["last_error"]
            self.last_failure_class = row["last_failure_class"]

    def _classify(self, error: BaseException) -> tuple[FailureClass, int | None]:
        """Return (class, retry_after_seconds).

        Prefers an attached FailureClassification; falls back to sniffing
        a `.response.status_code` attribute (`requests.HTTPError` shape).
        """
        attached = getattr(error, "ftl_failure", None)
        if isinstance(attached, FailureClassification):
            return attached.failure_class, attached.retry_after_seconds
        response = getattr(error, "response", None)
        code = getattr(response, "status_code", None)
        if code == 429:
            return "rate_limit", None
        if code is not None and 500 <= code < 600:
            return "server_error", None
        return "other", None

    def _base_for(self, cls: FailureClass) -> int:
        if cls == "rate_limit":
            return self.base_cooldown_rate_limit_seconds
        return self.base_cooldown_seconds

    def _compute_cooldown(self, cls: FailureClass, retry_after: int | None) -> int:
        base = self._base_for(cls)
        # Escalation uses the trip count *after* this trip is recorded.
        exponent = max(0, self.consecutive_trips - 1)
        computed = base * (self.backoff_multiplier**exponent)
        computed = min(computed, self.max_cooldown_seconds)
        # Jitter: rng() in [0,1), centered at 0.5 → no change.
        jitter = (self._rng() - 0.5) * 2 * self.jitter_fraction
        jittered = computed * (1 + jitter)
        floor = retry_after if retry_after is not None else 0
        return int(max(jittered, floor))

    def _open(self, now: int, cls: FailureClass, retry_after: int | None) -> None:
        self.state = "open"
        self.opened_at = now
        self.consecutive_trips += 1
        self.current_cooldown_seconds = self._compute_cooldown(cls, retry_after)
        self.next_retry_at = now + self.current_cooldown_seconds
        self.last_failure_class = cls
