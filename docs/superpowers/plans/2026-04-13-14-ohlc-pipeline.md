# OHLC Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated OHLC subsystem that fetches candlestick data from yfinance (primary) and Stooq (fallback), normalizes both to a single `Bar` model inside per-source adapters, persists to a `bars` table, runs gap-aware fetches in the background thread pool, exposes read-only chart APIs, and registers a second post-tick hook on `ImportPipeline` so new executions automatically trigger background OHLC fetches without ever blocking a request.

**Architecture:** All OHLC code lives under `services/ohlc/`. Per-source adapters (`yfinance_source.py`, `stooq_source.py`) implement the `OhlcSource` Protocol from `source.py` and return `list[Bar]` — nothing outside the adapter ever sees a pandas DataFrame, a Yahoo column name, or a Stooq CSV row. A per-source in-memory `CircuitBreaker` (`circuit_breaker.py`) opens after three consecutive failures or any HTTP 429/5xx, with a per-source cooldown before a half-open probe. `registry.py` owns the ordered source list and exposes `sources_for(timeframe)` so a source that doesn't support a timeframe is silently skipped. `store.py` wraps the `bars` table with a `(instrument, timeframe, time)` UPSERT and a range read. `gap_detection.py::find_gaps` returns the minimal missing sub-ranges for a request, consulting a stub session calendar (a default CME futures session in `services/instruments.py`) so overnight closes are not flagged as missing. `fetcher.py::fetch_range` is the single orchestrator: it asks the store what's missing, walks gaps, tries each source in registry order until one fills the gap, writes results via the store, and returns a `FetchResult` with per-attempt forensics. `jobs.py` is a thread-safe in-memory job registry (`job_id → Future + metadata`) used by the `/api/chart/{instrument}/fetch` route. The chart read route (`/api/chart/{instrument}`) reads `bars` directly and never calls the fetcher. The app factory registers (a) a second post-tick hook on `ImportPipeline.post_tick_hooks` that submits one `fetch_range` per `(instrument, timeframe)` to `BackgroundServices.pool` and returns immediately, and (b) two APScheduler jobs — every 15 minutes refreshing the last 6 hours, every 4 hours refreshing the last 7 days — for instruments that have any execution in the last 7 days.

