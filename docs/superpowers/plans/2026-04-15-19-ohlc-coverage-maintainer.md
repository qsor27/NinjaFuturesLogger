# Plan 19 — OHLC Coverage Maintainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild OHLC coverage so every active contract is continuously maintained by a scheduler-driven maintainer that respects yfinance rate limits, fetches the exact-contract symbol, and reports honest data-health state.

**Architecture:** One `ohlc_coverage_maintainer` job (every 30 min) plus `ohlc_historical_sweep` (every 4h) plus cron jobs for 1d/1wk/1mo replace the post-import OHLC hook and the current recent/week refresh jobs. A global `TokenBucket` gates every outbound fetch. `instrument_coverage` tracks an active/winding_down/retired state per contract. Migrations purge mis-tagged continuous-series bars and populate per-contract `contract_template` values. 4h candles become a read-time view transform over stored 1h bars.

**Tech Stack:** Python 3.11, Flask, APScheduler, SQLite (WAL), Pydantic v2, yfinance, stooq (HTTP), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-04-14-ohlc-coverage-maintainer-design.md`

---

## File Structure

**New modules:**
- `services/ohlc/rate_limiter.py` — `TokenBucket` class
- `services/ohlc/aggregate.py` — `derive_4h(bars_1h)` pure function
- `services/ohlc/coverage_state.py` — `refresh_instrument_coverage_state()`, state transitions
- `services/ohlc/coverage_maintainer.py` — maintainer tick + historical sweep tick
- `services/ohlc/reach.py` — `PROVIDER_REACH` table + `is_out_of_reach()` helper

**Modified modules:**
- `services/instruments.py` — `source_symbol()` renders contract templates; new `parse_instrument(s)` helper
- `services/instrument_registry.py` — seed default yfinance `contract_template` values
- `services/ohlc/yfinance_source.py` — use rendered template, no code change needed beyond what `source_symbol` returns (verification only)
- `services/ohlc/stooq_source.py` — same — verification only
- `services/ohlc/fetcher.py` — acquires token before `source.fetch()`
- `services/ohlc/gap_detection.py` — classify slots outside provider reach
- `services/ohlc/registry.py` — retuned yfinance breaker numbers
- `routes/monitoring.py` — `out_of_reach` / `pending` / `maintainer` panel
- `routes/settings.py` — pin / retire / reactivate endpoints
- `routes/pages.py` — chart route handles `tf=4h` via aggregate helper
- `templates/data_health.html` — notices + maintainer panel skeleton
- `templates/instruments.html` — pin/retire controls
- `static/js/data_health.js` — new cell states, maintainer panel rendering
- `static/js/instruments.js` — pin/retire wiring
- `app.py` — drop post-import OHLC hook, drop `ohlc_refresh_recent`, drop `ohlc_refresh_week`, register new jobs

**New migrations:**
- `migrations/008_instrument_coverage.sql` — `CREATE TABLE instrument_coverage`
- `migrations/009_purge_mistagged_bars.sql` — `DELETE FROM bars`
- `migrations/010_contract_templates.py` — Python migration to update `instruments.json`

**New tests (one per module):**
- `tests/test_rate_limiter.py`
- `tests/test_aggregate_4h.py`
- `tests/test_coverage_state.py`
- `tests/test_coverage_maintainer.py`
- `tests/test_reach.py`
- `tests/test_migration_008.py`
- `tests/test_migration_009.py`
- `tests/test_migration_010.py`
- `tests/test_instruments_contract_parse.py`

**Modified tests:**
- `tests/test_instruments.py` — template rendering cases
- `tests/test_yfinance_source.py` — contract symbol used for suffixed instruments
- `tests/test_stooq_source.py` — returns empty for suffixed instruments
- `tests/test_gap_detection.py` — `out_of_reach` classification
- `tests/test_routes_monitoring.py` — new cell states + maintainer panel
- `tests/test_settings_routes_instruments.py` — pin/retire/reactivate
- `tests/test_ohlc_fetcher.py` — token bucket acquire in happy path
- `tests/test_ohlc_registry.py` — retuned breaker numbers
- `tests/test_routes_chart_timeframes.py` — 4h derived bars in chart response

**Dependency order (phases):**
1. **Phase A** — Reach, rate limiter, 4h aggregate (pure, no deps)
2. **Phase B** — Contract parsing + symbology + source adapter verification
3. **Phase C** — Migrations 008/009/010
4. **Phase D** — Coverage state module
5. **Phase E** — Fetcher + token bucket integration
6. **Phase F** — Coverage maintainer + historical sweep
7. **Phase G** — Circuit breaker retune + app.py job wiring
8. **Phase H** — Data-health + settings UI
9. **Phase I** — Chart 4h route + smoke test

---

## Phase A — Foundation modules

### Task 1: Provider reach table

**Files:**
- Create: `services/ohlc/reach.py`
- Test: `tests/test_reach.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reach.py
from services.ohlc.reach import PROVIDER_REACH, is_out_of_reach


def test_provider_reach_table_has_all_intraday_timeframes():
    for tf in ("1m", "5m", "15m", "1h", "1d", "1wk", "1mo"):
        assert tf in PROVIDER_REACH


def test_1m_reach_is_7_days():
    assert PROVIDER_REACH["1m"] == 7 * 86400


def test_5m_and_15m_reach_is_60_days():
    assert PROVIDER_REACH["5m"] == 60 * 86400
    assert PROVIDER_REACH["15m"] == 60 * 86400


def test_1h_reach_is_730_days():
    assert PROVIDER_REACH["1h"] == 730 * 86400


def test_1d_reach_is_effectively_unlimited():
    assert PROVIDER_REACH["1d"] >= 30 * 365 * 86400


def test_is_out_of_reach_flags_old_1m_slot():
    now = 1_000_000_000
    old = now - 10 * 86400  # 10 days, beyond 7-day reach
    assert is_out_of_reach("1m", slot_ts=old, now=now) is True


def test_is_out_of_reach_passes_recent_1m_slot():
    now = 1_000_000_000
    recent = now - 3 * 86400  # 3 days, within reach
    assert is_out_of_reach("1m", slot_ts=recent, now=now) is False


def test_is_out_of_reach_unknown_timeframe_raises():
    import pytest
    with pytest.raises(ValueError):
        is_out_of_reach("2h", slot_ts=0, now=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reach.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.ohlc.reach'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/ohlc/reach.py
"""Provider reach table — how far back each timeframe can be fetched.

Values are the maximum lookback window yfinance will serve in a single
request for each interval, in seconds. `is_out_of_reach` uses these to
distinguish "the provider cannot serve this" from "we haven't fetched
this yet" in gap detection and data-health.
"""

PROVIDER_REACH: dict[str, int] = {
    "1m": 7 * 86400,
    "5m": 60 * 86400,
    "15m": 60 * 86400,
    "1h": 730 * 86400,
    "1d": 40 * 365 * 86400,   # effectively unlimited
    "1wk": 40 * 365 * 86400,
    "1mo": 40 * 365 * 86400,
}


def is_out_of_reach(timeframe: str, *, slot_ts: int, now: int) -> bool:
    """Return True if a slot at `slot_ts` is beyond the provider's reach at `now`."""
    if timeframe not in PROVIDER_REACH:
        raise ValueError(f"unknown timeframe: {timeframe}")
    return (now - slot_ts) > PROVIDER_REACH[timeframe]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reach.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/reach.py tests/test_reach.py
git commit -m "feat(ohlc): add provider-reach table for gap classification"
```

---

### Task 2: TokenBucket rate limiter

**Files:**
- Create: `services/ohlc/rate_limiter.py`
- Test: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rate_limiter.py
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
    clock.advance(4)  # 4 * 0.5 = 2 tokens
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rate_limiter.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# services/ohlc/rate_limiter.py
"""Global token bucket gating every OHLC provider call.

Capacity 30, refill 0.5/sec (= 30/min). Shared across sources, shared
across jobs. The fetcher acquires one token before each source.fetch()
call. Blocking acquire with bounded wait — callers that time out
defer to the next cycle rather than queueing indefinitely.
"""

import threading
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
        start = self._clock()
        with self._cond:
            while True:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._acquired_total += 1
                    break
                waited = self._clock() - start
                if waited >= timeout:
                    self._timeouts_total += 1
                    raise TimeoutError("token bucket timed out")
                self._cond.wait(timeout=max(0.01, timeout - waited))
        waited_ms = int((self._clock() - start) * 1000)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rate_limiter.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat(ohlc): add global token bucket rate limiter"
```

---

### Task 3: 4h aggregation helper

**Files:**
- Create: `services/ohlc/aggregate.py`
- Test: `tests/test_aggregate_4h.py`

Block alignment: CME session opens at 17:00 CT. We align 4h blocks to the session boundaries. Block boundaries (in session-local CT): `17:00, 21:00, 01:00, 05:00, 09:00, 13:00`. The window `13:00-17:00` crosses the 16:00-17:00 daily break — we shorten it to `13:00-16:00` (3 bars) and since it only has 3 constituents, it is **not emitted** (partial-block rule).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aggregate_4h.py
from models.bar import Bar
from services.ohlc.aggregate import derive_4h


def _bar(ts: int, o: float, h: float, lo: float, c: float, v: int) -> Bar:
    return Bar(
        instrument="MNQ JUN26",
        timeframe="1h",
        time=ts,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
        source="yfinance",
    )


# A CT 17:00 session open on 2026-04-14 in America/Chicago corresponds
# to 2026-04-14T22:00:00Z = unix 1776290400.
BASE_1700_CT = 1776290400


def test_empty_input_returns_empty():
    assert derive_4h([]) == []


def test_single_complete_block_emits_one_bar():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100 + h, 110 + h, 90 + h, 105 + h, 1000)
        for h in range(4)
    ]
    out = derive_4h(bars_1h)
    assert len(out) == 1
    b = out[0]
    assert b.timeframe == "4h"
    assert b.time == BASE_1700_CT
    assert b.open == 100
    assert b.high == 113
    assert b.low == 90
    assert b.close == 108
    assert b.volume == 4000
    assert b.source == "derived-1h"
    assert b.instrument == "MNQ JUN26"


