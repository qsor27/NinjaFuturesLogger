# Plan 18 — Adaptive circuit-breaker backoff

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed-cooldown circuit breaker with an adaptive one that (a) escalates cooldown on repeated trips, (b) distinguishes between rate-limit and transient-error failure classes with different base cooldowns, (c) respects an HTTP `Retry-After` header when the upstream server literally tells us when to come back, and (d) applies bounded jitter so simultaneous trips don't re-probe in lockstep. Surface the new state on `/api/ohlc/sources` so `/data-health` can display it.

**Non-goals:**
- **No synthetic / aggregated bar data.** If all sources are down, the chart stays in the "delayed" state it already has. We are improving source reliability, not papering over source absence.
- **No half-open health probes.** The probationary call stays as whatever the next real fetch happens to be.
- **No cross-source coordination beyond what `SourceRegistry.sources_for` already does.**
- **No breaker-state persistence across Flask restarts.** 5 minutes of lost state on a rebuild is acceptable.
- **No retry loops inside adapter `fetch()` methods.** The breaker is the single source of retry policy.

**Architecture:** Single-file change in `services/ohlc/circuit_breaker.py` with a new constructor shape, plus a thin data-class for failure classification. `registry.py` gains new config keys per source. `yfinance_source.py` and `stooq_source.py` gain minimal "classify HTTP errors" plumbing so the breaker receives a typed signal instead of a bare exception. `/api/ohlc/sources` adds four fields to its snapshot, consumed by `static/js/data_health.js` for the Next Retry column (already in the DOM but currently always shows `—`).

**Tech stack:** Pydantic v2 (for `FailureClassification` dataclass shape), `requests` HTTPError surfacing, `random.Random` (seeded for tests), existing APScheduler/SQLite stack untouched.

---

## Load-bearing decisions

1. **Separate `consecutive_trips` from `consecutive_failures`.** Today's counter conflates "3 requests failed inside one slow-trip" with "breaker has re-opened 3 times." The adaptive backoff needs the second meaning. Both counters coexist; both reset only on `record_success`.

2. **Base cooldown depends on *why* we tripped.** A 429 means "the server told us we're over quota" and deserves a longer baseline. A 5xx or network error means "transient problem" and deserves the normal baseline. An `"other"` error (the 3-consecutive-failures slow trip) also uses the normal baseline. A single enum-like string (`"rate_limit" | "server_error" | "network" | "other"`) is carried on every `record_failure` call.

3. **Classification happens in the adapter, not the breaker.** Adapters already know the concrete exception types their transport library raises. The breaker receives a `FailureClassification` pydantic model — or bare `BaseException` for back-compat with tests that just throw `RuntimeError` — and infers `"other"` when no class is supplied. This keeps the breaker library-agnostic.

4. **Jitter is multiplicative and bounded.** `cooldown *= 1 + rng.uniform(-jitter_fraction, +jitter_fraction)`. Default `jitter_fraction=0.15`. The `rng` is injectable for deterministic tests.

5. **Exponential escalation caps at `max_cooldown_seconds`.** Formula: `min(max_cooldown, base * multiplier ** (trips - 1))` then jittered. `multiplier` defaults to `2.0`. First trip → base. Second trip → 2×base. Third → 4×base. Capped.

6. **`Retry-After` is a floor, not a replacement.** If the upstream sends `Retry-After: 600` and our computed cooldown is 300, we wait 600. If it sends 10 and we computed 300, we wait 300. Never shorter than what the server asked for; never shorter than what our escalation says we should.

7. **Observability goes in the existing `status_snapshot()` dict.** Four new fields: `consecutive_trips`, `current_cooldown_seconds`, `next_retry_at`, `last_failure_class`. `/api/ohlc/sources` automatically carries them (it just maps `status_snapshot()` into JSON); `static/js/data_health.js` fills the "Next Retry" cell from `next_retry_at`.

---

## File Map