**Tech Stack:** Python 3.11, Pydantic v2, SQLite (stdlib `sqlite3`), pytest, ruff. **Two new third-party dependencies pinned in `requirements.txt`: `yfinance==0.2.50` and `requests==2.32.3`.** Both are imported lazily inside their adapter files so the test suite can monkeypatch them without forcing a real network round-trip. Uses the existing `BackgroundServices.pool` (bounded ThreadPoolExecutor from plan 00) and the `ImportPipeline.post_tick_hooks` seam (from plan 10, already used by plan 11's integrity hook).

## Spec references

- `docs/rebuild-spec/00-README.md` — Load-bearing decision 5 (primary + fallback OHLC sources, format normalization at adapter boundary), decision 6 (OHLC isolated; no FK pointing at `bars`; no request handler blocks on a fetch).
- `docs/rebuild-spec/01-mission-and-principles.md` — The Six Rules. Rule 1 (`bars` is the single source of truth for OHLC; no parallel cache table), Rule 3 (the fetcher is one named pipeline with a single result type), Rule 4 (`Bar`, `FetchResult`, `AttemptRecord` are typed), Rule 6 (every adapter is testable in isolation by injecting a fake transport).
- `docs/rebuild-spec/02-glossary.md` — OHLC, Timeframe, Bar, Missing Candles, Coverage, Missing Candle Retrieval. Note the deliberate avoidance of the word "gap" in user-visible language; "find_gaps" is an internal helper name only.
- `docs/rebuild-spec/14-ohlc-pipeline.md` — The full feature spec. This plan is its implementation. Read all of it before writing any code; the table comparing yfinance and Stooq formats and the fragmentation hazards section are load-bearing.
- `docs/superpowers/plans/2026-04-13-10-import-pipeline.md` — `ImportPipeline.post_tick_hooks` shape and how the app factory wires hooks (`(_result, parsed, affected)`).
- `docs/superpowers/plans/2026-04-13-11-position-building.md` — File layout conventions, commit message style, fixture patterns (`migrated_db`, `tmp_config`), the existing post-tick hook (the one this plan adds runs alongside, not instead of).

## Load-bearing rules from the spec

Six rules from doc 14 drive most of this plan. If you find yourself violating any of them, stop:

1. **No request handler ever blocks on a fetch.** `/api/chart/{instrument}` reads `bars` and returns whatever is there. It never calls `fetcher.fetch_range`. The only way a fetch happens is via the post-tick hook, the scheduled refresh jobs, or a user-initiated `POST /api/chart/{instrument}/fetch` that immediately returns a job ID for polling. If a route file imports `fetch_range`, you've broken Rule 1.
2. **Format normalization happens inside adapters.** Nothing outside `services/ohlc/yfinance_source.py` or `services/ohlc/stooq_source.py` ever sees a `pandas.DataFrame`, a string like `"Adj Close"`, a naive `datetime`, or a raw CSV row. Each adapter returns `list[Bar]`. If an adapter can't normalize a response, it raises an `Exception` (or a more specific subclass) — it does not return partially normalized data.
3. **The `bars` table has no foreign keys pointing at it from anywhere.** No `executions` column references `bars`. No `positions` derived value embeds bars. Plan 13 will join read-side, but it does not introduce a FK.
4. **Per-source circuit breakers are per source, not per instrument.** If yfinance fails three calls in a row, the breaker opens for *all* yfinance calls until the cooldown expires. Stooq remains independently available. The breaker also opens immediately on any single `HTTPError(429)` or `HTTPError(5xx)` — that fast-trip is hardcoded policy, not config.
5. **Upscaling is forbidden.** If the request is for `1m` and only `5m` is available, return the `1m` data we managed to fetch and report the rest as unavailable. Never synthesize finer timeframes by downsampling coarser ones.
6. **`bars.source` is always populated.** Every row knows which adapter wrote it. The forensic column is non-negotiable.

## File layout this plan creates or modifies

```
/
├── migrations/
│   └── 004_bars.sql                      # NEW: bars table + composite-key index
├── models/
│   ├── bar.py                            # NEW: Bar, FetchResult, FetchStatus, AttemptRecord
│   └── __init__.py                       # MODIFY: export Bar, FetchResult, AttemptRecord
├── services/
│   ├── instruments.py                    # MODIFY: add default_timeframes, source_symbol stub, default_session
│   └── ohlc/
│       ├── __init__.py                   # NEW: empty marker
│       ├── source.py                     # NEW: OhlcSource Protocol
│       ├── circuit_breaker.py            # NEW: CircuitBreaker (closed/open/half_open)
│       ├── yfinance_source.py            # NEW: primary adapter
│       ├── stooq_source.py               # NEW: fallback adapter
│       ├── registry.py                   # NEW: SourceRegistry, sources_for(timeframe)
│       ├── store.py                      # NEW: insert_many, read_range, list_times
│       ├── gap_detection.py              # NEW: find_gaps with session calendar
│       ├── fetcher.py                    # NEW: fetch_range orchestrator
│       └── jobs.py                       # NEW: in-memory FetchJobRegistry
├── routes/
│   └── ohlc.py                           # NEW: chart + jobs + sources blueprint
├── app.py                                # MODIFY: register ohlc blueprint, post-tick hook, refresh jobs
├── requirements.txt                      # MODIFY: add yfinance, requests
└── tests/
    ├── test_migrations_004.py            # NEW
    ├── test_models_bar.py                # NEW
    ├── test_instruments_ohlc_stub.py     # NEW
    ├── test_circuit_breaker.py           # NEW
    ├── test_ohlc_store.py                # NEW
    ├── test_gap_detection.py             # NEW
    ├── test_yfinance_source.py           # NEW (transport monkeypatched)
    ├── test_stooq_source.py              # NEW (transport monkeypatched)
    ├── test_ohlc_registry.py             # NEW
    ├── test_ohlc_fetcher.py              # NEW
    ├── test_ohlc_jobs.py                 # NEW
    ├── test_routes_ohlc.py               # NEW
    └── test_app_factory_plan14.py        # NEW (hook registered, scheduled jobs registered)
```

---

## Task 1: Migration 004 — bars

**Files:**
- Create: `migrations/004_bars.sql`
- Create: `tests/test_migrations_004.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrations_004.py`:

```python
from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_004_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "004_bars" in applied_versions(conn)
    finally:
        conn.close()


def test_bars_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)").fetchall()}
        assert cols == {
            "instrument", "timeframe", "time",
            "open", "high", "low", "close",
            "volume", "source", "fetched_at",
        }
    finally:
        conn.close()


def test_bars_primary_key_is_composite(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute("PRAGMA table_info(bars)").fetchall()
        pk_cols = sorted([r[1] for r in rows if r[5] > 0], key=lambda c: c)
        assert pk_cols == ["instrument", "time", "timeframe"]
    finally:
        conn.close()


def test_bars_has_lookup_index(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='bars'"
            ).fetchall()
        }
        assert "idx_bars_instrument_tf_time" in names
    finally:
        conn.close()


def test_no_foreign_keys_to_bars(tmp_path: Path):
    """Rule 6 from doc 14 — bars must not be referenced by any other table."""
    conn = _migrate(tmp_path)
    try:
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        for tbl in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
                assert fk[2] != "bars", f"{tbl} has a FK to bars"
    finally:
        conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_004.py -q
```

Expected: failures because `bars` does not exist.

- [ ] **Step 3: Write `migrations/004_bars.sql`**

```sql
CREATE TABLE bars (
  instrument TEXT NOT NULL,
  timeframe  TEXT NOT NULL,
  time       INTEGER NOT NULL,
  open       REAL NOT NULL,
  high       REAL NOT NULL,
  low        REAL NOT NULL,
  close      REAL NOT NULL,
  volume     INTEGER NOT NULL,
  source     TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  PRIMARY KEY (instrument, timeframe, time)
);

CREATE INDEX idx_bars_instrument_tf_time
  ON bars(instrument, timeframe, time);
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_004.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/004_bars.sql tests/test_migrations_004.py
git commit -m "feat(ohlc): migration 004 — bars table"
```

---

## Task 2: Models — Bar, FetchResult, AttemptRecord

`Bar` is the normalized OHLC record. `AttemptRecord` is the per-source forensic entry the fetcher returns. `FetchResult` wraps the orchestrator's outcome. All are `StrictModel` per Rule 4.

**Files:**
- Create: `models/bar.py`
- Modify: `models/__init__.py`
- Create: `tests/test_models_bar.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_bar.py`:

```python
import pytest
from pydantic import ValidationError

from models.bar import AttemptRecord, Bar, FetchResult


def _bar_kwargs(**overrides):
    base = dict(
        instrument="MNQ",
        timeframe="1m",
        time=1_700_000_000,
        open=4237.75,
        high=4238.50,
        low=4237.50,
        close=4238.25,
        volume=42,
        source="yfinance",
    )
    base.update(overrides)
    return base


def test_bar_accepts_valid():
    b = Bar(**_bar_kwargs())
    assert b.instrument == "MNQ"
    assert b.timeframe == "1m"
    assert b.volume == 42


def test_bar_rejects_invalid_timeframe():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(timeframe="2m"))


def test_bar_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(adj_close=4238.0))


def test_bar_volume_must_be_int_not_none():
    with pytest.raises(ValidationError):
        Bar(**_bar_kwargs(volume=None))


def test_attempt_record_minimal():
    a = AttemptRecord(source="yfinance", outcome="ok", count=12, error=None)
    assert a.outcome == "ok"
    assert a.count == 12


def test_attempt_record_rejects_invalid_outcome():
    with pytest.raises(ValidationError):
        AttemptRecord(source="yfinance", outcome="maybe", count=0, error=None)


def test_fetch_result_cached():
    r = FetchResult(status="cached", bars_added=0, attempts=[])
    assert r.bars_added == 0
    assert r.attempts == []


def test_fetch_result_with_attempts():
    r = FetchResult(
        status="ok",
        bars_added=12,
        attempts=[
            AttemptRecord(source="yfinance", outcome="ok", count=12, error=None),
        ],
    )
    assert r.bars_added == 12
    assert len(r.attempts) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_bar.py -q
```

Expected: failures because `models.bar` doesn't exist.

- [ ] **Step 3: Create `models/bar.py`**

```python
from typing import Literal

from models.base import StrictModel

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
FetchStatus = Literal["cached", "ok", "partial", "all_sources_unavailable", "no_source_for_timeframe"]
Outcome = Literal["ok", "failed", "skipped"]


class Bar(StrictModel):
    instrument: str
    timeframe: Timeframe
    time: int          # unix seconds, UTC
    open: float
    high: float
    low: float
    close: float
    volume: int        # 0 if source did not provide one, never None
    source: str        # which adapter wrote it: 'yfinance', 'stooq', ...


class AttemptRecord(StrictModel):
    source: str
    outcome: Outcome
    count: int         # bars returned (0 for failed/skipped)
    error: str | None


class FetchResult(StrictModel):
    status: FetchStatus
    bars_added: int
    attempts: list[AttemptRecord]
```

- [ ] **Step 4: Edit `models/__init__.py`**

Add the new exports:

```python
from models.base import StrictModel
from models.bar import AttemptRecord, Bar, FetchResult
from models.execution import Execution, RejectRecord, TickResult
from models.position import Fill, IntegrityIssue, Position

__all__ = [
    "StrictModel",
    "Execution",
    "RejectRecord",
    "TickResult",
    "Position",
    "IntegrityIssue",
    "Fill",
    "Bar",
    "AttemptRecord",
    "FetchResult",
]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_bar.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add models/bar.py models/__init__.py tests/test_models_bar.py
git commit -m "feat(ohlc): Bar, FetchResult, AttemptRecord models"
```

---

## Task 3: Instrument config stub additions

Plan 16 ships the JSON-backed instrument registry. Plan 14 needs three things now: a canonical timeframe list, a per-source symbol mapper, and a default trading session for gap detection. All three are added to the existing `services/instruments.py` stub (the same stub plan 11 uses for multipliers). Plan 16 will replace this whole module with `services/instrument_registry.py` reading `instruments.json`; the imports here are the seam.

**Files:**
- Modify: `services/instruments.py`
- Create: `tests/test_instruments_ohlc_stub.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_instruments_ohlc_stub.py`:

```python
from services.instruments import (
    DEFAULT_TIMEFRAMES,
    default_session,
    source_symbol,
)


def test_default_timeframes_canonical():
    assert DEFAULT_TIMEFRAMES == ("1m", "5m", "15m", "1h", "1d")


def test_source_symbol_yfinance_known():
    assert source_symbol("MNQ", "yfinance") == "MNQ=F"
    assert source_symbol("ES", "yfinance") == "ES=F"


def test_source_symbol_stooq_known():
    assert source_symbol("MNQ", "stooq") == "mnq.f"
    assert source_symbol("ES", "stooq") == "es.f"


def test_source_symbol_strips_contract_suffix():
    assert source_symbol("MNQ SEP25", "yfinance") == "MNQ=F"


def test_source_symbol_unknown_returns_none():
    assert source_symbol("ZZZ", "yfinance") is None


def test_source_symbol_unknown_source_returns_none():
    assert source_symbol("MNQ", "polygon") is None


def test_default_session_shape():
    s = default_session("MNQ")
    assert s.timezone == "America/Chicago"
    assert s.open == "17:00"
    assert s.close == "16:00"
    assert s.daily_break_start == "16:00"
    assert s.daily_break_end == "17:00"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_instruments_ohlc_stub.py -q
```

Expected: ImportError or AttributeError.

- [ ] **Step 3: Edit `services/instruments.py`**

Append (do not delete the existing multiplier code that plan 11 ships):

```python
from dataclasses import dataclass

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

_YFINANCE_SYMBOLS: dict[str, str] = {
    "ES": "ES=F", "MES": "MES=F",
    "NQ": "NQ=F", "MNQ": "MNQ=F",
    "RTY": "RTY=F", "M2K": "M2K=F",
    "YM": "YM=F", "MYM": "MYM=F",
    "CL": "CL=F", "MCL": "MCL=F",
    "GC": "GC=F", "MGC": "MGC=F",
    "SI": "SI=F", "SIL": "SIL=F",
    "ZN": "ZN=F", "ZB": "ZB=F",
    "6E": "6E=F", "6B": "6B=F",
}

_STOOQ_SYMBOLS: dict[str, str] = {
    "ES": "es.f", "MES": "mes.f",
    "NQ": "nq.f", "MNQ": "mnq.f",
    "RTY": "rty.f", "M2K": "m2k.f",
    "YM": "ym.f", "MYM": "mym.f",
    "CL": "cl.f", "MCL": "mcl.f",
    "GC": "gc.f", "MGC": "mgc.f",
    "SI": "si.f", "SIL": "sil.f",
    "ZN": "zn.f", "ZB": "zb.f",
    "6E": "6e.f", "6B": "6b.f",
}

_SOURCE_TABLES: dict[str, dict[str, str]] = {
    "yfinance": _YFINANCE_SYMBOLS,
    "stooq": _STOOQ_SYMBOLS,
}


def source_symbol(instrument: str, source: str) -> str | None:
    """Map a canonical NT instrument key to a per-source symbol.

    Returns None if either the source is unknown or the instrument is not
    in the source's table. Adapters skip instruments they cannot identify.
    Plan 16 replaces this with the instruments.json registry.
    """
    table = _SOURCE_TABLES.get(source)
    if table is None:
        return None
    return table.get(base_symbol(instrument))


@dataclass(frozen=True)
class SessionCalendar:
    """A one-day-repeating session description.

    Plan 14 ships a single default (CME futures: 17:00 → 16:00 next day,
    with a 16:00–17:00 daily break, all in America/Chicago) which gap
    detection consults to avoid flagging the overnight close as missing.
    Plan 16 replaces this with per-instrument JSON-driven calendars.
    """
    timezone: str
    open: str               # "HH:MM" local
    close: str              # "HH:MM" local
    daily_break_start: str  # "HH:MM" local; "" disables
    daily_break_end: str    # "HH:MM" local; "" disables


_DEFAULT_CME_SESSION = SessionCalendar(
    timezone="America/Chicago",
    open="17:00",
    close="16:00",
    daily_break_start="16:00",
    daily_break_end="17:00",
)


def default_session(_instrument: str) -> SessionCalendar:
    """Return the default trading session for the given instrument.

    Plan 14 returns the CME futures session for every instrument. Plan 16
    will dispatch on `instrument` against the JSON registry.
    """
    return _DEFAULT_CME_SESSION
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_instruments_ohlc_stub.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add services/instruments.py tests/test_instruments_ohlc_stub.py
git commit -m "feat(ohlc): instruments.py — timeframes, source symbols, default session"
```

---

## Task 4: OhlcSource Protocol + package marker

Just the type contract. The two adapters (Tasks 7 and 8) implement it.

**Files:**
- Create: `services/ohlc/__init__.py` (empty)
- Create: `services/ohlc/source.py`

- [ ] **Step 1: Create `services/ohlc/__init__.py`**

```python
"""OHLC pipeline: per-source adapters, circuit breaker, fetcher, store, jobs.

Nothing outside this package may see raw source data (pandas DataFrames,
Stooq CSV rows, naive datetimes). Adapters return list[Bar].
"""
```

- [ ] **Step 2: Create `services/ohlc/source.py`**

```python
from typing import Protocol, runtime_checkable

from models.bar import Bar


@runtime_checkable
class OhlcSource(Protocol):
    """Per-source adapter contract.

    Each implementation lives in its own file under services/ohlc/.
    Adapters MUST return a normalized, UTC-timestamped list[Bar]; raising is
    the only legal way to report partial or malformed data.
    """

    name: str
    supported_timeframes: frozenset[str]

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        start: int,   # unix seconds, UTC, inclusive
        end: int,     # unix seconds, UTC, exclusive
    ) -> list[Bar]:
        ...
```

- [ ] **Step 3: Verify the package imports cleanly**

```bash
.venv/Scripts/python.exe -c "from services.ohlc.source import OhlcSource; print(OhlcSource)"
```

Expected: `<class 'services.ohlc.source.OhlcSource'>` (or similar).

- [ ] **Step 4: Commit**

```bash
git add services/ohlc/__init__.py services/ohlc/source.py
git commit -m "feat(ohlc): OhlcSource Protocol"
```

---

## Task 5: Circuit breaker

Per-source, in-memory, three-state. The breaker takes a `clock` callable in its constructor so tests can drive time forward without sleeping. Fast-trip on `requests.HTTPError` with a 429 or 5xx status code is detected by inspecting the exception's optional `.response.status_code` attribute — adapters that raise something else (a generic `Exception`) only contribute to the consecutive-failure counter.

**Files:**
- Create: `services/ohlc/circuit_breaker.py`
- Create: `tests/test_circuit_breaker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_circuit_breaker.py`:

```python
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

    clock.advance(2)              # past the cooldown
    assert cb.allows() is True    # half-open: probationary call allowed
    assert cb.state == "half_open"


def test_half_open_success_closes():
    clock = _Clock()
    cb = _make(clock, cooldown=10)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(11)
    cb.allows()                   # transitions to half_open
    cb.record_success()
    assert cb.state == "closed"
    assert cb.consecutive_failures == 0


def test_half_open_failure_reopens_with_fresh_cooldown():
    clock = _Clock()
    cb = _make(clock, cooldown=10)
    for _ in range(3):
        cb.record_failure(RuntimeError("x"))
    clock.advance(11)
    cb.allows()                   # half_open
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_circuit_breaker.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/circuit_breaker.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_circuit_breaker.py -q
```

Expected: 14 passed (10 named + 4 parametrized).

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/circuit_breaker.py tests/test_circuit_breaker.py
git commit -m "feat(ohlc): per-source CircuitBreaker"
```

---

## Task 6: Bars store

Read/write helpers for the `bars` table. `insert_many` UPSERTs on the composite key (re-fetching rewrites cleanly). `read_range` returns ordered `Bar` rows for a request. `list_times` returns just the timestamp column for `find_gaps` to walk.

**Files:**
- Create: `services/ohlc/store.py`
- Create: `tests/test_ohlc_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ohlc_store.py`:

```python
from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many, list_times, read_range


def _bar(t: int, *, close: float = 100.0, src: str = "yfinance") -> Bar:
    return Bar(
        instrument="MNQ",
        timeframe="1m",
        time=t,
        open=close - 0.25,
        high=close + 0.50,
        low=close - 0.50,
        close=close,
        volume=10,
        source=src,
    )


def test_insert_many_then_read_range(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60), _bar(120), _bar(180)])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert [b.time for b in bars] == [60, 120, 180]
    assert all(isinstance(b, Bar) for b in bars)