def test_partial_block_dropped():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(3)  # only 3 of 4 bars
    ]
    assert derive_4h(bars_1h) == []


def test_multiple_complete_blocks():
    bars_1h = [
        _bar(BASE_1700_CT + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(8)  # two full blocks
    ]
    out = derive_4h(bars_1h)
    assert len(out) == 2
    assert out[0].time == BASE_1700_CT
    assert out[1].time == BASE_1700_CT + 4 * 3600


def test_gap_in_middle_drops_straddling_block():
    bars_1h = [
        _bar(BASE_1700_CT + 0 * 3600, 100, 110, 90, 105, 1000),
        _bar(BASE_1700_CT + 1 * 3600, 100, 110, 90, 105, 1000),
        _bar(BASE_1700_CT + 2 * 3600, 100, 110, 90, 105, 1000),
        # missing hour 3
        _bar(BASE_1700_CT + 4 * 3600, 100, 110, 90, 105, 1000),
    ]
    assert derive_4h(bars_1h) == []


def test_13_to_17_ct_block_spanning_daily_break_not_emitted():
    # The block aligned at 13:00 CT only has 3 hours before the 16:00-17:00
    # break; those 3 bars must not synthesize a 4h bar.
    base_1300_ct = BASE_1700_CT - 4 * 3600  # 13:00 CT the same session day
    bars_1h = [
        _bar(base_1300_ct + h * 3600, 100, 110, 90, 105, 1000)
        for h in range(3)  # 13, 14, 15 (16 is in break)
    ]
    assert derive_4h(bars_1h) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aggregate_4h.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# services/ohlc/aggregate.py
"""Read-time 4h view transform over stored 1h bars.

4h is the one allowed upscale in the OHLC subsystem. Bars are never
persisted — this helper is called when a chart route asks for tf=4h.
Blocks align to CME session opens (17:00 CT). Partial blocks (fewer
than 4 hours present) are silently dropped — the chart shows a gap.

The 16:00-17:00 daily break falls naturally because there is no 1h
bar in that hour; any block that straddles it will be partial and
therefore omitted.
"""

from models.bar import Bar

_BLOCK_SECONDS = 4 * 3600
_STEP = 3600


def derive_4h(bars_1h: list[Bar]) -> list[Bar]:
    if not bars_1h:
        return []
    by_time = {b.time: b for b in sorted(bars_1h, key=lambda b: b.time)}
    instrument = bars_1h[0].instrument

    # Block start alignment: anchor to the earliest 1h bar's time floored
    # to a 4h boundary from the session open (17:00 CT = hour 22 UTC, but
    # we align purely by modular arithmetic against _BLOCK_SECONDS with
    # the 17:00-CT anchor as zero). Using unix math avoids any tz code:
    # all CT 17:00 opens fall on timestamps where (t - ANCHOR) % 4h == 0,
    # where ANCHOR is any one known 17:00-CT timestamp.
    anchor = _earliest_session_anchor(by_time)

    out: list[Bar] = []
    start = anchor
    end = max(by_time) + _STEP
    while start < end:
        block_times = [start + i * _STEP for i in range(4)]
        block_bars = [by_time.get(t) for t in block_times]
        if all(b is not None for b in block_bars):
            out.append(_rollup(instrument, start, block_bars))  # type: ignore[arg-type]
        start += _BLOCK_SECONDS
    return out


def _earliest_session_anchor(by_time: dict[int, Bar]) -> int:
    # Find the smallest block-start <= the earliest bar, aligned to 4h
    # from *any* 17:00-CT anchor. We use 2026-04-14 22:00 UTC (17:00 CT DST)
    # as the fixed reference point — any other 17:00 CT instant differs
    # from it by a multiple of 86400, which is a multiple of 4h.
    REF = 1776290400  # 2026-04-14T22:00:00Z == 2026-04-14 17:00 America/Chicago (CDT)
    first = min(by_time)
    offset = (first - REF) % _BLOCK_SECONDS
    return first - offset


def _rollup(instrument: str, start_ts: int, bars: list[Bar]) -> Bar:
    return Bar(
        instrument=instrument,
        timeframe="4h",
        time=start_ts,
        open=bars[0].open,
        high=max(b.high for b in bars),
        low=min(b.low for b in bars),
        close=bars[-1].close,
        volume=sum(b.volume for b in bars),
        source="derived-1h",
    )
```

Note: `Bar.timeframe` is typed `Literal["1m", "5m", "15m", "1h", "4h", "1d"]` so `"4h"` is already allowed by the model — no model change needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aggregate_4h.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/aggregate.py tests/test_aggregate_4h.py
git commit -m "feat(ohlc): add read-time 4h aggregation helper"
```

---

## Phase B — Contract symbology

### Task 4: Parse instrument string into (root, contract suffix)

**Files:**
- Modify: `services/instruments.py`
- Test: `tests/test_instruments_contract_parse.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_instruments_contract_parse.py
import pytest

from services.instruments import parse_instrument


def test_plain_root():
    assert parse_instrument("MNQ") == ("MNQ", None)


def test_root_with_contract_suffix():
    assert parse_instrument("MNQ JUN26") == ("MNQ", "JUN26")


def test_multi_space_raises():
    with pytest.raises(ValueError):
        parse_instrument("MNQ JUN 26")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parse_instrument("")


def test_two_digit_year_six_char_suffix():
    assert parse_instrument("ES MAR26") == ("ES", "MAR26")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_instruments_contract_parse.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_instrument'`.

- [ ] **Step 3: Write minimal implementation**

Add to `services/instruments.py` (after `base_symbol`, before `get_multiplier`):

```python
def parse_instrument(instrument: str) -> tuple[str, str | None]:
    """Split a NinjaTrader instrument string into (root, contract_suffix).

    Accepts "MNQ" or "MNQ JUN26". Raises ValueError for empty strings or
    strings with more than one space. The contract suffix is whatever follows
    the single space — rendering into a source symbol happens in source_symbol().
    """
    if not instrument:
        raise ValueError("empty instrument string")
    parts = instrument.split(" ")
    if len(parts) == 1:
        return parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValueError(f"malformed instrument: {instrument!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_instruments_contract_parse.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/instruments.py tests/test_instruments_contract_parse.py
git commit -m "feat(instruments): parse_instrument helper"
```

---

### Task 5: Contract-template rendering in `source_symbol`

**Files:**
- Modify: `services/instruments.py`
- Modify: `tests/test_instruments.py`

CME month codes table:

| Month     | Code | Month     | Code |
|-----------|------|-----------|------|
| January   | F    | July      | N    |
| February  | G    | August    | Q    |
| March     | H    | September | U    |
| April     | J    | October   | V    |
| May       | K    | November  | X    |
| June      | M    | December  | Z    |

Contract suffix format from NinjaTrader is a 3-letter month code (upper) + 2-digit year, e.g. `JUN26`. Rendering must convert `JUN` → `M`, yielding `MNQM26.CME` given the template `{ROOT}{M}{YY}.CME`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_instruments.py`:

```python
def test_source_symbol_renders_contract_template_for_yfinance(tmp_path, monkeypatch):
    from services.instruments import set_registry_path, source_symbol
    import json

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {
                            "continuous": "MNQ=F",
                            "contract_template": "{ROOT}{M}{YY}.CME",
                        },
                        "stooq": {
                            "continuous": "mnq.f",
                            "contract_template": None,
                        },
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)
    assert source_symbol("MNQ JUN26", "yfinance") == "MNQM26.CME"
    assert source_symbol("MNQ", "yfinance") == "MNQ=F"
    # stooq has no contract template → None for a suffixed instrument.
    assert source_symbol("MNQ JUN26", "stooq") is None
    # stooq still works for the unsuffixed root.
    assert source_symbol("MNQ", "stooq") == "mnq.f"