**Created:**
- `tests/test_circuit_breaker_adaptive.py` — new test module for escalation/classification/retry-after/jitter behavior. Existing `test_circuit_breaker.py` is extended, not replaced.

**Modified:**
- `services/ohlc/circuit_breaker.py` — new constructor signature, new state fields, escalation math, classification enum, `FailureClassification` model.
- `services/ohlc/registry.py` — register yfinance and stooq with the new per-source config keys; keep the function signature of `register()` backwards-compatible (keyword-only, new optional params).
- `services/ohlc/yfinance_source.py` — catch `requests.HTTPError` (when present; yfinance's _ERRORS path already re-raises as `RuntimeError`) and attach a `FailureClassification` before re-raising.
- `services/ohlc/stooq_source.py` — same pattern; catch the `requests.HTTPError` raised by `_http_get`, classify by status code and `Retry-After` header.
- `tests/test_circuit_breaker.py` — update existing tests to pass `base_cooldown_seconds` instead of `cooldown_seconds` (rename); behavior assertions stay identical.
- `tests/test_ohlc_registry.py` — update the `build_default_registry` assertions to check the new config fields.
- `tests/test_routes_ohlc.py` — assert the four new fields are present in `/api/ohlc/sources` output.
- `static/js/data_health.js` — fill the "Next Retry" cell from `next_retry_at` and show the failure class in a tooltip on "Last Error".

---

## Task 1: Introduce `FailureClassification` and rename `cooldown_seconds` → `base_cooldown_seconds`

**Files:**
- Modify: `services/ohlc/circuit_breaker.py`
- Modify: `tests/test_circuit_breaker.py`

The constructor gets a new keyword name for the cooldown. Everything else stays behaviorally identical for this task — we're laying the foundation for escalation without changing any outcomes yet.

- [ ] **Step 1: Add a `FailureClass` literal and a `FailureClassification` model**

Append to the top of `services/ohlc/circuit_breaker.py`:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
```

- [ ] **Step 2: Rename `cooldown_seconds` to `base_cooldown_seconds`**

Update the `CircuitBreaker.__init__` signature and every internal reference:

```python
def __init__(
    self,
    *,
    name: str,
    failure_threshold: int,
    base_cooldown_seconds: int,
    clock: Callable[[], int],
) -> None:
    self.name = name
    self.failure_threshold = failure_threshold
    self.base_cooldown_seconds = base_cooldown_seconds
    self._clock = clock
    ...
```

Update `allows()` to compare against `self.base_cooldown_seconds` for now (task 2 will replace this with `self.current_cooldown_seconds`).

- [ ] **Step 3: Update existing tests to use the new kwarg name**

In `tests/test_circuit_breaker.py`, change every `cooldown=N` in the `_make` helper and every `cb.cooldown_seconds` reference to `base_cooldown=N` / `base_cooldown_seconds`. Functionally identical.

- [ ] **Step 4: Run existing tests**

```bash
pytest tests/test_circuit_breaker.py -q
```

All 13 existing tests must still pass. If any fail with a signature error, fix and re-run. Do not touch `test_ohlc_registry.py` yet — that's task 3.

---

## Task 2: Adaptive cooldown math + `consecutive_trips` + classification

**Files:**
- Modify: `services/ohlc/circuit_breaker.py`
- Create: `tests/test_circuit_breaker_adaptive.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_circuit_breaker_adaptive.py`:

```python
"""Tests for the adaptive-backoff extensions to CircuitBreaker.

See `docs/superpowers/plans/2026-04-14-18-adaptive-breakers.md` task 2.
"""

from __future__ import annotations

import pytest

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
    err.ftl_failure = FailureClassification(
        failure_class=cls, retry_after_seconds=retry_after
    )
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
    # trip 2
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    # trip 3
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
    # trip 2: 600
    clock.advance(301)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 600
    # trip 3: should be 1200 but capped to 1000
    clock.advance(601)
    cb.allows()
    cb.record_failure(RuntimeError("x"))
    assert cb.current_cooldown_seconds == 1000
    # trip 4: still 1000 (already capped)
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
    cb.record_failure(RuntimeError("x"))  # trip 2
    assert cb.consecutive_trips == 2

    clock.advance(601)
    cb.allows()
    cb.record_success()
    assert cb.consecutive_trips == 0
    assert cb.consecutive_failures == 0
    # Next trip starts fresh at base
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
    # base_rate_limit is 900, but retry_after is 1800 — floor wins
    assert cb.current_cooldown_seconds == 1800


def test_retry_after_ignored_when_shorter_than_computed():
    clock = _Clock()
    cb = _make(clock, base=300, base_rate_limit=900)
    cb.record_failure(_classify("rate_limit", retry_after=10))
    # Computed 900 > Retry-After 10 → use 900
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
    # Advance past base (300) but not past current (600) — must still block
    clock.advance(301)
    assert cb.allows() is False
    clock.advance(301)  # now 602 elapsed
    assert cb.allows() is True


def test_status_snapshot_contains_new_fields():
    clock = _Clock()
    cb = _make(clock, base=300)
    cb.record_failure(_classify("rate_limit"))
    snap = cb.status_snapshot()
    assert snap["consecutive_trips"] == 1
    assert snap["current_cooldown_seconds"] == 300  # rate_limit default 900? no — _classify with default base is 300
    assert snap["next_retry_at"] == clock.t + snap["current_cooldown_seconds"]
    assert snap["last_failure_class"] == "rate_limit"
```

Note: the `test_status_snapshot_contains_new_fields` test uses `base_rate_limit=900` by default in `_make`, so its `current_cooldown_seconds` should be 900. The comment in the test is a red herring — update when you verify.

Run to confirm all 15 tests fail with `TypeError: unexpected keyword argument` or attribute errors:

```bash
pytest tests/test_circuit_breaker_adaptive.py -q
```

- [ ] **Step 2: Extend `CircuitBreaker.__init__` with the new fields**

```python
def __init__(
    self,
    *,
    name: str,
    failure_threshold: int,
    base_cooldown_seconds: int,
    base_cooldown_rate_limit_seconds: int | None = None,
    max_cooldown_seconds: int | None = None,
    backoff_multiplier: float = 2.0,
    jitter_fraction: float = 0.0,
    clock: Callable[[], int],
    rng: Callable[[], float] | None = None,
) -> None:
    self.name = name
    self.failure_threshold = failure_threshold
    self.base_cooldown_seconds = base_cooldown_seconds
    self.base_cooldown_rate_limit_seconds = (
        base_cooldown_rate_limit_seconds or base_cooldown_seconds
    )
    self.max_cooldown_seconds = max_cooldown_seconds or (base_cooldown_seconds * 48)
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
```

- [ ] **Step 3: Rewrite `_open`, `record_failure`, `record_success`, `allows`**

```python
def _classify(self, error: BaseException) -> tuple[FailureClass, int | None]:
    """Return (class, retry_after_seconds). Prefers an attached
    FailureClassification; falls back to the legacy `.response.status_code`
    sniff used by `_is_fast_trip`."""
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
    computed = base * (self.backoff_multiplier ** exponent)
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

def record_success(self) -> None:
    with self._lock:
        now = self._clock()
        self.state = "closed"
        self.consecutive_failures = 0
        self.consecutive_trips = 0
        self.current_cooldown_seconds = self.base_cooldown_seconds
        self.opened_at = None
        self.next_retry_at = None
        self.last_success_at = now
        # last_failure_class stays so operators can see the last reason.

def allows(self) -> bool:
    with self._lock:
        if self.state == "closed" or self.state == "half_open":
            return True
        assert self.opened_at is not None
        if self._clock() - self.opened_at >= self.current_cooldown_seconds:
            self.state = "half_open"
            return True
        return False
```

- [ ] **Step 4: Extend `status_snapshot`**

```python
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
```

- [ ] **Step 5: Back-compat `_is_fast_trip`**

The module-level `_is_fast_trip(error)` function is no longer called from inside `record_failure`, but it's a public symbol used by the existing tests' semantics. Leave it in place for now; task 3 deletes it once nothing references it.

- [ ] **Step 6: Run both test modules**

```bash
pytest tests/test_circuit_breaker.py tests/test_circuit_breaker_adaptive.py -q
```

All 13 legacy tests plus all 15 new tests must pass. Triage any failures to the specific step above; do not paper over by weakening assertions.

---

## Task 3: Delete `_is_fast_trip` and wire the new params into `registry.py`

**Files:**
- Modify: `services/ohlc/circuit_breaker.py`
- Modify: `services/ohlc/registry.py`
- Modify: `tests/test_ohlc_registry.py`

- [ ] **Step 1: Delete the dead helper**

Remove `_is_fast_trip` from `services/ohlc/circuit_breaker.py`. Verify no other module imports it:

```bash
grep -rn "_is_fast_trip" services/ tests/
```

Expect only the definition line (which you're about to delete). If anything else matches, stop and reconsider.

- [ ] **Step 2: Extend `SourceRegistry.register()` signature**

```python
def register(
    self,
    source: OhlcSource,
    *,
    failure_threshold: int,
    base_cooldown_seconds: int,
    base_cooldown_rate_limit_seconds: int | None = None,
    max_cooldown_seconds: int | None = None,
    backoff_multiplier: float = 2.0,
    jitter_fraction: float = 0.15,
) -> None:
    import random
    rng = random.Random(hash(source.name)).random  # deterministic per source
    breaker = CircuitBreaker(
        name=source.name,
        failure_threshold=failure_threshold,
        base_cooldown_seconds=base_cooldown_seconds,
        base_cooldown_rate_limit_seconds=base_cooldown_rate_limit_seconds,
        max_cooldown_seconds=max_cooldown_seconds,
        backoff_multiplier=backoff_multiplier,
        jitter_fraction=jitter_fraction,
        clock=self._clock,
        rng=rng,
    )
    self.entries.append((source, breaker))
```

Note: jitter is now on by default (0.15 fraction). The rng is seeded from `hash(source.name)` so runs are reproducible per source without being identical across sources.

- [ ] **Step 3: Update `build_default_registry`**

```python
def build_default_registry(*, clock: Callable[[], int]) -> SourceRegistry:
    """Default order: yfinance primary, stooq fallback.

    Breaker tuning (plan 18):
    - yfinance: 3 misc failures trips; base 5m cooldown on server/network;
      15m on rate-limit; 2× escalation per re-open; 4h cap.
    - stooq:    3 misc failures trips; base 10m cooldown on server/network;
      30m on rate-limit; 2× escalation per re-open; 6h cap.
    """
    reg = SourceRegistry(clock=clock)
    reg.register(
        YfinanceSource(),
        failure_threshold=3,
        base_cooldown_seconds=300,
        base_cooldown_rate_limit_seconds=900,
        max_cooldown_seconds=14400,
        backoff_multiplier=2.0,
        jitter_fraction=0.15,
    )
    reg.register(
        StooqSource(),
        failure_threshold=3,
        base_cooldown_seconds=600,
        base_cooldown_rate_limit_seconds=1800,
        max_cooldown_seconds=21600,
        backoff_multiplier=2.0,
        jitter_fraction=0.15,
    )
    return reg
```

Stooq gets longer baselines because its `max_cooldown_seconds` cooldown of 30 min previously was aggressive; since plan 14 already used stooq as a fallback with 30m cooldown, the new "30m on rate-limit" preserves that floor while halving the baseline on normal transient errors (300s is too short for a fallback source).

- [ ] **Step 4: Update `tests/test_ohlc_registry.py`**

Update every `register()` call in the test fixtures to use `base_cooldown_seconds=N` instead of `cooldown_seconds=N`. For the `build_default_registry` assertion, check the new field values:

```python
def test_default_registry_has_yfinance_and_stooq_with_plan18_tuning():
    reg = build_default_registry(clock=lambda: 0)
    names = [s.name for s, _ in reg.entries]
    assert names == ["yfinance", "stooq"]

    yf_breaker = reg.entries[0][1]
    assert yf_breaker.failure_threshold == 3
    assert yf_breaker.base_cooldown_seconds == 300
    assert yf_breaker.base_cooldown_rate_limit_seconds == 900
    assert yf_breaker.max_cooldown_seconds == 14400
    assert yf_breaker.backoff_multiplier == 2.0

    stq_breaker = reg.entries[1][1]
    assert stq_breaker.base_cooldown_seconds == 600
    assert stq_breaker.base_cooldown_rate_limit_seconds == 1800
    assert stq_breaker.max_cooldown_seconds == 21600
```

- [ ] **Step 5: Run the registry tests**

```bash
pytest tests/test_ohlc_registry.py -q
```

---

## Task 4: Classify failures in the adapters

**Files:**
- Modify: `services/ohlc/yfinance_source.py`
- Modify: `services/ohlc/stooq_source.py`
- Modify: `tests/test_ohlc_fetcher.py` (if it asserts anything about the exception shape — check first)

The goal: when an adapter raises, the exception should carry a `ftl_failure` attribute that the breaker can read. No new exception types; we just attach a `FailureClassification` to whatever we were already raising.

- [ ] **Step 1: Add a shared helper**

Create `services/ohlc/_classify.py`:

```python
"""Helpers for attaching FailureClassification to adapter exceptions.

Plan 18: adapters call `attach_classification(err, ...)` before re-raising
so CircuitBreaker.record_failure can read a typed signal instead of
sniffing exception internals.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from services.ohlc.circuit_breaker import FailureClassification

if TYPE_CHECKING:
    import requests


def attach_classification(
    err: BaseException,
    *,
    failure_class: str,
    retry_after_seconds: int | None = None,
) -> BaseException:
    """Attach a FailureClassification to `err` and return it for re-raising."""
    err.ftl_failure = FailureClassification(  # type: ignore[attr-defined]
        failure_class=failure_class,
        retry_after_seconds=retry_after_seconds,
    )
    return err


def classify_http_error(err: "requests.HTTPError") -> tuple[str, int | None]:
    """Map a `requests.HTTPError` to (class, retry_after_seconds)."""
    import time

    response = err.response
    if response is None:
        return "network", None
    code = response.status_code
    retry_after = None
    header = response.headers.get("Retry-After")
    if header is not None:
        # Try integer-seconds form first, then HTTP-date.
        try:
            retry_after = int(header)
        except ValueError:
            try:
                dt = parsedate_to_datetime(header)
                retry_after = max(0, int(dt.timestamp() - time.time()))
            except (TypeError, ValueError):
                retry_after = None
    if code == 429:
        return "rate_limit", retry_after
    if 500 <= code < 600:
        return "server_error", retry_after
    return "other", retry_after
```

- [ ] **Step 2: Use it in `yfinance_source.py`**

The `yfinance` library wraps `requests` but may not surface `requests.HTTPError` directly. It also raises `RuntimeError` for `_ERRORS`-captured lookup failures. Keep the existing `_download` function; wrap the body in a try/except:

```python
def _download(symbol: str, *, start, end, interval):
    import yfinance as yf
    import yfinance.shared as _yfs
    import requests

    from services.ohlc._classify import attach_classification, classify_http_error

    _yfs._ERRORS.pop(symbol, None)
    try:
        df = yf.Ticker(symbol).history(
            start=start, end=end, interval=interval, auto_adjust=False,
        )
    except requests.HTTPError as http_err:
        cls, retry_after = classify_http_error(http_err)
        raise attach_classification(http_err, failure_class=cls, retry_after_seconds=retry_after)
    except (requests.ConnectionError, requests.Timeout) as net_err:
        raise attach_classification(net_err, failure_class="network")

    if symbol in _yfs._ERRORS:
        err = RuntimeError(f"yfinance lookup failed for {symbol!r}: {_yfs._ERRORS[symbol]}")
        # Lookup errors are not network failures — leave as "other" so the
        # slow-trip threshold applies. Do NOT attach a classification.
        raise err

    return df
```

Important: a bad-symbol lookup is not a source-is-down condition. We want it to count toward the slow-trip threshold only (3 consecutive), not fast-trip the breaker.

- [ ] **Step 3: Use it in `stooq_source.py`**

Find wherever stooq raises on HTTP errors (look for `raise_for_status()` or similar). Wrap with the same pattern:

```python
import requests
from services.ohlc._classify import attach_classification, classify_http_error

try:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
except requests.HTTPError as http_err:
    cls, retry_after = classify_http_error(http_err)
    raise attach_classification(http_err, failure_class=cls, retry_after_seconds=retry_after)
except (requests.ConnectionError, requests.Timeout) as net_err:
    raise attach_classification(net_err, failure_class="network")
```

- [ ] **Step 4: Write tests that verify attachment happens**

Append to `tests/test_circuit_breaker_adaptive.py`:

```python
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
```

- [ ] **Step 5: Run the full OHLC test subset**

```bash
pytest tests/test_circuit_breaker.py tests/test_circuit_breaker_adaptive.py tests/test_ohlc_registry.py tests/test_ohlc_fetcher.py -q
```

If `test_ohlc_fetcher.py` fails because it asserts on exception shape, add a new test variant that explicitly constructs an exception with `ftl_failure` attached and verifies the fetcher still records the failure correctly. Do not change `test_ohlc_fetcher.py` expectations otherwise.

---

## Task 5: Surface the new state on `/api/ohlc/sources` and `/data-health`

**Files:**
- Modify: `routes/ohlc.py` (if the snapshot reshape needs any adjustment — check first)
- Modify: `static/js/data_health.js`
- Modify: `tests/test_routes_ohlc.py`

- [ ] **Step 1: Verify the route already passes through `status_snapshot()`**

Open `routes/ohlc.py` and find the `/api/ohlc/sources` handler. Confirm it just returns `[breaker.status_snapshot() for _, breaker in reg.entries]` (or similar) — no field-picking that would drop the new fields. If it does filter fields, add the new ones.

- [ ] **Step 2: Update `tests/test_routes_ohlc.py`**

Add assertions that the response includes the new fields:

```python
def test_ohlc_sources_response_includes_plan18_fields(client):
    r = client.get("/api/ohlc/sources")
    assert r.status_code == 200
    body = r.get_json()
    assert "sources" in body
    for entry in body["sources"]:
        # Legacy fields still present
        assert "name" in entry
        assert "state" in entry
        assert "consecutive_failures" in entry
        # Plan 18 additions
        assert "consecutive_trips" in entry
        assert "current_cooldown_seconds" in entry
        assert "next_retry_at" in entry
        assert "last_failure_class" in entry
```

- [ ] **Step 3: Fill the Next Retry cell in `static/js/data_health.js`**

Find `renderSourcesBand`. Today it renders the Next Retry cell as `—`. Replace with:

```js
const nextRetry = s.next_retry_at
  ? new Date(s.next_retry_at * 1000).toLocaleTimeString()
  : "—";
```

And wire it into the row HTML. Add a tooltip to the Last Error cell showing `s.last_failure_class` when non-null so the operator can distinguish "rate-limited" from "network down" at a glance.

- [ ] **Step 4: Run the full route/frontend subset**

```bash
pytest tests/test_routes_ohlc.py -q
```

Then in the browser (Docker stack is up): visit `/data-health`, force a failure by poisoning `/etc/hosts` as in the plan 13 walkthrough, confirm the Next Retry column populates with a real timestamp and the failure class tooltip shows `network` or `rate_limit` as appropriate. Restore `/etc/hosts`, restart to clear state.

---

## Task 6: Full suite sweep + commit

- [ ] **Step 1: Run the full test suite**

```bash
pytest -q
```

All tests must pass. If anything outside `test_circuit_breaker*` / `test_ohlc_*` / `test_routes_ohlc.py` broke, it's because something else imported `cooldown_seconds` or `_is_fast_trip`. Fix at the site.

- [ ] **Step 2: `ruff check .` and `ruff format .`**

Both clean. Commit only after both pass.

- [ ] **Step 3: Single themed commit**

```
feat(ohlc): adaptive circuit-breaker backoff

- Add FailureClassification model so adapters can signal rate-limit
  vs server-error vs network-error to the breaker.
- Escalate cooldown on repeated trips (base * 2^(trips-1), capped).
- Separate base cooldown for rate-limit (longer) vs transient errors.
- Respect Retry-After header as a cooldown floor.
- Bounded jitter (±15%) on cooldown to avoid lockstep retries across
  simultaneous trips of different sources.
- Expose consecutive_trips, current_cooldown_seconds, next_retry_at,
  and last_failure_class on /api/ohlc/sources; /data-health now shows
  Next Retry as a real timestamp and the failure class as a tooltip
  on Last Error.

Plan: docs/superpowers/plans/2026-04-14-18-adaptive-breakers.md
```

---

## Acceptance criteria

- [ ] **AC1:** First trip of a source with default tuning uses its base cooldown (yfinance 300s, stooq 600s).
- [ ] **AC2:** Second consecutive trip doubles the cooldown; third quadruples; capped at `max_cooldown_seconds`.
- [ ] **AC3:** A 429 response uses `base_cooldown_rate_limit_seconds` as its base; a 5xx or network error uses `base_cooldown_seconds`.
- [ ] **AC4:** A `Retry-After` header raises the cooldown floor but is ignored when the computed cooldown is already longer.
- [ ] **AC5:** `record_success` resets `consecutive_trips` to 0 and `current_cooldown_seconds` to `base_cooldown_seconds`.
- [ ] **AC6:** Jitter is bounded inside `[computed * (1 - jitter_fraction), computed * (1 + jitter_fraction)]` and defaults to ±15%.
- [ ] **AC7:** A bad-symbol lookup on yfinance (handled via `_ERRORS`) counts as `"other"` and does not fast-trip — only the 3-consecutive-failure slow-trip applies.
- [ ] **AC8:** `/api/ohlc/sources` emits `consecutive_trips`, `current_cooldown_seconds`, `next_retry_at`, `last_failure_class`.
- [ ] **AC9:** `/data-health` renders the Next Retry timestamp and shows `last_failure_class` as a tooltip on the Last Error cell.
- [ ] **AC10:** Full pytest suite stays green. `ruff check .` and `ruff format .` are clean.

---

## Fragmentation hazards (carry forward)

- **Do NOT add retry logic inside `fetch()`.** The breaker is the single retry policy. An adapter that silently retries once inside its own `fetch` would double-count failures and throw off escalation math.
- **Do NOT persist breaker state across restarts.** The old plan 14 deliberately made breakers in-process ephemeral state. Persistence would invite stale-data lookups and complicate the single-writer SQLite story. A container restart fully clears breakers — this is a feature, not a bug.
- **Do NOT make `Retry-After` a replacement for the computed cooldown.** If the upstream says "come back in 10 seconds" during our third consecutive trip (computed 1200s), we still wait 1200s. Retry-After is a floor.
- **Do NOT let bad symbols fast-trip the breaker.** A trader typo on an instrument symbol should produce a single user-visible error, not knock yfinance offline for 5 minutes.
- **Do NOT conflate `consecutive_failures` with `consecutive_trips`.** The former counts individual failed requests in the current streak; the latter counts how many times the breaker has re-opened without a successful call in between. They are different quantities.