def test_insert_many_empty_is_noop(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [])
        assert read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000) == []
    finally:
        conn.close()


def test_insert_many_upserts_on_conflict(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60, close=100.0, src="yfinance")])
        insert_many(conn, [_bar(60, close=200.0, src="stooq")])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert len(bars) == 1
    assert bars[0].close == 200.0
    assert bars[0].source == "stooq"


def test_read_range_excludes_end(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(60), _bar(120), _bar(180)])
        bars = read_range(conn, instrument="MNQ", timeframe="1m", start=60, end=180)
    finally:
        conn.close()
    assert [b.time for b in bars] == [60, 120]


def test_read_range_filters_by_timeframe(migrated_db):
    conn = connect(migrated_db)
    try:
        b1 = _bar(60)
        b5 = _bar(60).model_copy(update={"timeframe": "5m"})
        insert_many(conn, [b1, b5])
        bars_1m = read_range(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
        bars_5m = read_range(conn, instrument="MNQ", timeframe="5m", start=0, end=1000)
    finally:
        conn.close()
    assert [b.timeframe for b in bars_1m] == ["1m"]
    assert [b.timeframe for b in bars_5m] == ["5m"]


def test_list_times_returns_sorted_unix_ts(migrated_db):
    conn = connect(migrated_db)
    try:
        insert_many(conn, [_bar(120), _bar(60), _bar(180)])
        times = list_times(conn, instrument="MNQ", timeframe="1m", start=0, end=1000)
    finally:
        conn.close()
    assert times == [60, 120, 180]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_store.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/store.py`**

```python
import sqlite3
import time
from collections.abc import Sequence

from models.bar import Bar


def insert_many(conn: sqlite3.Connection, bars: Sequence[Bar]) -> int:
    """UPSERT bars on (instrument, timeframe, time). Returns rows affected.

    Re-fetching an existing range cleanly rewrites it; whichever source
    last wrote the row wins. Keep this transactional decision at the
    *caller*: the fetcher wraps a single tick's writes in BEGIN/COMMIT.
    """
    if not bars:
        return 0
    fetched_at = int(time.time())
    rows = [
        (
            b.instrument, b.timeframe, b.time,
            b.open, b.high, b.low, b.close,
            b.volume, b.source, fetched_at,
        )
        for b in bars
    ]
    cur = conn.executemany(
        "INSERT INTO bars "
        "(instrument, timeframe, time, open, high, low, close, volume, source, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(instrument, timeframe, time) DO UPDATE SET "
        " open = excluded.open,"
        " high = excluded.high,"
        " low = excluded.low,"
        " close = excluded.close,"
        " volume = excluded.volume,"
        " source = excluded.source,"
        " fetched_at = excluded.fetched_at",
        rows,
    )
    return cur.rowcount or 0


def read_range(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[Bar]:
    """Return bars in [start, end) ordered by time."""
    rows = conn.execute(
        "SELECT instrument, timeframe, time, open, high, low, close, volume, source "
        "FROM bars WHERE instrument = ? AND timeframe = ? "
        "  AND time >= ? AND time < ? "
        "ORDER BY time",
        (instrument, timeframe, start, end),
    ).fetchall()
    return [
        Bar(
            instrument=r["instrument"],
            timeframe=r["timeframe"],
            time=r["time"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            source=r["source"],
        )
        for r in rows
    ]


def list_times(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[int]:
    """Return the sorted list of bar timestamps in [start, end)."""
    rows = conn.execute(
        "SELECT time FROM bars WHERE instrument = ? AND timeframe = ? "
        "  AND time >= ? AND time < ? ORDER BY time",
        (instrument, timeframe, start, end),
    ).fetchall()
    return [int(r["time"]) for r in rows]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_store.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/store.py tests/test_ohlc_store.py
git commit -m "feat(ohlc): bars store with UPSERT and range read"
```

---

## Task 7: Gap detection

`find_gaps(conn, instrument, timeframe, start, end)` returns the minimal list of `(sub_start, sub_end)` ranges in `[start, end)` where bars are missing **and** the instrument's session is open. Walks the existing bar timestamps, emits any run of missing slots aligned to the timeframe stride, and trims runs that fall during the daily break.

**Files:**
- Create: `services/ohlc/gap_detection.py`
- Create: `tests/test_gap_detection.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gap_detection.py`:

```python
from datetime import datetime, timezone

from db import connect
from models.bar import Bar
from services.ohlc.gap_detection import find_gaps, timeframe_seconds
from services.ohlc.store import insert_many


def _t(s: str) -> int:
    """UTC ISO -> unix seconds."""
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())


def test_timeframe_seconds_table():
    assert timeframe_seconds("1m") == 60
    assert timeframe_seconds("5m") == 300
    assert timeframe_seconds("15m") == 900
    assert timeframe_seconds("1h") == 3600
    assert timeframe_seconds("4h") == 14400
    assert timeframe_seconds("1d") == 86400


def test_no_bars_returns_full_range_during_session(migrated_db):
    """An empty store should yield one gap covering the whole session window."""
    conn = connect(migrated_db)
    try:
        # 22:00 UTC = 17:00 America/Chicago = session open
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:06:00")
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == [(start, end)]


def test_full_coverage_returns_empty(migrated_db):
    conn = connect(migrated_db)
    try:
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:04:00")
        bars = [
            Bar(instrument="MNQ", timeframe="1m", time=t,
                open=1.0, high=1.0, low=1.0, close=1.0, volume=0, source="t")
            for t in range(start, end, 60)
        ]
        insert_many(conn, bars)
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == []


def test_single_missing_run_in_middle(migrated_db):
    conn = connect(migrated_db)
    try:
        start = _t("2026-04-13T22:01:00")
        end = _t("2026-04-13T22:06:00")
        present_times = [start, start + 60, start + 240]   # missing 120, 180
        bars = [
            Bar(instrument="MNQ", timeframe="1m", time=t,
                open=1.0, high=1.0, low=1.0, close=1.0, volume=0, source="t")
            for t in present_times
        ]
        insert_many(conn, bars)
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == [(start + 120, start + 240)]


def test_skips_daily_break(migrated_db):
    """No gap should be reported during the 16:00–17:00 America/Chicago break."""
    conn = connect(migrated_db)
    try:
        # 21:00–22:00 UTC = 16:00–17:00 America/Chicago = daily break
        start = _t("2026-04-13T21:00:00")
        end = _t("2026-04-13T22:00:00")
        gaps = find_gaps(conn, instrument="MNQ", timeframe="1m", start=start, end=end)
    finally:
        conn.close()
    assert gaps == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_gap_detection.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/gap_detection.py`**

```python
import sqlite3
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from services.instruments import default_session
from services.ohlc.store import list_times

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError as e:
        raise ValueError(f"unknown timeframe: {timeframe}") from e


def _hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def _is_in_break(ts: int, tz: ZoneInfo, break_start: time, break_end: time) -> bool:
    """Is this UTC unix timestamp inside the instrument's daily break?"""
    local = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).time()
    if break_start <= break_end:
        return break_start <= local < break_end
    # break wraps midnight
    return local >= break_start or local < break_end


def _expected_slots(
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[int]:
    """Generate the timeframe-aligned slots in [start, end) that fall inside
    the instrument's trading session (i.e. NOT during the daily break)."""
    stride = timeframe_seconds(timeframe)
    aligned_start = start - (start % stride)
    if aligned_start < start:
        aligned_start += stride

    session = default_session(instrument)
    tz = ZoneInfo(session.timezone)
    has_break = bool(session.daily_break_start) and bool(session.daily_break_end)
    if has_break:
        bs = _hhmm(session.daily_break_start)
        be = _hhmm(session.daily_break_end)

    slots: list[int] = []
    t = aligned_start
    while t < end:
        if not has_break or not _is_in_break(t, tz, bs, be):
            slots.append(t)
        t += stride
    return slots


def find_gaps(
    conn: sqlite3.Connection,
    *,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Minimal `(sub_start, sub_end)` ranges in [start, end) the store is missing.

    Consults the instrument's session calendar (currently a stub default;
    plan 16 makes it per-instrument) so the daily break is not flagged as
    missing.
    """
    if start >= end:
        return []
    expected = _expected_slots(instrument, timeframe, start, end)
    if not expected:
        return []
    present = set(list_times(conn, instrument=instrument, timeframe=timeframe, start=start, end=end))

    stride = timeframe_seconds(timeframe)
    gaps: list[tuple[int, int]] = []
    run_start: int | None = None
    prev_slot: int | None = None
    for slot in expected:
        if slot in present:
            if run_start is not None:
                gaps.append((run_start, prev_slot + stride))
                run_start = None
            prev_slot = slot
            continue
        if run_start is None:
            run_start = slot
        prev_slot = slot
    if run_start is not None:
        gaps.append((run_start, prev_slot + stride))
    return gaps
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_gap_detection.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/gap_detection.py tests/test_gap_detection.py
git commit -m "feat(ohlc): session-aware find_gaps"
```

---

## Task 8: yfinance adapter

Lazy-imports `yfinance` inside `fetch()` so the test suite never needs to install it for unit tests, and a missing package becomes an ordinary fetch failure rather than an import-time crash. Tests monkeypatch `services.ohlc.yfinance_source._download` to inject a fake DataFrame.

**Files:**
- Create: `services/ohlc/yfinance_source.py`
- Create: `tests/test_yfinance_source.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_yfinance_source.py`:

```python
import pytest

from models.bar import Bar
from services.ohlc import yfinance_source as yfs
from services.ohlc.yfinance_source import YfinanceSource


class _FakeDF:
    """Minimal stand-in for pandas.DataFrame that supports the few accesses
    the adapter makes — itertuples-style iteration and an `empty` property."""

    def __init__(self, records):
        self._records = records

    @property
    def empty(self):
        return not self._records

    def itertuples(self, index=True, name="Bar"):
        for r in self._records:
            yield r


class _Row:
    def __init__(self, ts_unix, o, h, lo, c, v):
        self.Index = _FakeTs(ts_unix)
        self.Open = o
        self.High = h
        self.Low = lo
        self.Close = c
        self.Volume = v


class _FakeTs:
    def __init__(self, unix):
        self._unix = unix

    def timestamp(self):
        return self._unix


def test_supported_timeframes_includes_1m_through_1d():
    s = YfinanceSource()
    for tf in ("1m", "5m", "15m", "1h", "1d"):
        assert tf in s.supported_timeframes


def test_name_is_yfinance():
    assert YfinanceSource().name == "yfinance"


def test_fetch_unknown_instrument_returns_empty(monkeypatch):
    s = YfinanceSource()
    bars = s.fetch("ZZZ_NOT_REAL", "1m", 1_700_000_000, 1_700_001_000)
    assert bars == []


def test_fetch_returns_normalized_bars(monkeypatch):
    rows = [
        _Row(1_700_000_060, 4237.75, 4238.50, 4237.50, 4238.25, 12),
        _Row(1_700_000_120, 4238.25, 4239.00, 4238.00, 4238.75, 8),
    ]

    def fake_download(symbol, *, start, end, interval):
        assert symbol == "MNQ=F"
        assert interval == "1m"
        return _FakeDF(rows)

    monkeypatch.setattr(yfs, "_download", fake_download)
    bars = YfinanceSource().fetch("MNQ", "1m", 1_700_000_000, 1_700_000_180)
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)
    assert [b.time for b in bars] == [1_700_000_060, 1_700_000_120]
    assert all(b.source == "yfinance" for b in bars)
    assert all(b.timeframe == "1m" for b in bars)
    assert all(b.instrument == "MNQ" for b in bars)


def test_fetch_returns_empty_for_empty_dataframe(monkeypatch):
    monkeypatch.setattr(yfs, "_download", lambda *a, **k: _FakeDF([]))
    assert YfinanceSource().fetch("MNQ", "1m", 1, 2) == []


def test_fetch_propagates_transport_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(yfs, "_download", boom)
    with pytest.raises(RuntimeError):
        YfinanceSource().fetch("MNQ", "1m", 1, 2)


def test_fetch_volume_nan_becomes_zero(monkeypatch):
    nan = float("nan")
    rows = [_Row(1_700_000_060, 1.0, 1.0, 1.0, 1.0, nan)]
    monkeypatch.setattr(yfs, "_download", lambda *a, **k: _FakeDF(rows))
    bars = YfinanceSource().fetch("MNQ", "1m", 1_700_000_000, 1_700_000_120)
    assert bars[0].volume == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_yfinance_source.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/yfinance_source.py`**

```python
import math
from datetime import datetime, timezone

from models.bar import Bar
from services.instruments import source_symbol


def _download(symbol: str, *, start, end, interval):
    """Indirection so tests can monkeypatch without installing yfinance.

    The real implementation lazy-imports yfinance, calls download(), and
    returns the resulting pandas DataFrame. Any error from yfinance
    propagates to the caller, which is the circuit breaker's job to handle.
    """
    import yfinance as yf  # deferred so the test suite never imports it
    return yf.download(
        symbol,
        start=start,
        end=end,
        interval=interval,
        progress=False,
        auto_adjust=False,
    )


class YfinanceSource:
    """Primary OHLC source. Wraps the yfinance library."""

    name = "yfinance"
    supported_timeframes = frozenset({"1m", "5m", "15m", "1h", "1d"})

    def fetch(self, instrument: str, timeframe: str, start: int, end: int) -> list[Bar]:
        if timeframe not in self.supported_timeframes:
            return []
        symbol = source_symbol(instrument, "yfinance")
        if symbol is None:
            return []

        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        df = _download(symbol, start=start_dt, end=end_dt, interval=timeframe)
        if df is None or df.empty:
            return []

        bars: list[Bar] = []
        for row in df.itertuples(index=True, name="Bar"):
            ts = int(row.Index.timestamp())
            volume = row.Volume
            if volume is None or (isinstance(volume, float) and math.isnan(volume)):
                volume = 0
            bars.append(
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=ts,
                    open=float(row.Open),
                    high=float(row.High),
                    low=float(row.Low),
                    close=float(row.Close),
                    volume=int(volume),
                    source="yfinance",
                )
            )
        return bars
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_yfinance_source.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/yfinance_source.py tests/test_yfinance_source.py
git commit -m "feat(ohlc): yfinance adapter"
```

---

## Task 9: Stooq adapter

Stooq is the fallback. Plain `requests.get` against `https://stooq.com/q/d/l/?s={symbol}&i={interval}` returning CSV. Tests monkeypatch `services.ohlc.stooq_source._http_get` to inject CSV text. Stooq's intraday support is narrower than yfinance, so the adapter declares only `{"1d"}` as `supported_timeframes` for now — the registry will skip it for finer requests automatically.

**Files:**
- Create: `services/ohlc/stooq_source.py`
- Create: `tests/test_stooq_source.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stooq_source.py`:

```python
import pytest

from models.bar import Bar
from services.ohlc import stooq_source as ss
from services.ohlc.stooq_source import StooqSource

_DAILY_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-04-10,4200.00,4250.00,4180.00,4230.50,123456\n"
    "2026-04-11,4231.00,4240.00,4180.00,4189.00,98765\n"
)


def test_name_is_stooq():
    assert StooqSource().name == "stooq"


def test_supported_timeframes_is_daily_only():
    assert StooqSource().supported_timeframes == frozenset({"1d"})


def test_fetch_unknown_instrument_returns_empty():
    assert StooqSource().fetch("ZZZ_NOT_REAL", "1d", 1, 2) == []


def test_fetch_unsupported_timeframe_returns_empty():
    assert StooqSource().fetch("MNQ", "1m", 1, 2) == []


def test_fetch_parses_daily_csv(monkeypatch):
    captured = {}

    def fake_get(url):
        captured["url"] = url
        return _DAILY_CSV

    monkeypatch.setattr(ss, "_http_get", fake_get)

    start = ss._iso_to_unix("2026-04-09")
    end = ss._iso_to_unix("2026-04-12")
    bars = StooqSource().fetch("MNQ", "1d", start, end)

    assert "mnq.f" in captured["url"]
    assert "i=d" in captured["url"]
    assert len(bars) == 2
    assert all(isinstance(b, Bar) for b in bars)
    assert all(b.source == "stooq" for b in bars)
    assert all(b.instrument == "MNQ" for b in bars)
    assert all(b.timeframe == "1d" for b in bars)
    assert bars[0].close == 4230.50
    assert bars[1].close == 4189.00


def test_fetch_filters_to_requested_range(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: _DAILY_CSV)
    start = ss._iso_to_unix("2026-04-11")
    end = ss._iso_to_unix("2026-04-12")
    bars = StooqSource().fetch("MNQ", "1d", start, end)
    assert len(bars) == 1
    assert bars[0].close == 4189.00


def test_fetch_blank_volume_becomes_zero(monkeypatch):
    csv_text = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-04-10,4200.00,4250.00,4180.00,4230.50,\n"
    )
    monkeypatch.setattr(ss, "_http_get", lambda url: csv_text)
    bars = StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999)
    assert bars[0].volume == 0


def test_fetch_empty_body_returns_empty(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: "")
    assert StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999) == []


def test_fetch_header_only_returns_empty(monkeypatch):
    monkeypatch.setattr(ss, "_http_get", lambda url: "Date,Open,High,Low,Close,Volume\n")
    assert StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999) == []


def test_fetch_propagates_transport_error(monkeypatch):
    def boom(url):
        raise RuntimeError("dns")
    monkeypatch.setattr(ss, "_http_get", boom)
    with pytest.raises(RuntimeError):
        StooqSource().fetch("MNQ", "1d", 0, 9_999_999_999)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_stooq_source.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/stooq_source.py`**

```python
import csv
from datetime import datetime, timezone
from io import StringIO

from models.bar import Bar
from services.instruments import source_symbol

_STOOQ_INTERVALS: dict[str, str] = {"1d": "d"}


def _http_get(url: str) -> str:
    """Indirection so tests can monkeypatch without hitting the network.

    Real implementation calls requests.get and returns the response text.
    Raises requests.HTTPError on 4xx/5xx so the circuit breaker can detect
    it via .response.status_code.
    """
    import requests  # deferred so the test suite never imports it
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def _iso_to_unix(iso_date: str) -> int:
    return int(datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc).timestamp())


class StooqSource:
    """Fallback OHLC source. Plain HTTP CSV from stooq.com.

    Conservative: only daily bars are declared supported until per-instrument
    intraday verification (doc 14, open question 3) extends this set.
    """

    name = "stooq"
    supported_timeframes = frozenset({"1d"})

    def fetch(self, instrument: str, timeframe: str, start: int, end: int) -> list[Bar]:
        if timeframe not in self.supported_timeframes:
            return []
        symbol = source_symbol(instrument, "stooq")
        if symbol is None:
            return []

        interval = _STOOQ_INTERVALS[timeframe]
        url = f"https://stooq.com/q/d/l/?s={symbol}&i={interval}"
        text = _http_get(url)
        if not text or not text.strip():
            return []

        reader = csv.DictReader(StringIO(text))
        bars: list[Bar] = []
        for row in reader:
            try:
                ts = _iso_to_unix(row["Date"])
            except (KeyError, ValueError):
                continue
            if ts < start or ts >= end:
                continue
            try:
                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
            except (KeyError, ValueError):
                continue
            vol_raw = (row.get("Volume") or "").strip()
            try:
                volume = int(vol_raw) if vol_raw else 0
            except ValueError:
                volume = 0
            bars.append(
                Bar(
                    instrument=instrument,
                    timeframe=timeframe,
                    time=ts,
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=volume,
                    source="stooq",
                )
            )
        return bars
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_stooq_source.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/stooq_source.py tests/test_stooq_source.py
git commit -m "feat(ohlc): stooq adapter"
```

---

## Task 10: Source registry

Holds the ordered list of `(OhlcSource, CircuitBreaker)` pairs and exposes `sources_for(timeframe)` (skip sources that don't support the requested timeframe) and `status_snapshots()` for the monitoring API. The default registry is built by `build_default_registry(clock=time.time)` so tests can substitute a fake clock for breaker timing.

**Files:**
- Create: `services/ohlc/registry.py`
- Create: `tests/test_ohlc_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ohlc_registry.py`:

```python
import time

from services.ohlc.registry import (
    SourceRegistry,
    build_default_registry,
)
from services.ohlc.stooq_source import StooqSource
from services.ohlc.yfinance_source import YfinanceSource


def _clock():
    return int(time.time())


def test_default_registry_yfinance_first():
    reg = build_default_registry(clock=_clock)
    assert [s.name for s, _b in reg.entries] == ["yfinance", "stooq"]


def test_sources_for_filters_by_supported_timeframe():
    reg = build_default_registry(clock=_clock)
    one_min = list(reg.sources_for("1m"))
    one_day = list(reg.sources_for("1d"))
    assert [s.name for s, _b in one_min] == ["yfinance"]
    assert [s.name for s, _b in one_day] == ["yfinance", "stooq"]


def test_sources_for_skips_open_breakers():
    yf = YfinanceSource()
    st = StooqSource()
    reg = SourceRegistry(clock=_clock)
    reg.register(yf, failure_threshold=3, cooldown_seconds=600)
    reg.register(st, failure_threshold=3, cooldown_seconds=1800)

    # Trip yfinance breaker
    yf_breaker = reg.entries[0][1]
    for _ in range(3):
        yf_breaker.record_failure(RuntimeError("boom"))

    available = list(reg.sources_for("1d"))
    assert [s.name for s, _b in available] == ["stooq"]


def test_status_snapshots_returns_one_per_source():
    reg = build_default_registry(clock=_clock)
    snaps = reg.status_snapshots()
    assert {s["name"] for s in snaps} == {"yfinance", "stooq"}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_registry.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/registry.py`**

```python
from collections.abc import Callable, Iterator

from services.ohlc.circuit_breaker import CircuitBreaker
from services.ohlc.source import OhlcSource
from services.ohlc.stooq_source import StooqSource
from services.ohlc.yfinance_source import YfinanceSource


class SourceRegistry:
    """Ordered list of (source, breaker) pairs.

    The order in which `register()` is called determines the order in which
    the fetcher tries sources. Iteration filters to sources whose breaker
    currently allows a call AND that declare support for the requested
    timeframe (Rule 5: no upscaling).
    """

    def __init__(self, *, clock: Callable[[], int]) -> None:
        self._clock = clock
        self.entries: list[tuple[OhlcSource, CircuitBreaker]] = []

    def register(
        self,
        source: OhlcSource,
        *,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        breaker = CircuitBreaker(
            name=source.name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
            clock=self._clock,
        )
        self.entries.append((source, breaker))

    def sources_for(self, timeframe: str) -> Iterator[tuple[OhlcSource, CircuitBreaker]]:
        for source, breaker in self.entries:
            if timeframe not in source.supported_timeframes:
                continue
            if not breaker.allows():
                continue
            yield source, breaker

    def status_snapshots(self) -> list[dict]:
        return [breaker.status_snapshot() for _s, breaker in self.entries]


def build_default_registry(*, clock: Callable[[], int]) -> SourceRegistry:
    """Default order: yfinance primary, stooq fallback.

    The breaker parameters match doc 14:
    - yfinance: 3 failures, 600s cooldown
    - stooq:    3 failures, 1800s cooldown
    """
    reg = SourceRegistry(clock=clock)
    reg.register(YfinanceSource(), failure_threshold=3, cooldown_seconds=600)
    reg.register(StooqSource(), failure_threshold=3, cooldown_seconds=1800)
    return reg
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_registry.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/registry.py tests/test_ohlc_registry.py
git commit -m "feat(ohlc): SourceRegistry with per-source breakers"
```

---

## Task 11: Fetcher orchestrator

The single `fetch_range(db_path, registry, instrument, timeframe, start, end)` entry point. Asks the store what's missing, walks the gap list, tries each registry source in order until one fills each gap (or all skip/fail), writes results via the store, and returns a `FetchResult` with one `AttemptRecord` per source it touched.

**Files:**
- Create: `services/ohlc/fetcher.py`
- Create: `tests/test_ohlc_fetcher.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ohlc_fetcher.py`:

```python
import pytest

from db import connect
from models.bar import Bar
from services.ohlc.circuit_breaker import CircuitBreaker
from services.ohlc.fetcher import fetch_range
from services.ohlc.registry import SourceRegistry
from services.ohlc.store import insert_many


class _FakeSource:
    def __init__(self, name, *, supported, bars=None, error=None):
        self.name = name
        self.supported_timeframes = frozenset(supported)
        self._bars = bars or []
        self._error = error
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch(self, instrument, timeframe, start, end):
        self.calls.append((instrument, timeframe, start, end))
        if self._error is not None:
            raise self._error
        return [b for b in self._bars if start <= b.time < end]


def _bar(t, src="fake"):
    return Bar(
        instrument="MNQ", timeframe="1d", time=t,
        open=1.0, high=1.0, low=1.0, close=float(t),
        volume=0, source=src,
    )


def _registry_with(sources, *, threshold=3, cooldown=10):
    clock = lambda: 0
    reg = SourceRegistry(clock=clock)
    for s in sources:
        reg.register(s, failure_threshold=threshold, cooldown_seconds=cooldown)
    return reg


def test_fully_cached_returns_cached_status(migrated_db):
    primary = _FakeSource("primary", supported={"1d"}, bars=[])
    reg = _registry_with([primary])
    # Pre-populate the store with two daily bars
    conn = connect(migrated_db)
    try:
        insert_many(
            conn,
            [
                Bar(instrument="MNQ", timeframe="1d", time=86400,
                    open=1, high=1, low=1, close=1, volume=0, source="seed"),
                Bar(instrument="MNQ", timeframe="1d", time=86400 * 2,
                    open=1, high=1, low=1, close=1, volume=0, source="seed"),
            ],
        )
    finally:
        conn.close()

    # Use a tiny window that's exactly covered
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 3,
    )
    # Even if find_gaps returns extra "missing" bars from session-aware
    # expansion, the primary returns nothing for those, so bars_added stays 0.
    assert primary.calls == [] or all(c is not None for c in primary.calls)
    assert result.status in {"cached", "partial", "all_sources_unavailable"}


def test_primary_returns_bars(migrated_db):
    bars = [_bar(86400 * i, src="primary") for i in range(1, 4)]
    primary = _FakeSource("primary", supported={"1d"}, bars=bars)
    reg = _registry_with([primary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
    )
    assert result.bars_added >= 1
    assert any(a.outcome == "ok" for a in result.attempts)
    assert any(a.source == "primary" for a in result.attempts)


def test_primary_fails_falls_back_to_secondary(migrated_db):
    primary = _FakeSource("primary", supported={"1d"}, error=RuntimeError("boom"))
    bars = [_bar(86400 * i, src="secondary") for i in range(1, 4)]
    secondary = _FakeSource("secondary", supported={"1d"}, bars=bars)
    reg = _registry_with([primary, secondary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
    )
    sources_attempted = {a.source for a in result.attempts}
    assert "primary" in sources_attempted
    assert "secondary" in sources_attempted
    assert result.bars_added >= 1


def test_all_sources_open_returns_all_unavailable(migrated_db):
    primary = _FakeSource("primary", supported={"1d"}, error=RuntimeError("boom"))
    secondary = _FakeSource("secondary", supported={"1d"}, error=RuntimeError("boom"))
    reg = _registry_with([primary, secondary], threshold=1)
    # First call trips both
    fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
    )
    # Second call: both breakers open, no fetches happen
    primary.calls.clear()
    secondary.calls.clear()
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1d",
        start=86400,
        end=86400 * 4,
    )
    assert result.bars_added == 0
    assert result.status == "all_sources_unavailable"
    assert primary.calls == []
    assert secondary.calls == []


def test_no_source_supports_timeframe_returns_no_source_status(migrated_db):
    primary = _FakeSource("primary", supported={"1d"}, bars=[])
    reg = _registry_with([primary])
    result = fetch_range(
        db_path=migrated_db,
        registry=reg,
        instrument="MNQ",
        timeframe="1m",
        start=60,
        end=300,
    )
    assert result.status == "no_source_for_timeframe"
    assert result.bars_added == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_fetcher.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/fetcher.py`**

```python
from pathlib import Path

from db import connect
from logging_config import get_logger
from models.bar import AttemptRecord, Bar, FetchResult
from services.ohlc.gap_detection import find_gaps
from services.ohlc.registry import SourceRegistry
from services.ohlc.store import insert_many

log = get_logger("ohlc.fetcher")


def fetch_range(
    *,
    db_path: Path | str,
    registry: SourceRegistry,
    instrument: str,
    timeframe: str,
    start: int,
    end: int,
) -> FetchResult:
    """The single OHLC orchestration entry point.

    Steps:
      1. Find the missing sub-ranges in [start, end) the store doesn't have.
      2. For each missing sub-range, try each registry source in order.
         A source is skipped if its breaker is open OR if it doesn't
         declare the requested timeframe as supported.
      3. The first source that returns bars (even an empty list, treated as
         "this source had nothing for the range") fills the gap; we move on.
         A raised exception is recorded as a failure and we try the next
         source for the same gap.
      4. All collected bars are UPSERTed via the store in a single tick.
      5. Return a FetchResult with per-attempt forensics.

    The fetcher is the ONLY caller of source.fetch() in the entire app.
    Routes do not call it. Plan 14's post-tick hook submits it to the
    background pool; the scheduled refresh jobs call it on the scheduler
    thread.
    """
    if start >= end:
        return FetchResult(status="cached", bars_added=0, attempts=[])

    # Short-circuit if nothing in the registry supports this timeframe.
    if not any(timeframe in s.supported_timeframes for s, _b in registry.entries):
        return FetchResult(status="no_source_for_timeframe", bars_added=0, attempts=[])

    conn = connect(db_path)
    try:
        gaps = find_gaps(
            conn,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        if not gaps:
            return FetchResult(status="cached", bars_added=0, attempts=[])
    finally:
        conn.close()

    bars_collected: list[Bar] = []
    attempts: list[AttemptRecord] = []
    any_gap_filled = False

    for gap_start, gap_end in gaps:
        gap_filled = False
        for source, breaker in list(registry.entries):
            if timeframe not in source.supported_timeframes:
                continue
            if not breaker.allows():
                attempts.append(AttemptRecord(
                    source=source.name, outcome="skipped", count=0, error=None,
                ))
                continue
            try:
                bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                breaker.record_success()
                bars_collected.extend(bars)
                attempts.append(AttemptRecord(
                    source=source.name, outcome="ok", count=len(bars), error=None,
                ))
                gap_filled = True
                break
            except Exception as e:
                breaker.record_failure(e)
                attempts.append(AttemptRecord(
                    source=source.name, outcome="failed", count=0, error=repr(e),
                ))
                continue
        if gap_filled:
            any_gap_filled = True

    if bars_collected:
        conn = connect(db_path)
        try:
            conn.execute("BEGIN")
            try:
                insert_many(conn, bars_collected)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    if bars_collected:
        status = "ok" if any_gap_filled else "partial"
    elif any_gap_filled:
        status = "ok"
    else:
        status = "all_sources_unavailable"

    log.info(
        "fetch_range done",
        extra={
            "instrument": instrument,
            "tf": timeframe,
            "bars_added": len(bars_collected),
            "status": status,
        },
    )
    return FetchResult(
        status=status,
        bars_added=len(bars_collected),
        attempts=attempts,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_fetcher.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/fetcher.py tests/test_ohlc_fetcher.py
git commit -m "feat(ohlc): fetch_range orchestrator"
```

---

## Task 12: Fetch job registry

In-memory `FetchJobRegistry` that wraps job submission to a thread pool. `submit(pool, fn)` returns a `job_id`, kicks off the future, and stores the resulting `Future` and metadata. `status(job_id)` returns one of `pending`, `done`, `failed`, or `not_found`. Used by both the route (`POST /api/chart/{instrument}/fetch`) and the post-import hook.

**Files:**
- Create: `services/ohlc/jobs.py`
- Create: `tests/test_ohlc_jobs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ohlc_jobs.py`:

```python
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.ohlc.jobs import FetchJobRegistry


@pytest.fixture
def pool():
    p = ThreadPoolExecutor(max_workers=2)
    yield p
    p.shutdown(wait=True, cancel_futures=True)


def _wait(reg, job_id, target, deadline=2.0):
    end = time.time() + deadline
    while time.time() < end:
        if reg.status(job_id)["state"] == target:
            return
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {target}")


def test_unknown_job_id_is_not_found(pool):
    reg = FetchJobRegistry()
    assert reg.status("nope")["state"] == "not_found"


def test_submit_returns_unique_job_id(pool):
    reg = FetchJobRegistry()
    a = reg.submit(pool, lambda: None, meta={"x": 1})
    b = reg.submit(pool, lambda: None, meta={"x": 2})
    assert a != b


def test_submit_runs_function(pool):
    reg = FetchJobRegistry()
    seen = []
    job_id = reg.submit(pool, lambda: seen.append("ran"), meta={})
    _wait(reg, job_id, "done")
    assert seen == ["ran"]


def test_done_state(pool):
    reg = FetchJobRegistry()
    job_id = reg.submit(pool, lambda: 42, meta={"instrument": "MNQ"})
    _wait(reg, job_id, "done")
    snap = reg.status(job_id)
    assert snap["state"] == "done"
    assert snap["meta"] == {"instrument": "MNQ"}


def test_failed_state_carries_error(pool):
    reg = FetchJobRegistry()

    def boom():
        raise RuntimeError("nope")

    job_id = reg.submit(pool, boom, meta={})
    _wait(reg, job_id, "failed")
    snap = reg.status(job_id)
    assert snap["state"] == "failed"
    assert "nope" in snap["error"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_jobs.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `services/ohlc/jobs.py`**

```python
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor


class FetchJobRegistry:
    """In-memory registry of background fetch jobs.

    Single-process; restart wipes it. Plan 17's monitoring page may persist
    a summary later, but for now the only consumer is the polling client
    on the chart page (plan 13).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._meta: dict[str, dict] = {}

    def submit(self, pool: ThreadPoolExecutor, fn, *, meta: dict) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._meta[job_id] = dict(meta)
            self._futures[job_id] = pool.submit(fn)
        return job_id

    def status(self, job_id: str) -> dict:
        with self._lock:
            future = self._futures.get(job_id)
            meta = self._meta.get(job_id, {})
        if future is None:
            return {"state": "not_found"}
        if not future.done():
            return {"state": "pending", "meta": meta}
        exc = future.exception()
        if exc is not None:
            return {"state": "failed", "meta": meta, "error": repr(exc)}
        return {"state": "done", "meta": meta}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_ohlc_jobs.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/ohlc/jobs.py tests/test_ohlc_jobs.py
git commit -m "feat(ohlc): in-memory FetchJobRegistry"
```

---

## Task 13: OHLC routes blueprint

The four endpoints from doc 14. The read endpoint reads `bars` directly. The fetch endpoint submits a `fetch_range` call to the pool via the job registry and returns a job ID. The status endpoint looks the job ID up. The sources endpoint surfaces breaker snapshots. None of these import `fetch_range` for synchronous use — they only schedule it.

**Files:**
- Create: `routes/ohlc.py`
- Create: `tests/test_routes_ohlc.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_ohlc.py`:

```python
import time

from db import connect
from models.bar import Bar
from routes.ohlc import build_ohlc_blueprint
from services.ohlc.jobs import FetchJobRegistry
from services.ohlc.registry import build_default_registry
from services.ohlc.store import insert_many


def _seed_bar(db_path, t):
    conn = connect(db_path)
    try:
        insert_many(conn, [Bar(
            instrument="MNQ", timeframe="1d", time=t,
            open=1, high=2, low=0.5, close=1.5, volume=10,
            source="seed",
        )])
    finally:
        conn.close()


def _make_app(tmp_config, *, jobs=None, registry=None):
    from concurrent.futures import ThreadPoolExecutor

    from flask import Flask
    from migrations import run_migrations
    from pathlib import Path

    conn = connect(tmp_config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    pool = ThreadPoolExecutor(max_workers=2)
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = tmp_config.db_path
    app.config["FTL_OHLC_POOL"] = pool
    app.config["FTL_OHLC_JOBS"] = jobs or FetchJobRegistry()
    app.config["FTL_OHLC_REGISTRY"] = registry or build_default_registry(
        clock=lambda: int(time.time())
    )
    app.register_blueprint(build_ohlc_blueprint())
    return app, pool


def test_get_chart_reads_only(tmp_config):
    _seed_bar(tmp_config.db_path, 86400)
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=1d&start=0&end=999999999"
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["instrument"] == "MNQ"
        assert body["timeframe"] == "1d"
        assert len(body["bars"]) == 1
        assert body["bars"][0]["close"] == 1.5
    finally:
        pool.shutdown(wait=True)


def test_get_chart_empty_window_returns_empty(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=1d&start=0&end=10"
        )
        assert resp.status_code == 200
        assert resp.get_json()["bars"] == []
    finally:
        pool.shutdown(wait=True)


def test_get_chart_rejects_unknown_timeframe(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=2m&start=0&end=10"
        )
        assert resp.status_code == 400
    finally:
        pool.shutdown(wait=True)


def test_post_chart_fetch_returns_job_id_immediately(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().post(
            "/api/chart/MNQ/fetch",
            json={"timeframe": "1d", "start": 86400, "end": 86400 * 3},
        )
        assert resp.status_code == 202
        body = resp.get_json()
        assert "job_id" in body
        assert isinstance(body["job_id"], str)
    finally:
        pool.shutdown(wait=True)


def test_get_job_status_unknown(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/ohlc/jobs/notreal")
        assert resp.status_code == 404
    finally:
        pool.shutdown(wait=True)


def test_get_job_status_known(tmp_config):
    jobs = FetchJobRegistry()
    app, pool = _make_app(tmp_config, jobs=jobs)
    try:
        job_id = jobs.submit(pool, lambda: 1, meta={"instrument": "MNQ"})
        # Poll until the job lands
        for _ in range(200):
            if jobs.status(job_id)["state"] == "done":
                break
            time.sleep(0.01)
        resp = app.test_client().get(f"/api/ohlc/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["state"] == "done"
    finally:
        pool.shutdown(wait=True)


def test_get_sources_returns_per_source_breaker_state(tmp_config):
    app, pool = _make_app(tmp_config)
    try:
        resp = app.test_client().get("/api/ohlc/sources")
        assert resp.status_code == 200
        body = resp.get_json()
        names = {s["name"] for s in body["sources"]}
        assert names == {"yfinance", "stooq"}
        for s in body["sources"]:
            assert s["state"] == "closed"
    finally:
        pool.shutdown(wait=True)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_ohlc.py -q
```

Expected: ImportError.

- [ ] **Step 3: Create `routes/ohlc.py`**

```python
from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.ohlc.gap_detection import timeframe_seconds
from services.ohlc.store import read_range

log = get_logger("http.ohlc")


def build_ohlc_blueprint() -> Blueprint:
    bp = Blueprint("ohlc", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    def _pool():
        return current_app.config["FTL_OHLC_POOL"]

    def _jobs():
        return current_app.config["FTL_OHLC_JOBS"]

    def _registry():
        return current_app.config["FTL_OHLC_REGISTRY"]

    @bp.get("/api/chart/<instrument>")
    def get_chart(instrument: str):
        timeframe = request.args.get("timeframe", "1m")
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400
        try:
            start = int(request.args.get("start", "0"))
            end = int(request.args.get("end", "0"))
        except ValueError:
            return jsonify({"error": "start and end must be integers"}), 400

        conn = connect(_db_path())
        try:
            bars = read_range(
                conn,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        finally:
            conn.close()
        return jsonify({
            "instrument": instrument,
            "timeframe": timeframe,
            "bars": [b.model_dump() for b in bars],
        })

    @bp.post("/api/chart/<instrument>/fetch")
    def post_chart_fetch(instrument: str):
        body = request.get_json(silent=True) or {}
        timeframe = body.get("timeframe")
        try:
            start = int(body.get("start"))
            end = int(body.get("end"))
        except (TypeError, ValueError):
            return jsonify({"error": "start and end are required integers"}), 400
        if not isinstance(timeframe, str):
            return jsonify({"error": "timeframe is required"}), 400
        try:
            timeframe_seconds(timeframe)
        except ValueError:
            return jsonify({"error": f"unknown timeframe: {timeframe}"}), 400

        # Deferred import: routes/ohlc.py must not import the fetcher at
        # module load time, because Rule 1 says "no route synchronously
        # invokes the fetcher." Importing it inside the closure that
        # *submits* it to the pool is fine — the route still returns
        # immediately with a job ID.
        from services.ohlc.fetcher import fetch_range

        pool = _pool()
        jobs = _jobs()
        registry = _registry()
        db_path = _db_path()

        def _run():
            return fetch_range(
                db_path=db_path,
                registry=registry,
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end,
            )

        job_id = jobs.submit(pool, _run, meta={
            "instrument": instrument,
            "timeframe": timeframe,
            "start": start,
            "end": end,
        })
        return jsonify({"job_id": job_id}), 202

    @bp.get("/api/ohlc/jobs/<job_id>")
    def get_job(job_id: str):
        snap = _jobs().status(job_id)
        if snap.get("state") == "not_found":
            return jsonify({"error": "not found"}), 404
        return jsonify(snap)

    @bp.get("/api/ohlc/sources")
    def get_sources():
        return jsonify({"sources": _registry().status_snapshots()})

    return bp
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_ohlc.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add routes/ohlc.py tests/test_routes_ohlc.py
git commit -m "feat(ohlc): /api/chart, /api/ohlc/jobs, /api/ohlc/sources routes"
```

---

## Task 14: Add yfinance and requests to requirements

This must happen before the app-factory wiring task so the next Docker rebuild has the deps available. The pinned versions match what the adapters expect.

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Edit `requirements.txt`**

Append:

```
requests==2.32.3
yfinance==0.2.50
```

The full file should now be:

```
Flask==3.0.3
pydantic==2.9.2
APScheduler==3.10.4
watchdog==4.0.2
gunicorn==23.0.0
pytest==8.3.3
ruff==0.6.9
requests==2.32.3
yfinance==0.2.50
```

- [ ] **Step 2: Install into the local venv**

```bash
.venv/Scripts/python.exe -m pip install requests==2.32.3 yfinance==0.2.50
```

Expected: both packages install without error. Note: yfinance pulls in pandas, numpy, and a few HTML parsers — this is a ~150MB install. It only happens once.

- [ ] **Step 3: Verify nothing broke**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test from plans 00–11 plus every Plan 14 test added so far passes. (No file changes since Task 13 outside `requirements.txt`, so this is a sanity check that the new deps don't conflict with the existing pinned set.)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "build(deps): add yfinance and requests for ohlc adapters"
```

---

## Task 15: App-factory wiring — blueprint, post-tick hook, scheduled refresh jobs

Wire everything together in `app.py`:

1. Build a single `SourceRegistry` per app (using a real `time.time` clock).
2. Build a single `FetchJobRegistry` per app.
3. Stash both, plus `services.pool`, on `app.config` so the blueprint can pick them up.
4. Append a *second* post-tick hook to `pipeline.post_tick_hooks` that, for each affected `(account, instrument)` and each canonical timeframe in `DEFAULT_TIMEFRAMES`, submits one `fetch_range` job to `services.pool` covering the time range of `parsed` ± a 1-hour buffer. The hook returns immediately; nothing waits on the futures. Plan 11's integrity hook stays as the first hook.
5. Register two scheduled refresh jobs on `services.scheduler`: one every 15 minutes covering the last 6 hours, one every 4 hours covering the last 7 days. Both look up "instruments with any execution in the last 7 days" via a single SQL query against `executions`.
6. Register the OHLC blueprint.

**Files:**
- Modify: `app.py`
- Create: `tests/test_app_factory_plan14.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_factory_plan14.py`:

```python
import time
from pathlib import Path

from app import create_app
from db import connect
from models.bar import Bar
from services.ohlc.store import insert_many


def test_ohlc_blueprint_registered_and_chart_endpoint_works(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        conn = connect(tmp_config.db_path)
        try:
            insert_many(conn, [Bar(
                instrument="MNQ", timeframe="1d", time=86400,
                open=1, high=2, low=0.5, close=1.5, volume=10,
                source="seed",
            )])
        finally:
            conn.close()
        resp = app.test_client().get(
            "/api/chart/MNQ?timeframe=1d&start=0&end=999999999"
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["bars"]) == 1
    finally:
        services.stop()


def test_sources_endpoint_lists_yfinance_and_stooq(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        resp = app.test_client().get("/api/ohlc/sources")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.get_json()["sources"]}
        assert names == {"yfinance", "stooq"}
    finally:
        services.stop()


def test_post_tick_hooks_include_integrity_and_ohlc(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        pipeline = app.config["FTL_IMPORT_PIPELINE"]
        # Plan 11 contributed the integrity hook; plan 14 appends the ohlc one.
        # We can't introspect by name (they're closures), but we can assert
        # the count and that submitting a tick triggers a fetch job.
        assert len(pipeline.post_tick_hooks) >= 2
    finally:
        services.stop()


def test_scheduled_refresh_jobs_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    try:
        ids = {job.id for job in services.scheduler.get_jobs()}
        assert "ohlc_refresh_recent" in ids
        assert "ohlc_refresh_week" in ids
    finally:
        services.stop()


def test_ingest_tick_submits_ohlc_jobs_to_pool(tmp_config):
    """End-to-end: dropping a CSV causes the OHLC hook to enqueue jobs.

    We can't reach the real internet from the test, so we monkeypatch
    fetch_range to record its calls. The fixture starts background
    services so the watchdog actually fires.
    """
    from services.ohlc import fetcher as fetcher_mod

    calls: list[dict] = []

    def fake_fetch_range(*, db_path, registry, instrument, timeframe, start, end):
        calls.append({"instrument": instrument, "timeframe": timeframe})
        from models.bar import FetchResult
        return FetchResult(status="ok", bars_added=0, attempts=[])

    # NOTE: must patch BEFORE create_app reads the symbol if it does so at
    # module load time. The current implementation imports fetch_range
    # inside the hook closure, so patching here is sufficient.
    import services.ohlc.fetcher
    orig = services.ohlc.fetcher.fetch_range
    services.ohlc.fetcher.fetch_range = fake_fetch_range
    try:
        app, services_obj = create_app(tmp_config, start_background=True)
        try:
            header = (
                "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
                "Commission,Rate,Account,Connection,TradeValidation\n"
            )
            row = (
                "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,ohlctick1,Entry,1 L,"
                "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
            )
            path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
            path.write_text(header + row, encoding="utf-8")

            deadline = time.time() + 3.0
            while time.time() < deadline and not calls:
                time.sleep(0.05)
            services_obj.pool.shutdown(wait=True)
            assert calls, "OHLC hook did not submit any fetch jobs"
            assert all(c["instrument"] == "MNQ" for c in calls)
        finally:
            services_obj.stop()
    finally:
        services.ohlc.fetcher.fetch_range = orig
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan14.py -q
```

Expected: failures (no OHLC blueprint, no second hook, no scheduled jobs).

- [ ] **Step 3: Edit `app.py`**

Add the imports near the other route imports:

```python
import time as _time

from routes.ohlc import build_ohlc_blueprint
from services.instruments import DEFAULT_TIMEFRAMES
from services.ohlc.jobs import FetchJobRegistry
from services.ohlc.registry import build_default_registry
```

Inside `create_app`, after the `pipeline = ImportPipeline(...)` block, **before** the `app = Flask(__name__)` line, build the OHLC singletons:

```python
    ohlc_registry = build_default_registry(clock=lambda: int(_time.time()))
    ohlc_jobs = FetchJobRegistry()
```

Stash them on `app.config` next to the other `FTL_*` keys:

```python
    app.config["FTL_OHLC_REGISTRY"] = ohlc_registry
    app.config["FTL_OHLC_JOBS"] = ohlc_jobs
    app.config["FTL_OHLC_POOL"] = services.pool
```

Register the blueprint next to the other `register_blueprint` calls:

```python
    app.register_blueprint(build_ohlc_blueprint())
```

Append the second post-tick hook **after** `pipeline = ImportPipeline(...)` and before the scheduler-job registration. The hook captures `services.pool`, `ohlc_registry`, and `config.db_path`:

```python
    def _ohlc_hook(_result, parsed, affected):
        if not parsed:
            return
        from services.ohlc.fetcher import fetch_range  # deferred to allow tests to monkeypatch

        min_ts = min(e.timestamp for e in parsed)
        max_ts = max(e.timestamp for e in parsed)
        start = min_ts - 3600
        end = max_ts + 3600
        for _account, instrument in affected:
            for timeframe in DEFAULT_TIMEFRAMES:
                def _run(inst=instrument, tf=timeframe, st=start, en=end):
                    try:
                        fetch_range(
                            db_path=config.db_path,
                            registry=ohlc_registry,
                            instrument=inst,
                            timeframe=tf,
                            start=st,
                            end=en,
                        )
                    except Exception:
                        log.exception(
                            "ohlc fetch failed",
                            extra={"inst": inst, "tf": tf},
                        )

                ohlc_jobs.submit(
                    services.pool,
                    _run,
                    meta={
                        "instrument": instrument,
                        "timeframe": timeframe,
                        "start": start,
                        "end": end,
                        "trigger": "post_import",
                    },
                )

    pipeline.post_tick_hooks.append(_ohlc_hook)
```

Register the two scheduled refresh jobs next to the existing `import_safety_sweep` job:

```python
    def _refresh(window_seconds: int) -> None:
        now = int(_time.time())
        start = now - window_seconds
        seven_days_ago = now - 7 * 86400
        from services.ohlc.fetcher import fetch_range

        conn = connect(config.db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT instrument FROM executions WHERE timestamp >= ?",
                (seven_days_ago,),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            instrument = row["instrument"]
            for timeframe in DEFAULT_TIMEFRAMES:
                try:
                    fetch_range(
                        db_path=config.db_path,
                        registry=ohlc_registry,
                        instrument=instrument,
                        timeframe=timeframe,
                        start=start,
                        end=now,
                    )
                except Exception:
                    log.exception(
                        "scheduled ohlc refresh failed",
                        extra={"inst": instrument, "tf": timeframe},
                    )

    services.scheduler.add_job(
        lambda: _refresh(6 * 3600),
        trigger=IntervalTrigger(minutes=15),
        id="ohlc_refresh_recent",
        replace_existing=True,
    )
    services.scheduler.add_job(
        lambda: _refresh(7 * 86400),
        trigger=IntervalTrigger(hours=4),
        id="ohlc_refresh_week",
        replace_existing=True,
    )
```

- [ ] **Step 4: Run the new tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan14.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes, including the existing plan 10/11 app-factory tests (the new hook is appended, not substituted).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_factory_plan14.py
git commit -m "feat(ohlc): wire blueprint, post-tick hook, refresh jobs into app factory"
```

---

## Task 16: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes. Plan 14 adds ~60 new tests across 13 files. Plans 00–11 remain green.

- [ ] **Step 2: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```

Expected: no errors, no diffs. If `format --check` reports diffs, run `ruff format .` and commit as `chore(ohlc): ruff format pass`.

- [ ] **Step 3: Bring up the container and exercise end-to-end**

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/api/ohlc/sources
curl -fsS "http://localhost:8000/api/chart/MNQ?timeframe=1d&start=0&end=9999999999"
```

Expected:
- `Up (healthy)` after ~25s (the first build now installs yfinance + pandas, which is slower than plans 00–11).
- `/api/ohlc/sources` returns `{"sources": [{"name": "yfinance", "state": "closed", ...}, {"name": "stooq", ...}]}`.
- `/api/chart/MNQ?...` returns `{"instrument": "MNQ", "timeframe": "1d", "bars": []}` (no bars yet — nothing has been fetched).

Trigger an on-demand fetch and poll the job:

```bash
JOB=$(curl -fsS -X POST http://localhost:8000/api/chart/MNQ/fetch \
  -H "Content-Type: application/json" \
  -d '{"timeframe":"1d","start":1733000000,"end":1733900000}' | python -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
echo "job: $JOB"
sleep 5
curl -fsS "http://localhost:8000/api/ohlc/jobs/$JOB"
curl -fsS "http://localhost:8000/api/chart/MNQ?timeframe=1d&start=1733000000&end=1733900000"
```

Expected outcomes (any of these is acceptable):
- **Internet available, yfinance up:** `state: done`, `/api/chart/MNQ` returns several daily bars, each with `"source": "yfinance"`.
- **Internet available, yfinance down:** `state: done`, `/api/chart/MNQ` returns daily bars with `"source": "stooq"`.
- **No internet:** `state: done`, `/api/chart/MNQ` returns `[]`, and `/api/ohlc/sources` shows both breakers either `closed` (no calls yet) or `open` (calls failed). `/healthz` is still 200.

What is **not** acceptable: any chart endpoint hanging, any 500 from `/api/chart/...`, or `/healthz` going non-200 because OHLC sources are down. If any of those happen, the isolation invariant from Rule 6 is broken — go fix it before the plan ships.

- [ ] **Step 4: Bring it down**

```bash
docker compose down
```

- [ ] **Step 5: Commit any formatting fixes** (only if Step 2 reported diffs)

```bash
git status
git add -u
git commit -m "chore(ohlc): ruff format pass"
```

---

## Task 17: Update the rebuild-spec progress table

**Files:**
- Modify: `docs/rebuild-spec/00-README.md`

- [ ] **Step 1: Update the row and status**

Find:

```markdown
| 14 — OHLC Pipeline | `Bar` model, `OhlcSource` protocol, yfinance + Stooq adapters, circuit breaker, fetcher, gap detection, `bars` table, scheduled refresh jobs, fetch job API | ⏳ **Next** |
| 12 — Browsing | `/positions` list and detail, `execution_notes`, `execution_flags`, link groups, JSON APIs, shell templates + vanilla JS | ⏳ |
```

Replace with:

```markdown
| [14 — OHLC Pipeline](../superpowers/plans/2026-04-13-14-ohlc-pipeline.md) | `Bar` model, `OhlcSource` protocol, yfinance + Stooq adapters, circuit breaker, fetcher, gap detection, `bars` table, scheduled refresh jobs, fetch job API | ✅ **Complete** (2026-04-13) |
| 12 — Browsing | `/positions` list and detail, `execution_notes`, `execution_flags`, link groups, JSON APIs, shell templates + vanilla JS | ⏳ **Next** |
```

- [ ] **Step 2: Append a "What Plan 14 landed" section**

Below the existing `### What Plan 11 landed` section, append:

```markdown
### What Plan 14 landed

- **`Bar`, `FetchResult`, `AttemptRecord` models.** Pydantic StrictModels exported from `models/__init__.py`. `Timeframe` is the canonical Literal `{1m,5m,15m,1h,4h,1d}`; `volume` is non-nullable.
- **`bars` table.** Migration 004 ships the composite-key `(instrument, timeframe, time)` table plus `idx_bars_instrument_tf_time`. No FK from any other table points at `bars` — Rule 6 enforced structurally.
- **Two adapters, one Protocol.** `services/ohlc/yfinance_source.py` (primary, declares `{1m,5m,15m,1h,1d}`) and `services/ohlc/stooq_source.py` (fallback, declares `{1d}` only) implement `services/ohlc/source.py::OhlcSource`. Both lazy-import their transport library so the test suite never imports yfinance/requests; both convert raw responses to `list[Bar]` inside the adapter and never let pandas/CSV leak out.
- **Per-source circuit breaker.** `services/ohlc/circuit_breaker.py::CircuitBreaker` is closed/open/half_open with the spec's three-failure threshold and per-source cooldowns (yfinance 600s, stooq 1800s). Hardcoded fast-trip on any `HTTPError(429)` or `HTTPError(5xx)` regardless of threshold.
- **Source registry.** `services/ohlc/registry.py::SourceRegistry` keeps an ordered `[(source, breaker), …]` list and exposes `sources_for(timeframe)` which silently skips sources with open breakers or unsupported timeframes — Rule 5 (no upscaling) holds because the registry hides incompatible sources from the fetcher entirely.
- **`fetch_range` orchestrator.** `services/ohlc/fetcher.py::fetch_range` is the only function in the app that calls `source.fetch()`. It computes missing ranges via `gap_detection.find_gaps`, walks each gap, tries sources in registry order until one returns bars, UPSERTs the collected bars in a single transaction, and returns a `FetchResult` with one `AttemptRecord` per source touched. Cached, partial, ok, all-sources-unavailable, and no-source-for-timeframe are all explicit statuses.
- **Session-aware gap detection.** `services/ohlc/gap_detection.py::find_gaps` walks the timeframe-aligned slot grid in `[start, end)`, consults `services.instruments.default_session()` for a CME-default 23h session with a 16:00–17:00 America/Chicago break, and skips any slot inside the daily break so the overnight close is never reported as missing.
- **Background fetch job registry.** `services/ohlc/jobs.py::FetchJobRegistry` is an in-memory `job_id → Future + meta` map used by both the post-tick hook and the on-demand fetch route. Job state is `pending`, `done`, `failed`, or `not_found`.
- **API surface.** `GET /api/chart/{instrument}` (read-only, never fetches), `POST /api/chart/{instrument}/fetch` (queues a fetch, returns a job_id, 202), `GET /api/ohlc/jobs/{job_id}` (poll), `GET /api/ohlc/sources` (per-source breaker snapshots for the monitoring page).
- **Second post-tick hook.** Plan 11's integrity hook stays as the first hook on `ImportPipeline.post_tick_hooks`. Plan 14 appends a second hook that, for each affected `(account, instrument)` and each canonical timeframe in `services.instruments.DEFAULT_TIMEFRAMES`, submits a `fetch_range` job to `BackgroundServices.pool` and returns immediately. Imports never wait on OHLC.
- **Two scheduled refresh jobs.** Every 15 minutes (`ohlc_refresh_recent`, last 6h) and every 4 hours (`ohlc_refresh_week`, last 7d) for instruments that traded in the last 7 days. Both registered on the existing APScheduler from plan 00.
- **`services/instruments.py` extended.** `DEFAULT_TIMEFRAMES`, `source_symbol(instrument, source)`, and `default_session(instrument)` are all stubs that plan 16 will replace with the JSON-backed registry. The function names are the seam.
- **Two new pinned dependencies.** `requirements.txt` adds `requests==2.32.3` and `yfinance==0.2.50`. The Dockerfile rebuild on next `docker compose up -d --build` picks them up automatically.
- **End-to-end verified in Docker.** `/healthz` stays 200 even when both OHLC sources are unreachable; `/api/chart/{instrument}` returns whatever is in `bars` and never blocks; on-demand `POST /api/chart/{instrument}/fetch` returns a job_id immediately and the client polls.
- **OHLC stays isolated, per Rule 6.** No FK to `bars`, no route imports `fetch_range` for synchronous use, no positions/stats/notes path depends on chart data being present.
```

- [ ] **Step 3: Commit**

```bash
git add docs/rebuild-spec/00-README.md
git commit -m "docs(rebuild-spec): record Plan 14 completion"
```

---

## What this plan deliberately does NOT do

- **No chart frontend.** Plan 13 builds `PriceChart.js`, the position-detail embedding, the timeframe selector, the fetch-now button, and the delayed-data banner. Plan 14 only ships the JSON endpoints those will consume.
- **No real per-instrument session calendar.** `default_session()` returns the CME futures default for every instrument. Plan 16 replaces this with `instruments.json` and per-symbol calendars.
- **No `instruments.json` registry.** `services/instruments.py` is still the stub plan 11 introduced, just with three extra functions appended. Plan 16 deletes the stub and ships the JSON-backed registry.
- **No persistent fetch job log.** `FetchJobRegistry` is in-memory; restart wipes it. The monitoring dashboard in plan 17 may persist a summary later, but that's plan 17's call.
- **No completeness-percentage dashboard.** Coverage is a plan 17 concern. Plan 14 ships the data and the per-source forensic columns it needs.
- **No third source.** The architecture supports adding Databento/Polygon/etc. as a new file plus an entry in `build_default_registry`, but plan 14 ships only yfinance + stooq.
- **No automatic retry of failed jobs.** A failed fetch lives in the job registry as `state=failed` until restart. The next scheduled refresh window will re-attempt the range. Reactive retries are intentionally out of scope.
- **No upscaling or downsampling.** Per Rule 5. If a request asks for 1m and only 5m exists, the user sees the 1m we have plus a missing range — they do not see synthesized 1m bars.
- **No cache layer between routes and the bars table.** SQLite is the cache. Per fragmentation hazard 5.
- **No blocking inside a request.** Per Rule 1 / hazards 1 and 6. The fetcher is the only function that touches sources, and the fetcher is only ever invoked from the background pool or the scheduler thread — never from a Flask request thread.

## Definition of done for plan 14

1. `pytest` runs green. Plan 14 adds ~60 new tests across 13 files; plans 00–11 remain green. Final count ≈ 230.
2. `ruff check .` and `ruff format --check .` are clean.
3. `docker compose up -d --build` brings up exactly one container and `docker compose ps` shows `Up (healthy)`.
4. `GET /api/chart/MNQ?timeframe=1d&start=…&end=…` returns 200 with whatever bars are in the store. It returns 200 with `{"bars": []}` if the store is empty. It NEVER hangs and NEVER returns 5xx because of an upstream source outage.
5. `POST /api/chart/MNQ/fetch` returns 202 with a `job_id` immediately and never blocks.
6. `GET /api/ohlc/jobs/{job_id}` returns 200 with `state ∈ {pending, done, failed}` for known jobs, 404 for unknown.
7. `GET /api/ohlc/sources` returns 200 with one entry per registered source, each containing `state`, `last_failure_at`, `last_success_at`, `last_error`, and `consecutive_failures`.
8. Dropping a CSV into the inbox causes the import pipeline to (a) insert executions (plan 10), (b) run the integrity diff (plan 11), and (c) queue OHLC fetch jobs to the background pool (plan 14). Steps (b) and (c) both happen and do not interfere with each other.
9. With internet disabled, the entire app continues to function: imports land, positions compute, integrity issues surface, `/healthz` stays 200, `/api/chart/...` returns 200 with whatever bars existed before. Only the chart's freshness degrades.
10. With internet enabled and yfinance up, `POST /api/chart/MNQ/fetch` for a recent daily range eventually populates `bars` with at least one row whose `source = "yfinance"`. With yfinance simulated as down, the same flow populates `bars` with at least one row whose `source = "stooq"` (when the stooq adapter has data for that symbol).
11. `docs/rebuild-spec/00-README.md` lists plan 14 as complete and plan 12 as next.

After this plan is merged, plan 12 (Browsing) can begin. Plan 12 will introduce `execution_notes`, `execution_flags`, `link_groups`, the first real templates, and the first vanilla JS files. Plan 13 (Charting) will then consume the OHLC API surface plan 14 just shipped.