def test_source_symbol_all_month_codes(tmp_path):
    from services.instruments import set_registry_path, source_symbol
    import json

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "NQ": {
                    "display_name": "E-mini Nasdaq-100",
                    "multiplier": 20.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {
                            "continuous": "NQ=F",
                            "contract_template": "{ROOT}{M}{YY}.CME",
                        },
                        "stooq": {
                            "continuous": "nq.f",
                            "contract_template": None,
                        },
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    pairs = {
        "JAN": "F",
        "FEB": "G",
        "MAR": "H",
        "APR": "J",
        "MAY": "K",
        "JUN": "M",
        "JUL": "N",
        "AUG": "Q",
        "SEP": "U",
        "OCT": "V",
        "NOV": "X",
        "DEC": "Z",
    }
    for word, code in pairs.items():
        assert source_symbol(f"NQ {word}26", "yfinance") == f"NQ{code}26.CME"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_instruments.py -k "contract_template or all_month_codes" -v`
Expected: FAIL — current `source_symbol` returns continuous.

- [ ] **Step 3: Implement — edit `services/instruments.py`**

Replace the existing `source_symbol` with:

```python
_MONTH_CODES: dict[str, str] = {
    "JAN": "F",
    "FEB": "G",
    "MAR": "H",
    "APR": "J",
    "MAY": "K",
    "JUN": "M",
    "JUL": "N",
    "AUG": "Q",
    "SEP": "U",
    "OCT": "V",
    "NOV": "X",
    "DEC": "Z",
}


def _render_contract_template(template: str, *, root: str, contract: str) -> str | None:
    # contract is "MMMYY" — "JUN26"
    if len(contract) != 5:
        return None
    month_word = contract[:3].upper()
    year = contract[3:]
    if month_word not in _MONTH_CODES or not year.isdigit():
        return None
    return template.format(ROOT=root, M=_MONTH_CODES[month_word], YY=year)


def source_symbol(instrument: str, source: str) -> str | None:
    root, contract = parse_instrument(instrument)
    cfg = _REGISTRY.get(root)
    if cfg is None:
        return None
    if source == "yfinance":
        mapping = cfg.sources.yfinance
    elif source == "stooq":
        mapping = cfg.sources.stooq
    else:
        return None
    if contract is None:
        return mapping.continuous
    if mapping.contract_template:
        return _render_contract_template(
            mapping.contract_template, root=root, contract=contract
        )
    # Suffixed instrument but no template available → no silent fallback.
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_instruments.py -v`
Expected: PASS (including the new tests and all previously-passing ones).

- [ ] **Step 5: Commit**

```bash
git add services/instruments.py tests/test_instruments.py
git commit -m "feat(instruments): render per-contract source symbol from template"
```

---

### Task 6: Verify yfinance and stooq adapters pass through template symbols

No code change expected — the adapters already call `source_symbol()` and pass its result to `_download` / the URL. We add a belt-and-braces test that confirms a suffixed instrument ends up calling the adapter with the rendered symbol and that stooq refuses suffixed instruments.

**Files:**
- Modify: `tests/test_yfinance_source.py`
- Modify: `tests/test_stooq_source.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_yfinance_source.py`:

```python
def test_yfinance_uses_contract_symbol_for_suffixed_instrument(monkeypatch, tmp_path):
    from services.instruments import set_registry_path
    from services.ohlc import yfinance_source as yf_mod
    from services.ohlc.yfinance_source import YfinanceSource
    import json
    import pandas as pd

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {
                            "continuous": "MNQ=F",
                            "contract_template": "{ROOT}{M}{YY}.CME",
                        },
                        "stooq": {
                            "continuous": "mnq.f",
                            "contract_template": None,
                        },
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    seen = {}

    def fake_download(symbol, *, start, end, interval):
        seen["symbol"] = symbol
        return pd.DataFrame()  # empty is fine

    monkeypatch.setattr(yf_mod, "_download", fake_download)
    bars = YfinanceSource().fetch("MNQ JUN26", "1h", 0, 3600)
    assert seen["symbol"] == "MNQM26.CME"
    assert bars == []
```

Append to `tests/test_stooq_source.py`:

```python
def test_stooq_refuses_suffixed_instrument(monkeypatch, tmp_path):
    from services.instruments import set_registry_path
    from services.ohlc import stooq_source as stooq_mod
    from services.ohlc.stooq_source import StooqSource
    import json

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                        "stooq": {"continuous": "mnq.f", "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    called = {"n": 0}

    def fake_http_get(url):
        called["n"] += 1
        return ""

    monkeypatch.setattr(stooq_mod, "_http_get", fake_http_get)
    bars = StooqSource().fetch("MNQ JUN26", "1d", 0, 3600)
    assert bars == []
    assert called["n"] == 0
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_yfinance_source.py tests/test_stooq_source.py -v`
Expected: PASS (the adapters already read from `source_symbol`; behavior flows through from Task 5).

- [ ] **Step 3: Commit**

```bash
git add tests/test_yfinance_source.py tests/test_stooq_source.py
git commit -m "test(ohlc): verify per-contract symbol is used by adapters"
```

---

## Phase C — Migrations

### Task 7: Migration 008 — `instrument_coverage` table

**Files:**
- Create: `migrations/008_instrument_coverage.sql`
- Test: `tests/test_migration_008.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_008.py
from pathlib import Path

from db import connect
from migrations import run_migrations


def test_008_creates_instrument_coverage_table(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(instrument_coverage)").fetchall()}
    assert cols == {
        "instrument",
        "state",
        "last_execution_at",
        "pinned",
        "retired_at",
        "updated_at",
    }


def test_008_state_check_constraint(tmp_path):
    import sqlite3
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    # Valid state
    conn.execute(
        "INSERT INTO instrument_coverage (instrument, state, pinned, updated_at)"
        " VALUES (?, ?, 0, 0)",
        ("MNQ JUN26", "active"),
    )
    # Invalid state
    try:
        conn.execute(
            "INSERT INTO instrument_coverage (instrument, state, pinned, updated_at)"
            " VALUES (?, ?, 0, 0)",
            ("ES MAR26", "bogus"),
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_008.py -v`
Expected: FAIL — table doesn't exist.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/008_instrument_coverage.sql
CREATE TABLE instrument_coverage (
  instrument TEXT PRIMARY KEY,
  state TEXT NOT NULL
    CHECK (state IN ('active','winding_down','retired')),
  last_execution_at INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  retired_at INTEGER,
  updated_at INTEGER NOT NULL
);

CREATE INDEX idx_instrument_coverage_state ON instrument_coverage(state);
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_migration_008.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/008_instrument_coverage.sql tests/test_migration_008.py
git commit -m "feat(db): migration 008 — instrument_coverage table"
```

---

### Task 8: Migration 009 — purge mis-tagged `bars`

**Files:**
- Create: `migrations/009_purge_mistagged_bars.sql`
- Test: `tests/test_migration_009.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_009.py
from pathlib import Path

from db import connect
from migrations import run_migrations


def test_009_purges_all_bars(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    # Apply through 008 only
    import glob, shutil
    tmp_migrations = tmp_path / "migrations"
    tmp_migrations.mkdir()
    for f in sorted(glob.glob("migrations/0*.sql")):
        stem = Path(f).stem
        if stem > "008_instrument_coverage":
            continue
        shutil.copy(f, tmp_migrations / Path(f).name)
    run_migrations(conn, tmp_migrations)
    conn.execute(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('MNQ JUN26','1m',0,1,2,3,4,5,'yfinance',0)"
    )
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1

    # Copy 009 and re-run
    shutil.copy("migrations/009_purge_mistagged_bars.sql", tmp_migrations / "009_purge_mistagged_bars.sql")
    run_migrations(conn, tmp_migrations)
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0


def test_009_is_idempotent(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))  # full run
    # Insert after migration — re-running should leave new rows alone.
    conn.execute(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES ('MNQ JUN26','1m',0,1,2,3,4,5,'yfinance',0)"
    )
    run_migrations(conn, Path("migrations"))
    assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_009.py -v`
Expected: FAIL — 009 file missing.

- [ ] **Step 3: Write the migration**

```sql
-- migrations/009_purge_mistagged_bars.sql
-- Purge existing bars that were fetched against the continuous front-month
-- symbol but stamped with specific contract-month instrument labels. The
-- coverage maintainer will re-populate from the correct per-contract
-- symbols on next startup.
DELETE FROM bars;
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_migration_009.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/009_purge_mistagged_bars.sql tests/test_migration_009.py
git commit -m "feat(db): migration 009 — purge mis-tagged continuous bars"
```

---

### Task 9: Migration 010 — populate `contract_template` in `instruments.json`

This migration is Python, not SQL, because `instruments.json` lives on disk, not in SQLite. It runs **after** SQL migrations on app startup. Pattern: a loader function called from `create_app()` after `run_migrations`.

**Files:**
- Create: `migrations/010_contract_templates.py`
- Test: `tests/test_migration_010.py`
- Modify: `app.py` (wire the python migration into startup — covered in Task 19)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_010.py
import json
from pathlib import Path

from migrations_python import apply_json_migrations


def _seed(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "MNQ": {
                    "display_name": "Micro E-mini Nasdaq-100",
                    "multiplier": 2.0,
                    "tick_size": 0.25,
                    "sources": {
                        "yfinance": {"continuous": "MNQ=F", "contract_template": None},
                        "stooq": {"continuous": "mnq.f", "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )


def test_010_fills_yfinance_template(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "{ROOT}{M}{YY}.CME"
    # Stooq untouched.
    assert data["MNQ"]["sources"]["stooq"]["contract_template"] is None


def test_010_is_idempotent(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    apply_json_migrations(p)
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "{ROOT}{M}{YY}.CME"


def test_010_does_not_overwrite_existing_template(tmp_path):
    p = tmp_path / "instruments.json"
    _seed(p)
    data = json.loads(p.read_text())
    data["MNQ"]["sources"]["yfinance"]["contract_template"] = "custom.{ROOT}.{M}{YY}"
    p.write_text(json.dumps(data))
    apply_json_migrations(p)
    data = json.loads(p.read_text())
    assert data["MNQ"]["sources"]["yfinance"]["contract_template"] == "custom.{ROOT}.{M}{YY}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_010.py -v`
Expected: FAIL — `migrations_python` module missing.

- [ ] **Step 3: Create the python-migration module**

```python
# migrations_python.py
"""JSON-side migrations applied on app startup after SQL migrations.

Each function in `_STEPS` is idempotent. Run in list order. A migration
should check current state before writing anything — callers re-run this
on every startup.
"""

import json
from pathlib import Path

_YFINANCE_TEMPLATE = "{ROOT}{M}{YY}.CME"


def _fill_yfinance_contract_templates(data: dict) -> bool:
    """Return True if anything changed."""
    changed = False
    for root, cfg in data.items():
        sources = cfg.get("sources", {})
        yf = sources.get("yfinance")
        if yf is None:
            continue
        if yf.get("contract_template") is None:
            yf["contract_template"] = _YFINANCE_TEMPLATE
            changed = True
    return changed


_STEPS = [
    ("fill_yfinance_contract_templates", _fill_yfinance_contract_templates),
]


def apply_json_migrations(instruments_json_path: Path | str) -> list[str]:
    """Apply all JSON migration steps. Returns names of steps that changed anything."""
    path = Path(instruments_json_path)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else {}
    applied: list[str] = []
    for name, fn in _STEPS:
        if fn(data):
            applied.append(name)
    if applied:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return applied
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_migration_010.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations_python.py tests/test_migration_010.py
git commit -m "feat(db): migration 010 — populate yfinance contract templates"
```

---

## Phase D — Coverage state machine

### Task 10: `coverage_state.refresh_instrument_coverage_state`

The state function reads executions + the current `instrument_coverage` table, computes the new state per contract, and UPSERTs. Inputs: a connection, a clock. Output: a list of state rows for diagnostics. Also surfaces instruments that no longer exist in executions but remain in `instrument_coverage` (they stay in whatever state they are, including pinned/retired).

**Files:**
- Create: `services/ohlc/coverage_state.py`
- Test: `tests/test_coverage_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage_state.py
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.coverage_state import (
    CoverageRow,
    list_coverage,
    refresh_instrument_coverage_state,
    set_pinned,
    retire_now,
    reactivate,
)


def _setup(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    return conn


def _insert_execution(conn, *, nt_id, account, instrument, ts):
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, side, qty,"
        " price, commission, timestamp, import_batch_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (nt_id, account, instrument, "Buy", 1, 100.0, 0.0, ts, "batch1"),
    )


def test_new_execution_creates_active_row(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="MNQ JUN26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    rows = list_coverage(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r.instrument == "MNQ JUN26"
    assert r.state == "active"
    assert r.last_execution_at == now - 3600


def test_old_execution_becomes_winding_down(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn, nt_id="e1", account="sim", instrument="MNQ MAR26",
        ts=now - 40 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    rows = list_coverage(conn)
    assert rows[0].state == "winding_down"


def test_pinned_overrides_inactivity(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn, nt_id="e1", account="sim", instrument="MNQ MAR26",
        ts=now - 100 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    set_pinned(conn, instrument="MNQ MAR26", pinned=True, now=now)
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "active"


def test_retire_now_jumps_to_retired(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="CL JUL26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    rows = list_coverage(conn)
    assert rows[0].state == "retired"
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "retired"  # sticks


def test_reactivate_brings_back_to_active(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(conn, nt_id="e1", account="sim", instrument="CL JUL26", ts=now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    reactivate(conn, instrument="CL JUL26", now=now)
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "active"


def test_180_day_safety_backstop(tmp_path):
    conn = _setup(tmp_path)
    now = 1_000_000_000
    _insert_execution(
        conn, nt_id="e1", account="sim", instrument="MNQ SEP25",
        ts=now - 200 * 86400,
    )
    refresh_instrument_coverage_state(conn, now=now)
    assert list_coverage(conn)[0].state == "retired"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coverage_state.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the module**

```python
# services/ohlc/coverage_state.py
"""Per-contract coverage state machine.

Tracks (active | winding_down | retired) per instrument, derived from
executions plus user overrides (pinned, retired_at). Called once per
coverage-maintainer tick and on any user action.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

State = Literal["active", "winding_down", "retired"]

ACTIVE_DAYS = 30
SAFETY_BACKSTOP_DAYS = 180


@dataclass(frozen=True)
class CoverageRow:
    instrument: str
    state: State
    last_execution_at: int | None
    pinned: bool
    retired_at: int | None
    updated_at: int


def list_coverage(conn: sqlite3.Connection) -> list[CoverageRow]:
    rows = conn.execute(
        "SELECT instrument, state, last_execution_at, pinned, retired_at, updated_at"
        " FROM instrument_coverage ORDER BY instrument"
    ).fetchall()
    return [
        CoverageRow(
            instrument=r["instrument"],
            state=r["state"],
            last_execution_at=r["last_execution_at"],
            pinned=bool(r["pinned"]),
            retired_at=r["retired_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def set_pinned(
    conn: sqlite3.Connection, *, instrument: str, pinned: bool, now: int
) -> None:
    conn.execute(
        "INSERT INTO instrument_coverage"
        " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
        " VALUES (?, 'active', NULL, ?, NULL, ?)"
        " ON CONFLICT(instrument) DO UPDATE SET"
        "  pinned = excluded.pinned,"
        "  updated_at = excluded.updated_at",
        (instrument, 1 if pinned else 0, now),
    )


def retire_now(conn: sqlite3.Connection, *, instrument: str, now: int) -> None:
    conn.execute(
        "INSERT INTO instrument_coverage"
        " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
        " VALUES (?, 'retired', NULL, 0, ?, ?)"
        " ON CONFLICT(instrument) DO UPDATE SET"
        "  state = 'retired',"
        "  pinned = 0,"
        "  retired_at = excluded.retired_at,"
        "  updated_at = excluded.updated_at",
        (instrument, now, now),
    )


def reactivate(conn: sqlite3.Connection, *, instrument: str, now: int) -> None:
    conn.execute(
        "UPDATE instrument_coverage"
        " SET state = 'active', retired_at = NULL, updated_at = ?"
        " WHERE instrument = ?",
        (now, instrument),
    )


def refresh_instrument_coverage_state(conn: sqlite3.Connection, *, now: int) -> None:
    """Recompute state for every instrument seen in executions and upsert.

    Respects pinned and retired_at overrides. Never transitions an
    explicitly-retired contract back to active — only reactivate() does.
    """
    rows = conn.execute(
        "SELECT instrument, MAX(timestamp) AS last_ts"
        " FROM executions GROUP BY instrument"
    ).fetchall()
    existing = {r.instrument: r for r in list_coverage(conn)}

    for row in rows:
        instrument = row["instrument"]
        last_ts = int(row["last_ts"])
        prev = existing.get(instrument)
        pinned = prev.pinned if prev is not None else False
        # Manual retirement sticks.
        if prev is not None and prev.retired_at is not None and prev.state == "retired":
            continue
        state = _compute_state(
            last_ts=last_ts, pinned=pinned, now=now
        )
        conn.execute(
            "INSERT INTO instrument_coverage"
            " (instrument, state, last_execution_at, pinned, retired_at, updated_at)"
            " VALUES (?, ?, ?, ?, NULL, ?)"
            " ON CONFLICT(instrument) DO UPDATE SET"
            "  state = excluded.state,"
            "  last_execution_at = excluded.last_execution_at,"
            "  updated_at = excluded.updated_at",
            (instrument, state, last_ts, 1 if pinned else 0, now),
        )


def _compute_state(*, last_ts: int, pinned: bool, now: int) -> State:
    if pinned:
        return "active"
    age = now - last_ts
    if age <= ACTIVE_DAYS * 86400:
        return "active"
    if age >= SAFETY_BACKSTOP_DAYS * 86400:
        return "retired"
    return "winding_down"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_coverage_state.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/coverage_state.py tests/test_coverage_state.py
git commit -m "feat(ohlc): coverage state machine with pin/retire/reactivate"
```

---

## Phase E — Fetcher + token-bucket integration

### Task 11: Fetcher acquires token before `source.fetch()`

**Files:**
- Modify: `services/ohlc/fetcher.py`
- Modify: `tests/test_ohlc_fetcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ohlc_fetcher.py`:

```python
def test_fetcher_acquires_token_before_source_call(tmp_path):
    import time

    from db import connect
    from migrations import run_migrations
    from models.bar import Bar
    from services.ohlc.circuit_breaker import CircuitBreaker
    from services.ohlc.fetcher import fetch_range
    from services.ohlc.rate_limiter import TokenBucket
    from services.ohlc.registry import SourceRegistry

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    conn.close()

    class RecordingSource:
        name = "rec"
        supported_timeframes = frozenset({"1m"})

        def __init__(self):
            self.calls = 0

        def fetch(self, instrument, timeframe, start, end):
            self.calls += 1
            return [
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=start,
                    open=1,
                    high=2,
                    low=0,
                    close=1,
                    volume=1,
                    source="rec",
                )
            ]

    clock = [int(time.time())]
    reg = SourceRegistry(clock=lambda: clock[0])
    src = RecordingSource()
    reg.entries.append(
        (
            src,
            CircuitBreaker(
                name="rec",
                failure_threshold=3,
                base_cooldown_seconds=1,
                clock=lambda: clock[0],
            ),
        )
    )
    bucket = TokenBucket(capacity=2, refill_per_sec=0.0, clock=time.monotonic)
    start_ts = clock[0] - 120
    end_ts = start_ts + 60
    res = fetch_range(
        db_path=db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=start_ts,
        end=end_ts,
        token_bucket=bucket,
    )
    assert src.calls == 1
    assert bucket.stats()["acquired_total"] == 1
    assert res.bars_added == 1
```

(Plan expects `Path` imported at top of the test module already.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ohlc_fetcher.py -k "acquires_token" -v`
Expected: FAIL — `fetch_range()` has no `token_bucket` keyword.

- [ ] **Step 3: Modify `services/ohlc/fetcher.py`**

Change the signature to accept an optional `token_bucket` and acquire before the source call. Keep `token_bucket=None` as a backward-compat default so existing tests pass.

```python
# at top of file
from services.ohlc.rate_limiter import TokenBucket
```

Update `fetch_range` signature:

```python
def fetch_range(
    *,
    db_path: Path | str,
    registry: SourceRegistry,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
    token_bucket: TokenBucket | None = None,
) -> FetchResult:
```

Replace the inner source-call site:

```python
            try:
                if token_bucket is not None:
                    with token_bucket.acquire(timeout=60):
                        bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                else:
                    bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                breaker.record_success()
```

On `TimeoutError` from the bucket, classify as a skipped attempt:

```python
            except TimeoutError as te:
                attempts.append(
                    AttemptRecord(
                        source=source.name,
                        outcome="skipped",
                        count=0,
                        error=repr(te),
                    )
                )
                continue
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ohlc_fetcher.py -v`
Expected: PASS (new test + existing tests).

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/fetcher.py tests/test_ohlc_fetcher.py
git commit -m "feat(ohlc): gate fetch_range on global token bucket"
```

---

### Task 12: Gap detection — classify `out_of_reach`

The existing `find_gaps` returns `list[tuple[int,int]]`. We add a parallel function `classify_window` that returns a richer summary used by the data-health route: counts of `present`, `missing`, `out_of_reach`.

**Files:**
- Modify: `services/ohlc/gap_detection.py`
- Modify: `tests/test_gap_detection.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gap_detection.py`:

```python
def test_classify_window_marks_slots_beyond_reach_as_out_of_reach(tmp_path):
    from db import connect
    from migrations import run_migrations
    from services.ohlc.gap_detection import classify_window

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    # 30-day 1m window: 7-day reach, so ~23 days are out of reach.
    summary = classify_window(
        conn,
        instrument="MNQ JUN26",
        timeframe="1m",
        start=now - 30 * 86400,
        end=now,
        now=now,
    )
    assert summary["expected"] > 0
    assert summary["present"] == 0
    assert summary["out_of_reach"] > 0
    assert summary["missing"] > 0
    # Reach window should correspond to roughly 7 days of 1m slots (after
    # session-break removal).
    reachable = summary["expected"] - summary["out_of_reach"]
    assert 4000 < reachable < 12000
```

(You'll need `from pathlib import Path` at the top of the test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gap_detection.py -k "out_of_reach" -v`
Expected: FAIL — `classify_window` not defined.

- [ ] **Step 3: Add `classify_window` to `services/ohlc/gap_detection.py`**

```python
from services.ohlc.reach import PROVIDER_REACH


def classify_window(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
    now: int,
) -> dict:
    """Summarize a window as {expected, present, missing, out_of_reach}.

    A slot is `out_of_reach` if the provider cannot serve it even on a
    fresh fetch (yfinance 1m → only last 7 days). Everything beyond the
    reach threshold is classified as out_of_reach, not missing.
    """
    if start >= end:
        return {"expected": 0, "present": 0, "missing": 0, "out_of_reach": 0}
    slots = _expected_slots(instrument, timeframe, start, end)
    reach = PROVIDER_REACH.get(timeframe, PROVIDER_REACH["1d"])
    reach_cutoff = now - reach
    reachable = [s for s in slots if s >= reach_cutoff]
    out_of_reach = len(slots) - len(reachable)
    present = set(list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end))
    present_count = sum(1 for s in reachable if s in present)
    missing = len(reachable) - present_count
    return {
        "expected": len(slots),
        "present": present_count,
        "missing": missing,
        "out_of_reach": out_of_reach,
    }
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_gap_detection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/gap_detection.py tests/test_gap_detection.py
git commit -m "feat(ohlc): classify_window distinguishes out_of_reach from missing"
```

---

## Phase F — Coverage maintainer

### Task 13: Maintainer + historical sweep

**Files:**
- Create: `services/ohlc/coverage_maintainer.py`
- Test: `tests/test_coverage_maintainer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage_maintainer.py
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.ohlc.coverage_maintainer import (
    MAINTAINER_WINDOWS,
    SWEEP_WINDOWS,
    coverage_maintainer_tick,
    historical_sweep_tick,
)
from services.ohlc.coverage_state import (
    refresh_instrument_coverage_state,
    retire_now,
)


def _insert_exec(conn, instrument, ts):
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, side, qty,"
        " price, commission, timestamp, import_batch_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (f"e-{instrument}-{ts}", "sim", instrument, "Buy", 1, 100.0, 0.0, ts, "b"),
    )


def test_maintainer_submits_active_contracts_only(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "MNQ JUN26", now - 3600)
    _insert_exec(conn, "CL JUL26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    retire_now(conn, instrument="CL JUL26", now=now)
    conn.close()

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end):
        seen.append((instrument, timeframe, start, end))

    coverage_maintainer_tick(
        db_path=db, fetch_fn=fake_fetch, now=now,
    )
    instruments_called = {x[0] for x in seen}
    assert instruments_called == {"MNQ JUN26"}
    timeframes_called = {x[1] for x in seen}
    assert timeframes_called == set(MAINTAINER_WINDOWS.keys())


def test_sweep_uses_wider_windows(tmp_path):
    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "MNQ JUN26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    conn.close()

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end):
        seen.append((timeframe, end - start))

    historical_sweep_tick(db_path=db, fetch_fn=fake_fetch, now=now)
    for tf, width in seen:
        assert width >= MAINTAINER_WINDOWS[tf], (tf, width)
    # And it must be at least the configured sweep window.
    windows_seen = {tf: w for tf, w in seen}
    for tf, w in SWEEP_WINDOWS.items():
        assert windows_seen[tf] == w


def test_maintainer_skips_instruments_with_no_contract_template(tmp_path, monkeypatch):
    """A suffixed instrument whose registry has no contract_template
    ends up with source_symbol returning None; the maintainer should
    not submit fetches for it."""
    from services.instruments import set_registry_path
    import json

    db = tmp_path / "ftl.db"
    conn = connect(db)
    run_migrations(conn, Path("migrations"))
    now = 1_000_000_000
    _insert_exec(conn, "XYZ JUN26", now - 3600)
    refresh_instrument_coverage_state(conn, now=now)
    conn.close()

    path = tmp_path / "instruments.json"
    path.write_text(
        json.dumps(
            {
                "XYZ": {
                    "display_name": "Unknown",
                    "multiplier": 1.0,
                    "tick_size": 0.01,
                    "sources": {
                        "yfinance": {"continuous": None, "contract_template": None},
                        "stooq": {"continuous": None, "contract_template": None},
                    },
                    "session": {
                        "timezone": "America/Chicago",
                        "open": "17:00",
                        "close": "16:00",
                        "daily_break_start": "16:00",
                        "daily_break_end": "17:00",
                    },
                }
            }
        )
    )
    set_registry_path(path)

    seen = []

    def fake_fetch(*, db_path, instrument, timeframe, start, end):
        seen.append(instrument)

    coverage_maintainer_tick(db_path=db, fetch_fn=fake_fetch, now=now)
    assert seen == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coverage_maintainer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the module**

```python
# services/ohlc/coverage_maintainer.py
"""Coverage maintainer — replaces the post-import OHLC hook and
recent/week refresh jobs with a single scheduler-driven sweep.

Two entry points:
- coverage_maintainer_tick: runs every 30 min, active contracts, narrow
  windows targeted at keeping current data current.
- historical_sweep_tick: runs every 4h, active + winding_down contracts,
  wider windows targeted at backfilling reachable history.

Both accept an injected `fetch_fn` so tests can verify the call shape
without any network or DB side effects beyond the coverage table read.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from db import connect
from logging_config import get_logger
from services.instruments import source_symbol
from services.ohlc.coverage_state import (
    list_coverage,
    refresh_instrument_coverage_state,
)

log = get_logger("ohlc.coverage_maintainer")


# Window widths in seconds per timeframe.
MAINTAINER_WINDOWS: dict[str, int] = {
    "1m": 2 * 86400,
    "5m": 2 * 86400,
    "15m": 2 * 86400,
    "1h": 7 * 86400,
}

SWEEP_WINDOWS: dict[str, int] = {
    "1m": 7 * 86400,
    "5m": 60 * 86400,
    "15m": 60 * 86400,
    "1h": 730 * 86400,
    "1d": 10 * 365 * 86400,
}


class FetchFn(Protocol):
    def __call__(
        self,
        *,
        db_path: Path | str,
        instrument: str,
        timeframe: str,
        start: int,
        end: int,
    ) -> None: ...


def coverage_maintainer_tick(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
) -> None:
    _run(db_path=db_path, fetch_fn=fetch_fn, now=now, windows=MAINTAINER_WINDOWS, states=("active",))


def historical_sweep_tick(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
) -> None:
    _run(
        db_path=db_path,
        fetch_fn=fetch_fn,
        now=now,
        windows=SWEEP_WINDOWS,
        states=("active", "winding_down"),
    )


def _run(
    *,
    db_path: Path | str,
    fetch_fn: FetchFn,
    now: int,
    windows: dict[str, int],
    states: tuple[str, ...],
) -> None:
    conn = connect(db_path)
    try:
        refresh_instrument_coverage_state(conn, now=now)
        rows = [r for r in list_coverage(conn) if r.state in states]
    finally:
        conn.close()

    for row in rows:
        if source_symbol(row.instrument, "yfinance") is None and source_symbol(
            row.instrument, "stooq"
        ) is None:
            log.info("skip unknown instrument", extra={"instrument": row.instrument})
            continue
        for tf, width in windows.items():
            end = now
            start = end - width
            try:
                fetch_fn(
                    db_path=db_path,
                    instrument=row.instrument,
                    timeframe=tf,
                    start=start,
                    end=end,
                )
            except Exception:
                log.exception(
                    "coverage maintainer fetch failed",
                    extra={"instrument": row.instrument, "tf": tf},
                )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_coverage_maintainer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/coverage_maintainer.py tests/test_coverage_maintainer.py
git commit -m "feat(ohlc): coverage maintainer + historical sweep tick"
```

---

## Phase G — Circuit breaker retune + job wiring

### Task 14: Retune yfinance breaker numbers

**Files:**
- Modify: `services/ohlc/registry.py`
- Modify: `tests/test_ohlc_registry.py`

- [ ] **Step 1: Update tests**

Replace existing breaker-numbers expectations in `tests/test_ohlc_registry.py` (or add a new test) with:

```python
def test_yfinance_breaker_tuned_for_rate_limit_conservatism():
    from services.ohlc.registry import build_default_registry
    reg = build_default_registry(clock=lambda: 0)
    yf_breaker = next(b for s, b in reg.entries if s.name == "yfinance")
    assert yf_breaker.base_cooldown_rate_limit_seconds == 3600
    assert yf_breaker.max_cooldown_seconds == 12 * 3600
    assert yf_breaker.backoff_multiplier == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ohlc_registry.py -v`
Expected: FAIL — current numbers are 900 / 14400 / 2.0.

- [ ] **Step 3: Update `build_default_registry`**

```python
    reg.register(
        YfinanceSource(),
        failure_threshold=3,
        base_cooldown_seconds=300,
        base_cooldown_rate_limit_seconds=3600,  # 1 h first 429
        max_cooldown_seconds=12 * 3600,         # 12 h ceiling
        backoff_multiplier=4.0,                 # 1h → 4h → 12h
        jitter_fraction=0.15,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ohlc_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/registry.py tests/test_ohlc_registry.py
git commit -m "feat(ohlc): retune yfinance breaker for conservative rate-limit backoff"
```

---

### Task 15: Wire coverage maintainer jobs in `app.py`

This is the largest-blast-radius change. It drops three existing things and adds six new scheduler jobs.

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app_factory.py` or `tests/test_app_factory_plan14.py` — add a test for the new job registrations

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_factory_plan19.py
from app import create_app
from config import Config


def test_plan19_registers_new_jobs_and_drops_old_ones(tmp_path):
    cfg = Config(data_dir=str(tmp_path))
    app, services = create_app(config=cfg, start_background=False)
    try:
        job_ids = {j.id for j in services.scheduler.get_jobs()}
    finally:
        services.stop()
    assert "ohlc_coverage_maintainer" in job_ids
    assert "ohlc_historical_sweep" in job_ids
    assert "ohlc_daily_refresh" in job_ids
    assert "ohlc_weekly_refresh" in job_ids
    assert "ohlc_monthly_refresh" in job_ids
    # Old jobs gone:
    assert "ohlc_refresh_recent" not in job_ids
    assert "ohlc_refresh_week" not in job_ids


def test_plan19_drops_post_import_ohlc_hook(tmp_path):
    cfg = Config(data_dir=str(tmp_path))
    app, services = create_app(config=cfg, start_background=False)
    try:
        pipeline = app.config["FTL_IMPORT_PIPELINE"]
        hook_names = [fn.__name__ for fn in pipeline.post_tick_hooks]
    finally:
        services.stop()
    assert "_ohlc_hook" not in hook_names
    assert "_integrity_hook" in hook_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_factory_plan19.py -v`
Expected: FAIL — old jobs still registered, hook still present.

- [ ] **Step 3: Modify `app.py`**

Remove:
- the `_ohlc_hook` function definition (lines ~78–116)
- `pipeline.post_tick_hooks.append(_ohlc_hook)` (line ~118)
- the `_refresh` helper and both `ohlc_refresh_recent` / `ohlc_refresh_week` registrations (lines ~158–201)

Add `ohlc_jobs` stays and `ohlc_registry` stays. Additions go where the old refresh registrations were. At the top of the file, add:

```python
from services.ohlc.coverage_maintainer import (
    coverage_maintainer_tick,
    historical_sweep_tick,
)
from services.ohlc.rate_limiter import TokenBucket
from migrations_python import apply_json_migrations
```

Inside `create_app`, right after `ohlc_registry` is built, add:

```python
    token_bucket = TokenBucket(capacity=30, refill_per_sec=0.5, clock=_time.monotonic)
    app.config["FTL_OHLC_TOKEN_BUCKET"] = token_bucket  # deferred — set after app created

    def _fetch(*, db_path, instrument, timeframe, start, end):
        from services.ohlc.fetcher import fetch_range
        fetch_range(
            db_path=db_path,
            registry=ohlc_registry,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
            token_bucket=token_bucket,
        )
```

(Move the `app.config` assignment for the token bucket to after the Flask app is created.)

Apply JSON migrations after SQL migrations:

```python
    run_migrations(conn, Path("migrations"))
    conn.close()
    instruments_json = Path(config.data_dir) / "config" / "instruments.json"
    apply_json_migrations(instruments_json)
```

Replace the two removed refresh-job registrations with:

```python
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    import calendar

    services.scheduler.add_job(
        lambda: coverage_maintainer_tick(
            db_path=config.db_path, fetch_fn=_fetch, now=int(_time.time())
        ),
        trigger=IntervalTrigger(minutes=30),
        id="ohlc_coverage_maintainer",
        replace_existing=True,
    )
    services.scheduler.add_job(
        lambda: historical_sweep_tick(
            db_path=config.db_path, fetch_fn=_fetch, now=int(_time.time())
        ),
        trigger=IntervalTrigger(hours=4),
        id="ohlc_historical_sweep",
        replace_existing=True,
    )

    def _fetch_daily():
        # 1d for active contracts only
        _fetch_tf_for_active("1d", window_seconds=10 * 365 * 86400)

    def _fetch_weekly():
        _fetch_tf_for_active("1wk", window_seconds=10 * 365 * 86400)

    def _fetch_monthly():
        _fetch_tf_for_active("1mo", window_seconds=40 * 365 * 86400)
        _schedule_next_monthly()

    def _fetch_tf_for_active(tf: str, *, window_seconds: int) -> None:
        from services.ohlc.coverage_state import (
            list_coverage,
            refresh_instrument_coverage_state,
        )
        conn = connect(config.db_path)
        try:
            now = int(_time.time())
            refresh_instrument_coverage_state(conn, now=now)
            rows = [r for r in list_coverage(conn) if r.state == "active"]
        finally:
            conn.close()
        end = int(_time.time())
        start = end - window_seconds
        for row in rows:
            try:
                _fetch(
                    db_path=config.db_path,
                    instrument=row.instrument,
                    timeframe=tf,
                    start=start,
                    end=end,
                )
            except Exception:
                log.exception(
                    "scheduled refresh failed",
                    extra={"instrument": row.instrument, "tf": tf},
                )

    services.scheduler.add_job(
        _fetch_daily,
        trigger=CronTrigger(hour=16, minute=1, timezone="America/Chicago"),
        id="ohlc_daily_refresh",
        replace_existing=True,
    )
    services.scheduler.add_job(
        _fetch_weekly,
        trigger=CronTrigger(day_of_week="fri", hour=16, minute=1, timezone="America/Chicago"),
        id="ohlc_weekly_refresh",
        replace_existing=True,
    )

    def _schedule_next_monthly():
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Chicago")
        now_local = datetime.now(tz)
        last_day = calendar.monthrange(now_local.year, now_local.month)[1]
        run_date = now_local.replace(
            day=last_day, hour=16, minute=1, second=0, microsecond=0
        )
        if run_date <= now_local:
            # Roll to next month
            m = now_local.month + 1
            y = now_local.year + (1 if m > 12 else 0)
            m = ((m - 1) % 12) + 1
            last_day = calendar.monthrange(y, m)[1]
            run_date = run_date.replace(year=y, month=m, day=last_day)
        services.scheduler.add_job(
            _fetch_monthly,
            trigger="date",
            run_date=run_date,
            id="ohlc_monthly_refresh",
            replace_existing=True,
        )

    _schedule_next_monthly()
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/test_app_factory_plan19.py tests/test_app_factory_plan14.py -v`
Expected: PASS. Old refresh-job tests in `test_app_factory_plan14.py` may need adjustment — if they assert the old job IDs exist, update them to assert the new ones.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app_factory_plan19.py tests/test_app_factory_plan14.py
git commit -m "feat(app): wire coverage maintainer, drop post-import OHLC hook"
```

---

## Phase H — Data-health & settings UI

### Task 16: Data-health API — `out_of_reach`, `pending`, maintainer panel

**Files:**
- Modify: `routes/monitoring.py`
- Modify: `tests/test_routes_monitoring.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_routes_monitoring.py`:

```python
def test_data_health_completeness_emits_out_of_reach(tmp_path, client_factory):
    # client_factory is assumed to exist; follow the existing pattern in
    # test_routes_monitoring.py. If not, adapt using create_app directly.
    client = client_factory(tmp_path)
    # Create an execution so the instrument appears in the matrix.
    _seed_execution(client, instrument="MNQ JUN26", ts_seconds_ago=3600)
    resp = client.get("/api/data-health/completeness?days=30")
    body = resp.get_json()
    row = body["cells"]["MNQ JUN26"]
    # 1m: at 30d window with 7d reach, status must be out_of_reach (no data).
    assert row["1m"] in ("out_of_reach", "partial")


def test_data_health_has_maintainer_status_endpoint(client_factory, tmp_path):
    client = client_factory(tmp_path)
    resp = client.get("/api/data-health/maintainer")
    body = resp.get_json()
    assert set(body.keys()) >= {
        "next_run_at",
        "last_run_at",
        "last_run_status",
        "token_bucket",
    }
    assert set(body["token_bucket"].keys()) >= {"capacity", "available"}


def test_canonical_timeframes_drop_4h_add_weekly_monthly():
    from routes.monitoring import CANONICAL_TIMEFRAMES
    assert "4h" not in CANONICAL_TIMEFRAMES
    assert "1wk" in CANONICAL_TIMEFRAMES
    assert "1mo" in CANONICAL_TIMEFRAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_routes_monitoring.py -v`
Expected: FAIL — `/api/data-health/maintainer` doesn't exist; `CANONICAL_TIMEFRAMES` still lists 4h.

- [ ] **Step 3: Modify `routes/monitoring.py`**

Replace the constant:

```python
CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"]
```

Update `_cell_status` to use `classify_window` and return `out_of_reach` when appropriate:

```python
from services.ohlc.gap_detection import classify_window


def _cell_status(conn, *, instrument: str, timeframe: str, start: int, end: int, now: int) -> str:
    summary = classify_window(
        conn,
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end,
        now=now,
    )
    if summary["expected"] == 0:
        return "session_closed"
    if summary["missing"] == 0 and summary["present"] > 0:
        return "complete"
    if summary["out_of_reach"] == summary["expected"]:
        return "out_of_reach"
    if summary["present"] == 0 and summary["out_of_reach"] < summary["expected"]:
        return "missing"
    return "partial"
```

Update the completeness route to pass `now`. Add the maintainer endpoint:

```python
@bp.get("/api/data-health/maintainer")
def data_health_maintainer():
    services = _services()
    scheduler = services.scheduler
    job = scheduler.get_job("ohlc_coverage_maintainer")
    history = services._job_history.get("ohlc_coverage_maintainer", [])
    last = history[0] if history else None
    token_bucket = current_app.config.get("FTL_OHLC_TOKEN_BUCKET")
    tb_stats = token_bucket.stats() if token_bucket is not None else {}
    return jsonify(
        {
            "next_run_at": job.next_run_time.timestamp() if job and job.next_run_time else None,
            "last_run_at": last["started_at"] if last else None,
            "last_run_status": last["status"] if last else None,
            "token_bucket": tb_stats,
        }
    )
```

The existing tests may need a `client_factory` fixture. If it doesn't already exist, add it in `tests/conftest.py`:

```python
# tests/conftest.py  (append)
import pytest
from app import create_app
from config import Config


@pytest.fixture
def client_factory():
    def _make(tmp_path):
        cfg = Config(data_dir=str(tmp_path))
        app, services = create_app(config=cfg, start_background=False)
        client = app.test_client()
        client._ftl_services = services  # keep a ref so it doesn't GC
        return client
    return _make


def _seed_execution(client, *, instrument: str, ts_seconds_ago: int) -> None:
    import time as _time
    from db import connect
    db_path = client.application.config["FTL_DB_PATH"]
    conn = connect(db_path)
    now = int(_time.time())
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, side, qty,"
        " price, commission, timestamp, import_batch_id) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (f"e-{instrument}-{now}", "sim", instrument, "Buy", 1, 100.0, 0.0, now - ts_seconds_ago, "b"),
    )
    conn.close()
```

(If the project already has a client_factory fixture, use that instead — check `tests/conftest.py` first.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_routes_monitoring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/monitoring.py tests/test_routes_monitoring.py tests/conftest.py
git commit -m "feat(monitoring): out_of_reach cells + maintainer status endpoint"
```

---

### Task 17: Data-health JS — new cell states + panel + notices

**Files:**
- Modify: `static/js/data_health.js`
- Modify: `templates/data_health.html`

- [ ] **Step 1: Update `templates/data_health.html`**

```html
{% extends "base.html" %}
{% block title %}Data Health — FTL{% endblock %}
{% block content %}
<h1>Data Health</h1>
<div class="notice">
  4h candles are derived from 1h bars at read time — no separate 4h data is stored or fetched.
</div>
<div id="sources-band"></div>
<div id="maintainer-panel"></div>
<div id="completeness-matrix"></div>
<div id="detail-panel" style="display:none"></div>
{% endblock %}
{% block scripts %}
<script type="module" src="{{ url_for('static', filename='js/data_health.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Update `static/js/data_health.js`**

Extend `statusStyle` with two new states:

```js
const statusStyle = {
  complete: "background:#d4edda;color:#155724",
  partial: "background:#fff3cd;color:#856404",
  missing: "background:#f8d7da;color:#721c24",
  out_of_reach: "background:#e2e3e5;color:#6c757d",
  pending: "background:#cce5ff;color:#004085",
  session_closed: "background:#e2e3e5;color:#383d41",
};
```

Add a maintainer-panel renderer called from `initDataHealth`:

```js
initDataHealth();

async function initDataHealth() {
  await renderSourcesBand();
  await renderMaintainerPanel();
  await renderMatrix();
}

async function renderMaintainerPanel() {
  const el = document.getElementById("maintainer-panel");
  const resp = await fetch("/api/data-health/maintainer");
  const body = await resp.json();
  const next = body.next_run_at ? new Date(body.next_run_at * 1000).toLocaleString() : "—";
  const last = body.last_run_at ? new Date(body.last_run_at * 1000).toLocaleString() : "—";
  const lastStatus = body.last_run_status ?? "—";
  const tb = body.token_bucket || {};
  el.innerHTML = `
    <h3 style="margin-top:1em">Coverage Maintainer</h3>
    <table>
      <tr><th>Next run</th><td>${next}</td></tr>
      <tr><th>Last run</th><td>${last} (${escHtml(lastStatus)})</td></tr>
      <tr><th>Tokens available</th><td>${tb.available ?? "—"} / ${tb.capacity ?? "—"}</td></tr>
      <tr><th>Acquired (lifetime)</th><td>${tb.acquired_total ?? 0}</td></tr>
      <tr><th>Timeouts (lifetime)</th><td>${tb.timeouts_total ?? 0}</td></tr>
    </table>`;
}
```

Add the stooq inline note inside `renderSourcesBand`, next to the stooq row:

```js
    const noteSuffix = s.name === "stooq"
      ? ' <span style="color:#6c757d">(daily bars only — used as fallback for 1d when yfinance is unavailable)</span>'
      : '';
    return `<tr>
      <td>${escHtml(s.name)}${noteSuffix}</td>
      ...
```

- [ ] **Step 3: Manual verification**

Run the app in Docker, load `/data-health` in Chrome, confirm:
- Top notice about 4h synthetic.
- Maintainer panel shows next run time and token stats.
- Stooq row has the "daily bars only" note.
- Matrix has no 4h column; has 1wk and 1mo columns.
- Cell clicks still open the detail panel.

- [ ] **Step 4: Commit**

```bash
git add static/js/data_health.js templates/data_health.html
git commit -m "feat(ui): data-health UI — new cell states, maintainer panel, notices"
```

---

### Task 18: Settings page — pin / retire / reactivate endpoints + UI

**Files:**
- Modify: `routes/settings.py`
- Modify: `tests/test_settings_routes_instruments.py`
- Modify: `templates/instruments.html`
- Modify: `static/js/instruments.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_routes_instruments.py`:

```python
def test_pin_contract(client_factory, tmp_path):
    client = client_factory(tmp_path)
    _seed_execution(client, instrument="MNQ JUN26", ts_seconds_ago=3600)
    resp = client.post(
        "/api/settings/coverage/MNQ JUN26/pin", json={"pinned": True}
    )
    assert resp.status_code == 200
    assert resp.get_json()["pinned"] is True


def test_retire_and_reactivate(client_factory, tmp_path):
    client = client_factory(tmp_path)
    _seed_execution(client, instrument="CL AUG26", ts_seconds_ago=3600)
    r1 = client.post("/api/settings/coverage/CL AUG26/retire")
    assert r1.status_code == 200
    assert r1.get_json()["state"] == "retired"
    r2 = client.post("/api/settings/coverage/CL AUG26/reactivate")
    assert r2.status_code == 200
    assert r2.get_json()["state"] == "active"


def test_list_coverage_rows(client_factory, tmp_path):
    client = client_factory(tmp_path)
    _seed_execution(client, instrument="MNQ JUN26", ts_seconds_ago=3600)
    # Trigger a coverage refresh via the coverage-list endpoint.
    resp = client.get("/api/settings/coverage")
    body = resp.get_json()
    names = {r["instrument"] for r in body["rows"]}
    assert "MNQ JUN26" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings_routes_instruments.py -v`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 3: Add the endpoints in `routes/settings.py`**

```python
from services.ohlc.coverage_state import (
    list_coverage,
    refresh_instrument_coverage_state,
    retire_now,
    reactivate,
    set_pinned,
)


@bp.get("/api/settings/coverage")
def coverage_list():
    conn = connect(_db_path())
    try:
        import time as _time
        refresh_instrument_coverage_state(conn, now=int(_time.time()))
        rows = list_coverage(conn)
    finally:
        conn.close()
    return jsonify(
        {
            "rows": [
                {
                    "instrument": r.instrument,
                    "state": r.state,
                    "last_execution_at": r.last_execution_at,
                    "pinned": r.pinned,
                    "retired_at": r.retired_at,
                }
                for r in rows
            ]
        }
    )


@bp.post("/api/settings/coverage/<path:instrument>/pin")
def coverage_pin(instrument: str):
    import time as _time
    data = request.get_json() or {}
    pinned = bool(data.get("pinned", True))
    conn = connect(_db_path())
    try:
        set_pinned(conn, instrument=instrument, pinned=pinned, now=int(_time.time()))
        refresh_instrument_coverage_state(conn, now=int(_time.time()))
    finally:
        conn.close()
    return jsonify({"instrument": instrument, "pinned": pinned})


@bp.post("/api/settings/coverage/<path:instrument>/retire")
def coverage_retire(instrument: str):
    import time as _time
    conn = connect(_db_path())
    try:
        retire_now(conn, instrument=instrument, now=int(_time.time()))
    finally:
        conn.close()
    return jsonify({"instrument": instrument, "state": "retired"})


@bp.post("/api/settings/coverage/<path:instrument>/reactivate")
def coverage_reactivate(instrument: str):
    import time as _time
    conn = connect(_db_path())
    try:
        reactivate(conn, instrument=instrument, now=int(_time.time()))
        refresh_instrument_coverage_state(conn, now=int(_time.time()))
    finally:
        conn.close()
    return jsonify({"instrument": instrument, "state": "active"})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings_routes_instruments.py -v`
Expected: PASS.

- [ ] **Step 5: Add UI controls**

Append to `templates/instruments.html`:

```html
<h2>Coverage</h2>
<div id="coverage-rows"></div>
```

Append to `static/js/instruments.js`:

```js
async function renderCoverage() {
  const el = document.getElementById("coverage-rows");
  if (!el) return;
  const r = await fetch("/api/settings/coverage");
  const body = await r.json();
  const rows = body.rows.map((row) => {
    const pinBtn = `<button data-instrument="${row.instrument}" class="pin-btn">${row.pinned ? "Unpin" : "Pin"}</button>`;
    const retireBtn = row.state === "retired"
      ? `<button data-instrument="${row.instrument}" class="reactivate-btn">Reactivate</button>`
      : `<button data-instrument="${row.instrument}" class="retire-btn">Retire</button>`;
    return `<tr><td>${row.instrument}</td><td>${row.state}</td><td>${pinBtn} ${retireBtn}</td></tr>`;
  });
  el.innerHTML = `<table><thead><tr><th>Instrument</th><th>State</th><th>Actions</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  el.querySelectorAll(".pin-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const inst = btn.dataset.instrument;
      const current = btn.textContent === "Unpin";
      await fetch(`/api/settings/coverage/${encodeURIComponent(inst)}/pin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned: !current }),
      });
      await renderCoverage();
    });
  });
  el.querySelectorAll(".retire-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const inst = btn.dataset.instrument;
      await fetch(`/api/settings/coverage/${encodeURIComponent(inst)}/retire`, { method: "POST" });
      await renderCoverage();
    });
  });
  el.querySelectorAll(".reactivate-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const inst = btn.dataset.instrument;
      await fetch(`/api/settings/coverage/${encodeURIComponent(inst)}/reactivate`, { method: "POST" });
      await renderCoverage();
    });
  });
}

// Call at init-time from whatever initInstruments does — add a call:
renderCoverage();
```

- [ ] **Step 6: Commit**

```bash
git add routes/settings.py tests/test_settings_routes_instruments.py templates/instruments.html static/js/instruments.js
git commit -m "feat(settings): pin/retire/reactivate controls for coverage"
```

---

## Phase I — Chart 4h route + acceptance test

### Task 19: Chart route serves 4h via `derive_4h`

**Files:**
- Modify: `routes/pages.py` (or wherever `/api/chart/<instrument>` lives — check existing code)
- Modify: `tests/test_routes_chart_timeframes.py`

- [ ] **Step 1: Grep for the chart route**

Run: `grep -rn "api/chart" routes/`

Expected: locate the route handler that returns bars for a `(instrument, timeframe)` pair.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_routes_chart_timeframes.py`:

```python
def test_chart_tf_4h_derives_from_1h(client_factory, tmp_path):
    client = client_factory(tmp_path)
    from db import connect
    db_path = client.application.config["FTL_DB_PATH"]
    conn = connect(db_path)
    # Insert 4 consecutive 1h bars starting at a known session anchor.
    base = 1776290400  # 2026-04-14T22:00Z == 17:00 CT
    for h in range(4):
        conn.execute(
            "INSERT INTO bars (instrument, timeframe, time, open, high, low, close, volume, source, fetched_at)"
            " VALUES (?, '1h', ?, ?, ?, ?, ?, ?, 'yfinance', 0)",
            ("MNQ JUN26", base + h * 3600, 100 + h, 110 + h, 90 + h, 105 + h, 1000),
        )
    conn.close()
    resp = client.get(
        f"/api/chart/MNQ JUN26?tf=4h&start={base}&end={base + 4 * 3600 + 1}"
    )
    body = resp.get_json()
    assert len(body["bars"]) == 1
    assert body["bars"][0]["time"] == base
    assert body["bars"][0]["source"] == "derived-1h"
```

- [ ] **Step 3: Modify the chart route**

Wherever the chart route builds the bar list, intercept `tf == "4h"`:

```python
from services.ohlc.aggregate import derive_4h
from services.ohlc.store import read_range

# inside the route handler, after parsing params:
if timeframe == "4h":
    bars_1h = read_range(
        conn, instrument=instrument, timeframe="1h", start=start, end=end
    )
    bars = derive_4h(bars_1h)
else:
    bars = read_range(
        conn, instrument=instrument, timeframe=timeframe, start=start, end=end
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_routes_chart_timeframes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/pages.py tests/test_routes_chart_timeframes.py
git commit -m "feat(chart): serve 4h as read-time derivation over 1h bars"
```

---

### Task 20: Full-suite run + ruff + manual smoke test

- [ ] **Step 1: Ruff**

Run: `ruff check .`
Expected: no errors. Fix anything reported.

Run: `ruff format --check .`
Expected: no diffs. Fix with `ruff format .` if needed.

- [ ] **Step 2: Full test suite**

Run: `pytest`
Expected: all tests pass. Migration 009 in particular will purge the test DB's `bars`; make sure any test that inserts bars also runs migrations first (they should, because they all use `run_migrations`).

- [ ] **Step 3: Manual smoke test in Docker**

Run: `docker compose up -d --build`
Wait ~30 seconds for the first maintainer tick.

In Chrome, open `http://localhost:8000/data-health`:
- Confirm the 4h notice banner is visible.
- Confirm the maintainer panel shows a next run time and tokens.
- Confirm the matrix has no 4h column, has 1wk and 1mo columns.
- Click a partial cell; verify gaps shown are only inside the reach window.

In `/instruments`, confirm the coverage list shows your traded contracts with pin/retire buttons.

Tail logs: `docker compose logs -f futurestradinglog | grep -i ohlc`
Confirm you see `coverage_maintainer_tick` running with no stack traces and no 429s in the sources snapshot after 1-2 cycles.

- [ ] **Step 4: Final commit**

If the smoke test surfaced any small issue, commit the fix. Otherwise:

```bash
git log --oneline -20
```

Confirm plan 19 commits form a clean series.

---

## Self-review notes

- **Spec coverage:** Every spec section maps to at least one task: §1 coverage maintainer → Task 13, 15. §2 timeframe schedule → Task 15 (cron jobs) + Task 19 (4h read transform) + Task 3 (aggregate). §3 contract lifecycle → Task 10, 18. §4 symbology + purge migration → Task 4, 5, 6, 7, 8, 9. §5 rate limiter + breaker retune + data-health honesty → Task 2, 11, 12, 14, 16, 17. §6 file layout — matches directly. §7 testing — every module has a test task.
- **Type consistency:** `CoverageRow` and `State` used identically across Task 10, 13, 18. `TokenBucket.acquire` signature consistent between Task 2 and Task 11. `classify_window` return shape consistent between Task 12 and Task 16.
- **Placeholder scan:** No "TBD" / "add error handling" / "similar to" left. Each step has concrete code.
- **One drift caught during review:** The maintainer uses `source_symbol` to skip unknown instruments without a `contract_template`. This is correct: spec §4 says "never silently fall back to continuous for a suffixed instrument" — the maintainer respects that by not submitting the fetch at all, and it lets `XYZ JUN26`-style unknowns drop harmlessly.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-15-19-ohlc-coverage-maintainer.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.
2. **Inline Execution** — executing-plans, batch with checkpoints.

Which approach?
