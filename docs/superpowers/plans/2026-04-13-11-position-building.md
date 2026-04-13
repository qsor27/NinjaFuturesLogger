# Position Building Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group stored executions into derived logical positions via a pure `build_positions` function, cross-check them against the exporter's `Position` column to produce integrity issues, persist issues with a diff-on-every-import lifecycle, and surface both positions and issues through the JSON API. No `positions` table, no position IDs, no rebuild lifecycle.

**Architecture:** Two small service modules:

- `services/positions.py` — `build_positions(executions) -> (list[Position], list[IntegrityIssue])`, pure function. Walks sorted executions; opens a position when running quantity leaves zero; closes when it returns to zero. Direction-reversing fills (long→short or short→long in a single fill) are split in-memory into `#close`/`#open` sub-fills with proportional commission. No DB access, no globals, no I/O.
- `services/integrity.py` — `IntegrityValidator` produces `IntegrityIssue` records by comparing computed running quantity to the CSV's `Position` column on each execution. `run_integrity_diff(conn, account, instrument)` is the post-tick entry point: it loads executions for the pair, calls `build_positions`, diffs the returned issue list against the stored `integrity_issues` table, inserts new issues, auto-resolves stale ones, and leaves ignored rows alone.

`run_integrity_diff` is registered on `ImportPipeline.post_tick_hooks` in the app factory so every successful tick triggers one diff per affected `(account, instrument)` pair. Reads happen on the calling thread — the diff is cheap (sub-millisecond for typical data) and the thread pool is reserved for plan 14's OHLC fetches. A `positions_service` module provides the read-side query helpers that the `/api/positions` routes call: load executions for a filter, run `build_positions`, return the list. Positions are never cached — rendering is fast enough.

**Tech Stack:** Python 3.11, Pydantic v2, SQLite (stdlib `sqlite3`), pytest, ruff. No new third-party deps. Uses the existing `ImportPipeline.post_tick_hooks` seam from plan 10.

## Spec references

- `docs/rebuild-spec/01-mission-and-principles.md` — The Six Rules. Rule 1 (single source of truth: executions; no positions table, ever), Rule 4 (typed contracts — Position/IntegrityIssue are Pydantic models), Rule 6 (build_positions is a pure function testable without DB).
- `docs/rebuild-spec/02-glossary.md` — Execution, Position, Side (normalized), position side (Long/Short), quantity flow, direction reversal, Entry/Exit, NT ExecutionId. Read before writing any code in this plan.
- `docs/rebuild-spec/11-position-building.md` — The full feature spec. This plan is its implementation.
- `docs/rebuild-spec/10-import-pipeline.md` — Acceptance criterion 7 requires the importer to run the integrity diff after every tick. Plan 11 is where that AC is satisfied; the hook seam was shipped in plan 10.
- `docs/superpowers/plans/2026-04-13-10-import-pipeline.md` — File layout conventions, commit message style, test-fixture patterns (`migrated_db`), `ImportPipeline.post_tick_hooks` shape.

## Load-bearing rules from the spec

Four rules from doc 11 drive most of this plan. If you find yourself violating any of them, stop:

1. **No `positions` table.** Positions are computed on every read. If a test or route asks "is there a positions table?", the answer is no. The escape hatch for performance (an in-memory memoization cache keyed by `(account, instrument, max_execution_time)`) is deliberately not in this plan — build first, measure, add only if profiling shows it's needed.
2. **Position identity is `(account, instrument, entry_execution_id)`.** Never an auto-increment integer. The `entry_execution_id` carries the `#open` suffix if the opening fill was synthesized from a reversal.
3. **User metadata attaches to execution IDs, never to positions.** Plan 11 must not add any FK pointing at positions. `integrity_issues.execution_id` is a TEXT column with no FK to `executions` — that's deliberate per doc 11 so forensic records survive rollback. User notes / flags / custom fields are plans 12 and 16 and will FK to `executions.nt_execution_id` via the plan 10 unique index.
4. **Direction reversal sub-fills are in-memory only.** Never insert a row with a `#close` or `#open` suffix into the `executions` table. Those suffixes only appear in `integrity_issues.execution_id` when an issue is raised against a synthesized fill. If you find yourself about to SQL-insert `"abc#open"`, stop.

## File layout this plan creates or modifies

```
/
├── migrations/
│   └── 003_integrity_issues.sql    # NEW: integrity_issues table + partial index
├── models/
│   ├── position.py                 # NEW: Position, IntegrityIssue, Fill
│   └── __init__.py                 # MODIFY: export Position, IntegrityIssue
├── services/
│   ├── instruments.py              # NEW: get_multiplier stub for plan 16
│   ├── positions.py                # NEW: build_positions, make_position, synthesize_fill, sign
│   ├── integrity.py                # NEW: IntegrityValidator, run_integrity_diff
│   ├── integrity_db.py             # NEW: SQL helpers for integrity_issues
│   └── positions_service.py        # NEW: load-executions + build_positions query layer
├── routes/
│   ├── positions.py                # NEW: /api/positions + /api/integrity-issues blueprint
│   └── __init__.py                 # unchanged
├── app.py                          # MODIFY: register integrity hook, register blueprint
└── tests/
    ├── test_migrations_003.py      # NEW
    ├── test_models_position.py     # NEW
    ├── test_instruments.py         # NEW
    ├── test_positions_long_short.py        # NEW — build_positions: round-trip long/short, multi
    ├── test_positions_weighted_pnl.py      # NEW — weighted-avg prices, points/dollars P&L
    ├── test_positions_open.py      # NEW — open position at end
    ├── test_positions_reversal.py  # NEW — direction reversal splitter
    ├── test_positions_sort.py      # NEW — sort stability and ordering
    ├── test_integrity_validator.py # NEW — position_after cross-check
    ├── test_integrity_db.py        # NEW — upsert, resolve, ignore
    ├── test_integrity_diff.py      # NEW — run_integrity_diff composer
    ├── test_positions_service.py   # NEW — query layer
    ├── test_routes_positions.py    # NEW — /api/positions
    ├── test_routes_integrity.py    # NEW — /api/integrity-issues
    └── test_app_factory_plan11.py  # NEW — hook registered, end-to-end
```

---

## Task 1: Migration 003 — integrity_issues

**Files:**
- Create: `migrations/003_integrity_issues.sql`
- Create: `tests/test_migrations_003.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrations_003.py`:

```python
from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_003_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "003_integrity_issues" in applied_versions(conn)
    finally:
        conn.close()


def test_integrity_issues_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(integrity_issues)").fetchall()}
        assert cols == {
            "issue_id", "account", "instrument", "execution_id",
            "severity", "type", "description",
            "detected_at", "last_seen_at",
            "resolved_at", "resolved_by", "resolution_note",
            "ignored", "ignore_note",
        }
    finally:
        conn.close()


def test_integrity_issues_unique_key(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        insert = (
            "INSERT INTO integrity_issues "
            "(account, instrument, execution_id, severity, type, description,"
            " detected_at, last_seen_at, ignored) "
            "VALUES (?,?,?,?,?,?,?,?,0)"
        )
        row = ("Sim101", "MNQ", "abc", "high", "position_column_mismatch", "x", 1, 1)
        conn.execute(insert, row)
        try:
            conn.execute(insert, row)
            raised = False
        except Exception:
            raised = True
        assert raised
    finally:
        conn.close()


def test_integrity_open_partial_index_exists(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='integrity_issues'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert "idx_integrity_open" in names
    finally:
        conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_003.py -q
```

Expected: failures because `integrity_issues` does not exist.

- [ ] **Step 3: Write `migrations/003_integrity_issues.sql`**

```sql
CREATE TABLE integrity_issues (
  issue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  account         TEXT NOT NULL,
  instrument      TEXT NOT NULL,
  execution_id    TEXT NOT NULL,
  severity        TEXT NOT NULL CHECK(severity IN ('low','medium','high')),
  type            TEXT NOT NULL,
  description     TEXT NOT NULL,
  detected_at     INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,
  resolved_at     INTEGER,
  resolved_by     TEXT CHECK(resolved_by IN ('system','user') OR resolved_by IS NULL),
  resolution_note TEXT,
  ignored         INTEGER NOT NULL DEFAULT 0,
  ignore_note     TEXT,
  UNIQUE (account, instrument, execution_id, type)
);

CREATE INDEX idx_integrity_open
  ON integrity_issues(account, instrument, severity)
  WHERE resolved_at IS NULL AND ignored = 0;
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_003.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/003_integrity_issues.sql tests/test_migrations_003.py
git commit -m "feat(positions): migration 003 — integrity_issues table"
```

---

## Task 2: Models — Position, IntegrityIssue, Fill

`Fill` is an internal dataclass used only inside `services/positions.py`. `Position` and `IntegrityIssue` are StrictModels exposed via the API.

**Files:**
- Create: `models/position.py`
- Modify: `models/__init__.py`
- Create: `tests/test_models_position.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_position.py`:

```python
import pytest
from pydantic import ValidationError

from models.position import IntegrityIssue, Position


def _pos_kwargs(**overrides):
    base = dict(
        account="Sim101",
        instrument="MNQ",
        entry_execution_id="abc123",
        side="Long",
        entry_time=1_700_000_000,
        exit_time=1_700_000_300,
        quantity=3,
        entry_price=4237.75,
        exit_price=4240.00,
        points_pnl=2.25,
        dollars_pnl=13.50,
        commission=5.00,
        duration_minutes=5.0,
        execution_ids=["abc123", "abc124"],
    )
    base.update(overrides)
    return base


def test_position_accepts_valid_long():
    p = Position(**_pos_kwargs())
    assert p.side == "Long"
    assert p.quantity == 3
    assert p.execution_ids == ["abc123", "abc124"]


def test_position_rejects_invalid_side():
    with pytest.raises(ValidationError):
        Position(**_pos_kwargs(side="Buy"))


def test_position_open_fields_nullable():
    p = Position(**_pos_kwargs(
        exit_time=None, exit_price=None,
        points_pnl=None, dollars_pnl=None, duration_minutes=None,
    ))
    assert p.exit_time is None
    assert p.points_pnl is None


def test_position_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Position(**_pos_kwargs(bogus=1))


def test_integrity_issue_accepts_valid():
    issue = IntegrityIssue(
        account="Sim101",
        instrument="MNQ",
        execution_id="abc123",
        severity="high",
        type="position_column_mismatch",
        description="builder saw 3 L, CSV said 2 L",
    )
    assert issue.severity == "high"


def test_integrity_issue_rejects_bad_severity():
    with pytest.raises(ValidationError):
        IntegrityIssue(
            account="Sim101",
            instrument="MNQ",
            execution_id="abc123",
            severity="huge",
            type="x",
            description="y",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_position.py -q
```

Expected: `ModuleNotFoundError: No module named 'models.position'`.

- [ ] **Step 3: Implement `models/position.py`**

```python
from dataclasses import dataclass
from typing import Literal

from models.base import StrictModel

PositionSide = Literal["Long", "Short"]
Severity = Literal["low", "medium", "high"]


class Position(StrictModel):
    account: str
    instrument: str
    entry_execution_id: str
    side: PositionSide
    entry_time: int
    exit_time: int | None
    quantity: int
    entry_price: float
    exit_price: float | None
    points_pnl: float | None
    dollars_pnl: float | None
    commission: float
    duration_minutes: float | None
    execution_ids: list[str]


class IntegrityIssue(StrictModel):
    account: str
    instrument: str
    execution_id: str
    severity: Severity
    type: str
    description: str


@dataclass
class Fill:
    """Internal walk-state fill. Never persisted.

    A Fill either wraps one real Execution 1:1, or is a synthesized sub-fill
    produced by the reversal splitter. The `execution_id` carries the
    `#close` / `#open` suffix for synthesized fills.
    """

    execution_id: str
    account: str
    instrument: str
    timestamp: int
    side: Literal["Buy", "Sell"]
    quantity: int
    price: float
    commission: float
    entry_exit: Literal["Entry", "Exit"]
```

- [ ] **Step 4: Update `models/__init__.py`**

Replace with:

```python
from models.base import StrictModel
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
]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_position.py -q
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add models/position.py models/__init__.py tests/test_models_position.py
git commit -m "feat(positions): Position, IntegrityIssue, Fill models"
```

---

## Task 3: Instrument multiplier stub

Plan 16 will ship `instruments.json` with multipliers and tick sizes. Plan 11 needs a one-function stub so `dollars_pnl = points_pnl × multiplier(instrument)` works today. Base-symbol extraction (`"MNQ SEP25"` → `"MNQ"`) happens here too.

**Files:**
- Create: `services/instruments.py`
- Create: `tests/test_instruments.py`

- [ ] **Step 1: Write the failing test**

```python
from services.instruments import base_symbol, get_multiplier


def test_get_multiplier_known_symbols():
    assert get_multiplier("MNQ") == 2.0
    assert get_multiplier("ES") == 50.0
    assert get_multiplier("NQ") == 20.0
    assert get_multiplier("MES") == 5.0
    assert get_multiplier("CL") == 1000.0
    assert get_multiplier("GC") == 100.0


def test_get_multiplier_handles_contract_suffix():
    assert get_multiplier("MNQ SEP25") == 2.0
    assert get_multiplier("ES DEC25") == 50.0


def test_get_multiplier_unknown_symbol_returns_one():
    assert get_multiplier("ZZZZ") == 1.0


def test_base_symbol_strips_suffix():
    assert base_symbol("MNQ SEP25") == "MNQ"
    assert base_symbol("ES DEC25") == "ES"
    assert base_symbol("MNQ") == "MNQ"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_instruments.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.instruments'`.

- [ ] **Step 3: Implement `services/instruments.py`**

```python
"""Instrument metadata stub.

Plan 16 replaces this with a JSON-backed registry. Until then, this module
holds the multipliers plan 11 needs for dollars_pnl. When you migrate to
the JSON registry, delete this file and update the imports in
services/positions.py.
"""

_MULTIPLIERS: dict[str, float] = {
    # CME equity index futures
    "ES": 50.0, "MES": 5.0,
    "NQ": 20.0, "MNQ": 2.0,
    "RTY": 50.0, "M2K": 5.0,
    "YM": 5.0, "MYM": 0.50,
    # CME energies
    "CL": 1000.0, "MCL": 100.0,
    "NG": 10000.0, "QG": 2500.0,
    "RB": 42000.0,
    "HO": 42000.0,
    # CME metals
    "GC": 100.0, "MGC": 10.0,
    "SI": 5000.0, "SIL": 1000.0,
    "HG": 25000.0, "MHG": 2500.0,
    # CME interest rates (partial)
    "ZN": 1000.0, "ZB": 1000.0, "ZF": 1000.0, "ZT": 2000.0,
    # CME FX
    "6E": 125000.0, "6B": 62500.0, "6J": 12500000.0,
}


def base_symbol(instrument: str) -> str:
    """Strip any trailing contract-month suffix like ' SEP25'."""
    return instrument.split(" ", 1)[0]


def get_multiplier(instrument: str) -> float:
    """Dollars per point for the instrument. Unknown symbols return 1.0."""
    return _MULTIPLIERS.get(base_symbol(instrument), 1.0)
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_instruments.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/instruments.py tests/test_instruments.py
git commit -m "feat(positions): instrument multiplier stub (plan 16 replaces this)"
```

---

## Task 4: `build_positions` — long and short round-trips, multi-position sequences

This task lands the core algorithm: sort → walk → open on zero-cross-out → close on zero-cross-in → emit. Reversal and open-at-end are separate tasks.

**Files:**
- Create: `services/positions.py`
- Create: `tests/test_positions_long_short.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_positions_long_short.py`:

```python
from models.execution import Execution
from services.positions import build_positions


def _ex(
    eid: str,
    side: str,
    qty: int,
    price: float,
    ts: int,
    *,
    account: str = "Sim101",
    instrument: str = "MNQ",
    entry_exit: str = "Entry",
    position_after: str | None = "1 L",
    commission: float = 0.0,
) -> Execution:
    return Execution(
        nt_execution_id=eid,
        account=account,
        instrument=instrument,
        timestamp=ts,
        side=side,
        original_action=side,
        quantity=qty,
        price=price,
        commission=commission,
        entry_exit=entry_exit,
        position_after=position_after,
        source_order_id=None,
        source_filename="f.csv",
        imported_at=ts,
    )


def test_simple_long_round_trip():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Long"
    assert p.entry_execution_id == "e1"
    assert p.quantity == 1
    assert p.entry_price == 4000.0
    assert p.exit_price == 4010.0
    assert p.entry_time == 100
    assert p.exit_time == 200
    assert p.execution_ids == ["e1", "e2"]


def test_simple_short_round_trip():
    exs = [
        _ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S"),
        _ex("e2", "Buy", 1, 4090.0, 200, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Short"
    assert p.entry_execution_id == "e1"
    assert p.quantity == 1
    assert p.entry_price == 4100.0
    assert p.exit_price == 4090.0


def test_two_sequential_long_positions():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Buy", 1, 4020.0, 300, position_after="1 L"),
        _ex("e4", "Sell", 1, 4030.0, 400, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].entry_execution_id == "e1"
    assert positions[1].entry_execution_id == "e3"


def test_mixed_long_then_short_positions():
    exs = [
        _ex("e1", "Buy", 2, 4000.0, 100, position_after="2 L"),
        _ex("e2", "Sell", 2, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Sell", 1, 4100.0, 300, position_after="1 S"),
        _ex("e4", "Buy", 1, 4095.0, 400, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].side == "Long"
    assert positions[1].side == "Short"


def test_multi_fill_long_position_groups_correctly():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Buy", 2, 4002.0, 200, position_after="3 L"),
        _ex("e3", "Sell", 3, 4010.0, 300, entry_exit="Exit", position_after="-"),
    ]
    positions, _issues = build_positions(exs)
    assert len(positions) == 1
    assert positions[0].execution_ids == ["e1", "e2", "e3"]
    assert positions[0].quantity == 3
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_long_short.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.positions'`.

- [ ] **Step 3: Implement `services/positions.py`**

```python
from collections.abc import Sequence

from models.execution import Execution
from models.position import Fill, IntegrityIssue, Position
from services.instruments import get_multiplier


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _fill_from(ex: Execution) -> Fill:
    return Fill(
        execution_id=ex.nt_execution_id,
        account=ex.account,
        instrument=ex.instrument,
        timestamp=ex.timestamp,
        side=ex.side,
        quantity=ex.quantity,
        price=ex.price,
        commission=ex.commission,
        entry_exit=ex.entry_exit,
    )


def _make_position(fills: list[Fill], *, is_open: bool) -> Position:
    first = fills[0]
    side = "Long" if first.side == "Buy" else "Short"

    if side == "Long":
        entry_fills = [f for f in fills if f.side == "Buy"]
        exit_fills = [f for f in fills if f.side == "Sell"]
    else:
        entry_fills = [f for f in fills if f.side == "Sell"]
        exit_fills = [f for f in fills if f.side == "Buy"]

    entry_qty_total = sum(f.quantity for f in entry_fills)
    entry_price = (
        sum(f.price * f.quantity for f in entry_fills) / entry_qty_total
        if entry_qty_total
        else 0.0
    )

    if is_open or not exit_fills:
        exit_time: int | None = None
        exit_price: float | None = None
        points_pnl: float | None = None
        dollars_pnl: float | None = None
        duration_minutes: float | None = None
    else:
        exit_qty_total = sum(f.quantity for f in exit_fills)
        exit_price = (
            sum(f.price * f.quantity for f in exit_fills) / exit_qty_total
            if exit_qty_total
            else 0.0
        )
        exit_time = fills[-1].timestamp
        signed_qty = entry_qty_total if side == "Long" else -entry_qty_total
        points_pnl = (exit_price - entry_price) * signed_qty
        dollars_pnl = points_pnl * get_multiplier(first.instrument)
        duration_minutes = (exit_time - first.timestamp) / 60.0

    return Position(
        account=first.account,
        instrument=first.instrument,
        entry_execution_id=entry_fills[0].execution_id,
        side=side,
        entry_time=first.timestamp,
        exit_time=exit_time,
        quantity=entry_qty_total,
        entry_price=entry_price,
        exit_price=exit_price,
        points_pnl=points_pnl,
        dollars_pnl=dollars_pnl,
        commission=sum(f.commission for f in fills),
        duration_minutes=duration_minutes,
        execution_ids=[f.execution_id for f in fills],
    )


def build_positions(
    executions: Sequence[Execution],
) -> tuple[list[Position], list[IntegrityIssue]]:
    """Pure function: walk executions and emit positions.

    Direction-reversing fills and sort stability are handled in later tasks.
    """
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []
    current: list[Fill] = []
    running_qty = 0

    for ex in executions:
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        new_qty = running_qty + signed
        current.append(_fill_from(ex))
        running_qty = new_qty

        if running_qty == 0:
            positions.append(_make_position(current, is_open=False))
            current = []

    return positions, issues
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_long_short.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/positions.py tests/test_positions_long_short.py
git commit -m "feat(positions): build_positions core — long/short round-trips"
```

---

## Task 5: `build_positions` — weighted-average prices and P&L

The core `_make_position` helper already computes weighted averages and P&L. This task adds focused tests to lock that behavior down and catch regressions when the reversal splitter lands next.

**Files:**
- Create: `tests/test_positions_weighted_pnl.py`

- [ ] **Step 1: Write the test**

```python
import pytest

from models.execution import Execution
from services.positions import build_positions


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry",
        instrument="MNQ", position_after="1 L", commission=0.0):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument=instrument,
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=commission, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_weighted_entry_price_across_multiple_buys():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Buy", 3, 4004.0, 150, position_after="4 L"),
        _ex("e3", "Sell", 4, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    # (1*4000 + 3*4004) / 4 = 4003
    assert p[0].entry_price == pytest.approx(4003.0)
    assert p[0].exit_price == pytest.approx(4010.0)
    assert p[0].quantity == 4


def test_weighted_exit_price_across_multiple_sells():
    exs = [
        _ex("e1", "Buy", 4, 4000.0, 100, position_after="4 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="3 L"),
        _ex("e3", "Sell", 3, 4020.0, 300, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    # (1*4010 + 3*4020) / 4 = 4017.5
    assert p[0].exit_price == pytest.approx(4017.5)


def test_long_points_and_dollars_pnl_uses_multiplier():
    # MNQ multiplier is 2.0
    exs = [
        _ex("e1", "Buy", 2, 4000.0, 100, position_after="2 L"),
        _ex("e2", "Sell", 2, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    # (4010 - 4000) * 2 = 20 points
    assert p[0].points_pnl == pytest.approx(20.0)
    # 20 points * $2/point = $40
    assert p[0].dollars_pnl == pytest.approx(40.0)


def test_short_points_pnl_is_positive_when_price_falls():
    exs = [
        _ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S"),
        _ex("e2", "Buy", 1, 4090.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    # (4090 - 4100) * -1 = 10 points
    assert p[0].points_pnl == pytest.approx(10.0)
    assert p[0].dollars_pnl == pytest.approx(20.0)


def test_commission_summed_across_all_fills():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, commission=1.25, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", commission=1.25, position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].commission == pytest.approx(2.50)


def test_duration_minutes_computed():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 400, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    # (400 - 100) / 60 = 5.0
    assert p[0].duration_minutes == pytest.approx(5.0)


def test_instrument_without_multiplier_falls_back_to_one():
    exs = [
        _ex("e1", "Buy", 1, 100.0, 100, instrument="ZZZ", position_after="1 L"),
        _ex("e2", "Sell", 1, 110.0, 200, entry_exit="Exit", instrument="ZZZ", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert p[0].points_pnl == pytest.approx(10.0)
    assert p[0].dollars_pnl == pytest.approx(10.0)
```

- [ ] **Step 2: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_weighted_pnl.py -q
```

Expected: 7 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_positions_weighted_pnl.py
git commit -m "test(positions): weighted-average prices and P&L"
```

---

## Task 6: `build_positions` — open position at end

If the last execution leaves running quantity non-zero, the trailing fills become an open position with null exit fields.

**Files:**
- Create: `tests/test_positions_open.py`

- [ ] **Step 1: Write the failing test**

```python
from models.execution import Execution
from services.positions import build_positions


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry", position_after="1 L"):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument="MNQ",
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_open_long_position_has_null_exit_fields():
    exs = [_ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L")]
    positions, _ = build_positions(exs)
    assert len(positions) == 1
    p = positions[0]
    assert p.side == "Long"
    assert p.entry_execution_id == "e1"
    assert p.entry_price == 4000.0
    assert p.quantity == 1
    assert p.exit_time is None
    assert p.exit_price is None
    assert p.points_pnl is None
    assert p.dollars_pnl is None
    assert p.duration_minutes is None


def test_open_position_after_closed_ones():
    exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
        _ex("e3", "Buy", 2, 4020.0, 300, position_after="2 L"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].exit_time == 200
    assert positions[1].exit_time is None
    assert positions[1].quantity == 2


def test_open_short_position():
    exs = [_ex("e1", "Sell", 1, 4100.0, 100, position_after="1 S")]
    p, _ = build_positions(exs)
    assert len(p) == 1
    assert p[0].side == "Short"
    assert p[0].exit_price is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_open.py -q
```

Expected: the first test fails — with the Task 4 implementation, a non-zero running quantity at the end produces no position.

- [ ] **Step 3: Update `build_positions` to emit the trailing open position**

Replace the end of `build_positions` in `services/positions.py`. The current body ends at the `for` loop; add the trailing emit:

```python
def build_positions(
    executions: Sequence[Execution],
) -> tuple[list[Position], list[IntegrityIssue]]:
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []
    current: list[Fill] = []
    running_qty = 0

    for ex in executions:
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        new_qty = running_qty + signed
        current.append(_fill_from(ex))
        running_qty = new_qty

        if running_qty == 0:
            positions.append(_make_position(current, is_open=False))
            current = []

    if current:
        positions.append(_make_position(current, is_open=True))

    return positions, issues
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_open.py tests/test_positions_long_short.py tests/test_positions_weighted_pnl.py -q
```

Expected: all pass (3 + 5 + 7 = 15).

- [ ] **Step 5: Commit**

```bash
git add services/positions.py tests/test_positions_open.py
git commit -m "feat(positions): emit trailing open position"
```

---

## Task 7: `build_positions` — direction-reversal splitter

A single fill that takes running quantity across zero (e.g., long 3 + Sell 5 → short 2) must be split into two synthetic sub-fills: one that brings running quantity to zero (closing the current position) and one that takes it from zero to the new quantity (opening the next). Both reference the same source ExecutionId with `#close` / `#open` suffixes. Commission is split proportionally by quantity.

**Files:**
- Modify: `services/positions.py`
- Create: `tests/test_positions_reversal.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from models.execution import Execution
from services.positions import build_positions


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry",
        position_after="1 L", commission=0.0):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument="MNQ",
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=commission, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_long_to_short_reversal_creates_two_positions():
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, position_after="3 L"),
        _ex("e2", "Sell", 5, 4010.0, 200, entry_exit="Exit",
            position_after="2 S", commission=2.5),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    # First position: long 3, closed at 4010 via synthetic #close fill.
    p0 = positions[0]
    assert p0.side == "Long"
    assert p0.entry_execution_id == "e1"
    assert p0.quantity == 3
    assert p0.exit_price == pytest.approx(4010.0)
    assert "e2#close" in p0.execution_ids
    # Second position: short 2, opened via synthetic #open fill — still open.
    p1 = positions[1]
    assert p1.side == "Short"
    assert p1.entry_execution_id == "e2#open"
    assert p1.quantity == 2
    assert p1.exit_time is None
    assert "e2#open" in p1.execution_ids


def test_short_to_long_reversal_creates_two_positions():
    exs = [
        _ex("e1", "Sell", 2, 4100.0, 100, position_after="2 S"),
        _ex("e2", "Buy", 5, 4090.0, 200, entry_exit="Exit", position_after="3 L"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[0].side == "Short"
    assert positions[0].quantity == 2
    assert positions[0].exit_price == pytest.approx(4090.0)
    assert positions[1].side == "Long"
    assert positions[1].quantity == 3
    assert positions[1].entry_execution_id == "e2#open"


def test_reversal_commission_split_proportionally():
    # long 3 → Sell 5 → short 2. Commission $5 on the reversal fill.
    # Close sub-fill gets 3/5 = $3; open sub-fill gets 2/5 = $2.
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, commission=0.0, position_after="3 L"),
        _ex("e2", "Sell", 5, 4010.0, 200, entry_exit="Exit",
            commission=5.0, position_after="2 S"),
    ]
    positions, _ = build_positions(exs)
    # First position's commission is e1 (0) + e2#close (3) = 3
    assert positions[0].commission == pytest.approx(3.0)
    # Second position is open and its only fill so far is e2#open (2)
    assert positions[1].commission == pytest.approx(2.0)


def test_reversal_followed_by_close():
    # long 3, Sell 5 → short 2, Buy 2 → flat. Two closed positions.
    exs = [
        _ex("e1", "Buy", 3, 4000.0, 100, position_after="3 L"),
        _ex("e2", "Sell", 5, 4010.0, 200, entry_exit="Exit", position_after="2 S"),
        _ex("e3", "Buy", 2, 4005.0, 300, entry_exit="Exit", position_after="-"),
    ]
    positions, _ = build_positions(exs)
    assert len(positions) == 2
    assert positions[1].exit_time == 300
    assert positions[1].exit_price == pytest.approx(4005.0)
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_reversal.py -q
```

Expected: failures — no splitter exists yet.

- [ ] **Step 3: Add `synthesize_fill` and update `build_positions`**

Replace the body of `build_positions` in `services/positions.py` (keep `_sign`, `_fill_from`, `_make_position`). Add `synthesize_fill` above `build_positions`:

```python
def synthesize_fill(
    ex: Execution,
    *,
    id_suffix: str,
    split_quantity: int,
    split_side: str,
) -> Fill:
    """Produce a synthetic sub-fill for a direction-reversing execution.

    `split_quantity` is the unsigned size of this half of the reversal.
    Commission is split proportionally by quantity vs. the parent fill.
    The caller decides which half gets which side.
    """
    proportion = split_quantity / ex.quantity
    return Fill(
        execution_id=f"{ex.nt_execution_id}{id_suffix}",
        account=ex.account,
        instrument=ex.instrument,
        timestamp=ex.timestamp,
        side=split_side,  # type: ignore[arg-type]
        quantity=split_quantity,
        price=ex.price,
        commission=ex.commission * proportion,
        entry_exit="Exit" if id_suffix == "#close" else "Entry",
    )


def build_positions(
    executions: Sequence[Execution],
) -> tuple[list[Position], list[IntegrityIssue]]:
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []
    current: list[Fill] = []
    running_qty = 0

    for ex in executions:
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        new_qty = running_qty + signed

        if (
            running_qty != 0
            and new_qty != 0
            and _sign(new_qty) != _sign(running_qty)
        ):
            # Direction reversal: split this raw fill into two sub-fills.
            close_qty = abs(running_qty)
            open_qty = abs(new_qty)
            # The closing sub-fill has the opposite side of current running_qty.
            close_side = "Sell" if running_qty > 0 else "Buy"
            # The opening sub-fill matches the raw fill's side.
            open_side = ex.side
            sub_close = synthesize_fill(
                ex, id_suffix="#close",
                split_quantity=close_qty, split_side=close_side,
            )
            sub_open = synthesize_fill(
                ex, id_suffix="#open",
                split_quantity=open_qty, split_side=open_side,
            )
            current.append(sub_close)
            positions.append(_make_position(current, is_open=False))
            current = [sub_open]
            running_qty = new_qty
            continue

        current.append(_fill_from(ex))
        running_qty = new_qty

        if running_qty == 0:
            positions.append(_make_position(current, is_open=False))
            current = []

    if current:
        positions.append(_make_position(current, is_open=True))

    return positions, issues
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_reversal.py tests/test_positions_long_short.py tests/test_positions_open.py tests/test_positions_weighted_pnl.py -q
```

Expected: 4 + 5 + 3 + 7 = 19 passed.

- [ ] **Step 5: Commit**

```bash
git add services/positions.py tests/test_positions_reversal.py
git commit -m "feat(positions): direction-reversal splitter"
```

---

## Task 8: `build_positions` — sort stability

Callers may hand in unsorted executions. `build_positions` sorts by `(timestamp, execution_id)` before walking so out-of-order imports produce identical results.

**Files:**
- Modify: `services/positions.py`
- Create: `tests/test_positions_sort.py`

- [ ] **Step 1: Write the failing test**

```python
from models.execution import Execution
from services.positions import build_positions


def _ex(eid, side, qty, price, ts, *, entry_exit="Entry", position_after="1 L"):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument="MNQ",
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_unsorted_input_produces_same_result_as_sorted():
    sorted_exs = [
        _ex("e1", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    unsorted_exs = list(reversed(sorted_exs))
    sorted_p, _ = build_positions(sorted_exs)
    unsorted_p, _ = build_positions(unsorted_exs)
    assert len(sorted_p) == len(unsorted_p) == 1
    assert sorted_p[0].entry_execution_id == unsorted_p[0].entry_execution_id
    assert sorted_p[0].exit_price == unsorted_p[0].exit_price


def test_ties_broken_by_execution_id():
    # Same timestamp: deterministic order by NT ExecutionId.
    exs = [
        _ex("b", "Sell", 1, 4010.0, 100, entry_exit="Exit", position_after="-"),
        _ex("a", "Buy", 1, 4000.0, 100, position_after="1 L"),
    ]
    p, _ = build_positions(exs)
    assert len(p) == 1
    assert p[0].entry_execution_id == "a"
    assert p[0].execution_ids == ["a", "b"]


def test_different_accounts_and_instruments_are_not_caller_grouped():
    # build_positions walks whatever it is handed. Callers are responsible
    # for grouping by (account, instrument). When handed a mixed list,
    # sorting by timestamp still produces a deterministic (if useless) walk.
    exs = [
        _ex("x", "Buy", 1, 4000.0, 100, position_after="1 L"),
        _ex("y", "Sell", 1, 4010.0, 200, entry_exit="Exit", position_after="-"),
    ]
    p, _ = build_positions(exs)
    assert len(p) == 1
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_sort.py -q
```

Expected: `test_unsorted_input_produces_same_result_as_sorted` fails.

- [ ] **Step 3: Add the sort in `build_positions`**

Edit `services/positions.py`. Change the first line of `build_positions`'s body to sort:

```python
def build_positions(
    executions: Sequence[Execution],
) -> tuple[list[Position], list[IntegrityIssue]]:
    executions = sorted(executions, key=lambda e: (e.timestamp, e.nt_execution_id))
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []
    current: list[Fill] = []
    running_qty = 0
    # ... rest unchanged
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_sort.py -q
```

Expected: 3 passed. Then rerun the full positions suite to confirm nothing regressed:

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_long_short.py tests/test_positions_weighted_pnl.py tests/test_positions_open.py tests/test_positions_reversal.py tests/test_positions_sort.py -q
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add services/positions.py tests/test_positions_sort.py
git commit -m "feat(positions): sort stability across timestamp and execution_id"
```

---

## Task 9: IntegrityValidator — position column cross-check

The exporter writes the post-execution running position in the CSV's `Position` column (`{qty} L`, `{qty} S`, or `-`). The validator compares that to what the builder computed, and emits an `IntegrityIssue` with `severity="high"` and `type="position_column_mismatch"` whenever they disagree.

**Files:**
- Create: `services/integrity.py`
- Create: `tests/test_integrity_validator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_integrity_validator.py`:

```python
from models.execution import Execution
from services.integrity import cross_check_against_source_position_column


def _ex(eid, side, qty, ts, *, position_after, entry_exit="Entry"):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument="MNQ",
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=4000.0, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_consistent_position_column_produces_no_issues():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 L"),
        _ex("e2", "Buy", 2, 200, position_after="3 L"),
        _ex("e3", "Sell", 3, 300, position_after="-", entry_exit="Exit"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_mismatched_position_column_produces_high_issue():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="2 L"),  # builder sees 1 L
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert issues[0].severity == "high"
    assert issues[0].type == "position_column_mismatch"
    assert issues[0].execution_id == "e1"


def test_mismatched_side_flag_produces_issue():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 S"),  # wrong side
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert issues[0].type == "position_column_mismatch"


def test_null_position_column_is_skipped():
    # Empty CSV Position field → nothing to cross-check.
    exs = [
        _ex("e1", "Buy", 1, 100, position_after=None),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_dash_matches_flat_running_quantity():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="1 L"),
        _ex("e2", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert issues == []


def test_unparseable_position_column_is_reported():
    exs = [
        _ex("e1", "Buy", 1, 100, position_after="garbage"),
    ]
    issues = cross_check_against_source_position_column(exs)
    assert len(issues) == 1
    assert "garbage" in issues[0].description
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_validator.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.integrity'`.

- [ ] **Step 3: Implement `services/integrity.py`**

```python
from collections.abc import Sequence

from models.execution import Execution
from models.position import IntegrityIssue


def _parse_position_column(value: str) -> int | None:
    """Parse the exporter's Position column into signed running quantity.

    Returns None if the value cannot be interpreted. `-` means flat (0).
    `5 L` means +5, `3 S` means -3.
    """
    s = value.strip()
    if s == "-":
        return 0
    parts = s.split()
    if len(parts) != 2:
        return None
    qty_s, tag = parts
    try:
        qty = int(qty_s)
    except ValueError:
        return None
    if qty < 0:
        return None
    if tag == "L":
        return qty
    if tag == "S":
        return -qty
    return None


def cross_check_against_source_position_column(
    executions: Sequence[Execution],
) -> list[IntegrityIssue]:
    """Walk executions in arrival order and compare each position_after string
    against the builder's own running quantity.

    The caller is expected to pass executions for a single (account, instrument)
    pair in chronological order. `build_positions` already sorts internally;
    this function just walks the provided list.
    """
    issues: list[IntegrityIssue] = []
    running_qty = 0
    for ex in sorted(executions, key=lambda e: (e.timestamp, e.nt_execution_id)):
        signed = ex.quantity if ex.side == "Buy" else -ex.quantity
        running_qty += signed

        raw = ex.position_after
        if raw is None or raw == "":
            continue

        reported = _parse_position_column(raw)
        if reported is None:
            issues.append(IntegrityIssue(
                account=ex.account,
                instrument=ex.instrument,
                execution_id=ex.nt_execution_id,
                severity="high",
                type="position_column_mismatch",
                description=f"could not parse Position column value {raw!r}",
            ))
            continue

        if reported != running_qty:
            issues.append(IntegrityIssue(
                account=ex.account,
                instrument=ex.instrument,
                execution_id=ex.nt_execution_id,
                severity="high",
                type="position_column_mismatch",
                description=(
                    f"builder running qty {running_qty} disagrees with CSV "
                    f"Position column {raw!r} (parsed as {reported})"
                ),
            ))
    return issues
```

- [ ] **Step 4: Wire the cross-check into `build_positions`**

Update `services/positions.py` — at the end of `build_positions`, call the validator and merge its issues into the returned list:

```python
# At the top of services/positions.py, add:
from services.integrity import cross_check_against_source_position_column
```

And change the `return` of `build_positions`:

```python
    issues.extend(cross_check_against_source_position_column(executions))
    return positions, issues
```

(Place the `extend` call just before `return positions, issues`.)

- [ ] **Step 5: Run**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_validator.py tests/test_positions_long_short.py tests/test_positions_open.py tests/test_positions_weighted_pnl.py tests/test_positions_reversal.py tests/test_positions_sort.py -q
```

Expected: 6 + 22 = 28 passed.

- [ ] **Step 6: Commit**

```bash
git add services/integrity.py services/positions.py tests/test_integrity_validator.py
git commit -m "feat(positions): integrity cross-check against CSV Position column"
```

---

## Task 10: integrity_issues DB helpers

Small SQL layer for the diff function. `upsert_issue` inserts new or bumps `last_seen_at`; `auto_resolve_missing` sets `resolved_at`/`resolved_by='system'` for open issues no longer present; `list_open_for_pair` returns currently-open rows for one `(account, instrument)`; `mark_resolved_by_user` / `mark_ignored` are used by the API.

**Files:**
- Create: `services/integrity_db.py`
- Create: `tests/test_integrity_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_integrity_db.py`:

```python
from pathlib import Path

from db import connect
from migrations import run_migrations
from models.position import IntegrityIssue
from services.integrity_db import (
    auto_resolve_missing,
    list_open_for_pair,
    mark_ignored,
    mark_resolved_by_user,
    upsert_issue,
)


def _migrated(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def _issue(eid: str = "abc"):
    return IntegrityIssue(
        account="Sim101",
        instrument="MNQ",
        execution_id=eid,
        severity="high",
        type="position_column_mismatch",
        description="mismatch",
    )


def test_upsert_new_issue_inserts_row(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "abc"
        assert rows[0]["detected_at"] == 100
        assert rows[0]["last_seen_at"] == 100
        assert rows[0]["resolved_at"] is None
    finally:
        conn.close()


def test_upsert_same_issue_bumps_last_seen(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        upsert_issue(conn, _issue(), now=200)
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["detected_at"] == 100
        assert rows[0]["last_seen_at"] == 200
    finally:
        conn.close()


def test_auto_resolve_missing_resolves_only_stale_issues(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("abc"), now=100)
        upsert_issue(conn, _issue("xyz"), now=100)
        # Only 'abc' still present:
        auto_resolve_missing(
            conn, account="Sim101", instrument="MNQ",
            present_keys={("abc", "position_column_mismatch")},
            now=200,
        )
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        ids = {r["execution_id"] for r in rows}
        assert ids == {"abc"}  # 'xyz' auto-resolved
        xyz = conn.execute(
            "SELECT resolved_at, resolved_by FROM integrity_issues WHERE execution_id='xyz'"
        ).fetchone()
        assert xyz["resolved_at"] == 200
        assert xyz["resolved_by"] == "system"
    finally:
        conn.close()


def test_auto_resolve_skips_ignored_issues(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("abc"), now=100)
        mark_ignored(conn, issue_id=1, note="known false positive")
        auto_resolve_missing(
            conn, account="Sim101", instrument="MNQ",
            present_keys=set(),
            now=200,
        )
        row = conn.execute(
            "SELECT ignored, resolved_at FROM integrity_issues WHERE issue_id=1"
        ).fetchone()
        assert row["ignored"] == 1
        assert row["resolved_at"] is None
    finally:
        conn.close()


def test_mark_resolved_by_user(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue(), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=150, note="fixed by hand")
        row = conn.execute(
            "SELECT resolved_at, resolved_by, resolution_note "
            "FROM integrity_issues WHERE issue_id=1"
        ).fetchone()
        assert row["resolved_at"] == 150
        assert row["resolved_by"] == "user"
        assert row["resolution_note"] == "fixed by hand"
    finally:
        conn.close()


def test_list_open_excludes_resolved_and_ignored(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
        upsert_issue(conn, _issue("b"), now=100)
        upsert_issue(conn, _issue("c"), now=100)
        mark_resolved_by_user(conn, issue_id=1, now=110, note=None)
        mark_ignored(conn, issue_id=2, note="noise")
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        ids = {r["execution_id"] for r in rows}
        assert ids == {"c"}
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_db.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.integrity_db'`.

- [ ] **Step 3: Implement `services/integrity_db.py`**

```python
import sqlite3

from models.position import IntegrityIssue


def upsert_issue(conn: sqlite3.Connection, issue: IntegrityIssue, *, now: int) -> None:
    """Insert the issue if new; bump last_seen_at if it already exists.

    Keyed by UNIQUE(account, instrument, execution_id, type). Does not touch
    resolved_at or ignored so a stored resolution survives a re-detection.
    """
    conn.execute(
        "INSERT INTO integrity_issues "
        "(account, instrument, execution_id, severity, type, description,"
        " detected_at, last_seen_at, ignored) "
        "VALUES (?,?,?,?,?,?,?,?,0) "
        "ON CONFLICT(account, instrument, execution_id, type) DO UPDATE SET "
        " last_seen_at = excluded.last_seen_at,"
        " severity = excluded.severity,"
        " description = excluded.description",
        (
            issue.account, issue.instrument, issue.execution_id,
            issue.severity, issue.type, issue.description,
            now, now,
        ),
    )


def auto_resolve_missing(
    conn: sqlite3.Connection,
    *,
    account: str,
    instrument: str,
    present_keys: set[tuple[str, str]],
    now: int,
) -> None:
    """Mark as system-resolved every open issue for the pair not in `present_keys`.

    `present_keys` is a set of `(execution_id, type)` tuples currently produced
    by build_positions. Ignored issues are left alone.
    """
    rows = conn.execute(
        "SELECT issue_id, execution_id, type FROM integrity_issues "
        "WHERE account = ? AND instrument = ? AND resolved_at IS NULL AND ignored = 0",
        (account, instrument),
    ).fetchall()
    stale_ids = [
        r["issue_id"]
        for r in rows
        if (r["execution_id"], r["type"]) not in present_keys
    ]
    if not stale_ids:
        return
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(
        f"UPDATE integrity_issues SET resolved_at = ?, resolved_by = 'system' "
        f"WHERE issue_id IN ({placeholders})",
        (now, *stale_ids),
    )


def list_open_for_pair(
    conn: sqlite3.Connection, account: str, instrument: str,
) -> list:
    return conn.execute(
        "SELECT * FROM integrity_issues "
        "WHERE account = ? AND instrument = ? "
        "  AND resolved_at IS NULL AND ignored = 0 "
        "ORDER BY issue_id",
        (account, instrument),
    ).fetchall()


def mark_resolved_by_user(
    conn: sqlite3.Connection,
    *,
    issue_id: int,
    now: int,
    note: str | None,
) -> None:
    conn.execute(
        "UPDATE integrity_issues SET resolved_at = ?, resolved_by = 'user', "
        " resolution_note = ? WHERE issue_id = ?",
        (now, note, issue_id),
    )


def mark_ignored(conn: sqlite3.Connection, *, issue_id: int, note: str) -> None:
    conn.execute(
        "UPDATE integrity_issues SET ignored = 1, ignore_note = ? WHERE issue_id = ?",
        (note, issue_id),
    )
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_db.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/integrity_db.py tests/test_integrity_db.py
git commit -m "feat(positions): integrity_issues SQL helpers"
```

---

## Task 11: `run_integrity_diff` — composer and post-tick hook

`run_integrity_diff(db_path, account, instrument)` is the entry point the import pipeline will register. It loads all executions for the pair, calls `build_positions`, collects the issues, and diffs them against the DB in one transaction.

**Files:**
- Modify: `services/integrity.py`
- Create: `tests/test_integrity_diff.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_integrity_diff.py`:

```python
from pathlib import Path

from db import connect
from services.import_db import bulk_insert_executions
from services.integrity import run_integrity_diff
from services.integrity_db import list_open_for_pair
from models.execution import Execution


def _ex(eid, side, qty, ts, *, position_after, entry_exit="Entry"):
    return Execution(
        nt_execution_id=eid, account="Sim101", instrument="MNQ",
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=4000.0, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_diff_inserts_new_issue(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(conn, [
            _ex("e1", "Buy", 1, 100, position_after="5 L"),  # mismatch
        ])
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "e1"
    finally:
        conn.close()


def test_diff_auto_resolves_stale_issue_when_data_is_fixed(migrated_db: Path):
    # First pass: bad data → issue inserted
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(conn, [
            _ex("e1", "Buy", 1, 100, position_after="5 L"),
        ])
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    # Second pass: data replaced with consistent rows → issue should auto-resolve
    conn = connect(migrated_db)
    try:
        conn.execute("DELETE FROM executions")
        bulk_insert_executions(conn, [
            _ex("e1", "Buy", 1, 100, position_after="1 L"),
        ])
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        rows = list_open_for_pair(conn, "Sim101", "MNQ")
        assert rows == []
        resolved = conn.execute(
            "SELECT resolved_by FROM integrity_issues WHERE execution_id='e1'"
        ).fetchone()
        assert resolved["resolved_by"] == "system"
    finally:
        conn.close()


def test_diff_is_idempotent_when_issue_persists(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(conn, [
            _ex("e1", "Buy", 1, 100, position_after="5 L"),
        ])
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM integrity_issues WHERE execution_id='e1'"
        ).fetchone()[0]
        assert rows == 1
    finally:
        conn.close()


def test_diff_leaves_other_pairs_alone(migrated_db: Path):
    conn = connect(migrated_db)
    try:
        bulk_insert_executions(conn, [
            Execution(
                nt_execution_id="e1", account="Sim101", instrument="MNQ",
                timestamp=100, side="Buy", original_action="Buy",
                quantity=1, price=4000.0, commission=0.0, entry_exit="Entry",
                position_after="5 L",  # mismatch
                source_order_id=None, source_filename="f.csv", imported_at=100,
            ),
            Execution(
                nt_execution_id="e2", account="APEX-1", instrument="ES",
                timestamp=100, side="Buy", original_action="Buy",
                quantity=1, price=4000.0, commission=0.0, entry_exit="Entry",
                position_after="5 L",  # mismatch
                source_order_id=None, source_filename="f.csv", imported_at=100,
            ),
        ])
    finally:
        conn.close()
    run_integrity_diff(migrated_db, "Sim101", "MNQ")
    conn = connect(migrated_db)
    try:
        sim = list_open_for_pair(conn, "Sim101", "MNQ")
        apex = list_open_for_pair(conn, "APEX-1", "ES")
        assert len(sim) == 1
        assert apex == []  # untouched — diff was only called for Sim101/MNQ
    finally:
        conn.close()
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_diff.py -q
```

Expected: `ImportError: cannot import name 'run_integrity_diff'`.

- [ ] **Step 3: Add `run_integrity_diff` to `services/integrity.py`**

Append to the bottom of `services/integrity.py`. **Important:** the `build_positions` import is *inside* the function body to break the circular import with `services/positions.py` (which imports `cross_check_against_source_position_column` at its module top).

```python
import time as _time
from pathlib import Path as _Path

from db import connect as _connect


def run_integrity_diff(
    db_path: _Path | str,
    account: str,
    instrument: str,
) -> None:
    """Load executions for one pair, build positions + issues, diff DB.

    This is the function plan 11 registers on ImportPipeline.post_tick_hooks
    (indirectly — the registered hook iterates affected pairs and calls this
    once per pair).
    """
    # Deferred imports — services/positions imports from this module at its
    # top, so top-level imports here would create a cycle.
    from models.execution import Execution
    from services.integrity_db import auto_resolve_missing, upsert_issue
    from services.positions import build_positions

    now = int(_time.time())
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit,"
            " position_after, source_order_id, source_filename, imported_at "
            "FROM executions WHERE account = ? AND instrument = ? "
            "ORDER BY timestamp, nt_execution_id",
            (account, instrument),
        ).fetchall()
        executions = [
            Execution(
                nt_execution_id=r["nt_execution_id"],
                account=r["account"],
                instrument=r["instrument"],
                timestamp=r["timestamp"],
                side=r["side"],
                original_action=r["original_action"],
                quantity=r["quantity"],
                price=r["price"],
                commission=r["commission"],
                entry_exit=r["entry_exit"],
                position_after=r["position_after"],
                source_order_id=r["source_order_id"],
                source_filename=r["source_filename"],
                imported_at=r["imported_at"],
            )
            for r in rows
        ]
        _positions, issues = build_positions(executions)

        present: set[tuple[str, str]] = {
            (i.execution_id, i.type) for i in issues
        }

        conn.execute("BEGIN")
        try:
            for issue in issues:
                upsert_issue(conn, issue, now=now)
            auto_resolve_missing(
                conn,
                account=account,
                instrument=instrument,
                present_keys=present,
                now=now,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_integrity_diff.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/integrity.py tests/test_integrity_diff.py
git commit -m "feat(positions): run_integrity_diff composer"
```

---

## Task 12: Register the integrity hook on `ImportPipeline.post_tick_hooks`

Plan 10 shipped `ImportPipeline` with `post_tick_hooks = []`. Plan 11 registers one hook in the app factory: it receives `(tick_result, parsed, affected)` and calls `run_integrity_diff` once per affected `(account, instrument)` pair.

**Files:**
- Modify: `app.py`
- Create: `tests/test_app_factory_plan11.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_factory_plan11.py`:

```python
import time
from pathlib import Path

from app import create_app
from db import connect


def test_integrity_hook_runs_after_tick_and_records_issues(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        header = (
            "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
            "Commission,Rate,Account,Connection,TradeValidation\n"
        )
        # Malformed Position column → builder disagrees, issue expected.
        bad_row = (
            "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,badpos1,Entry,99 L,"
            "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
        )
        path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
        path.write_text(header + bad_row, encoding="utf-8")

        deadline = time.time() + 3.0
        issue_count = 0
        while time.time() < deadline:
            conn = connect(tmp_config.db_path)
            try:
                issue_count = conn.execute(
                    "SELECT COUNT(*) FROM integrity_issues "
                    "WHERE execution_id = 'badpos1' AND resolved_at IS NULL"
                ).fetchone()[0]
            finally:
                conn.close()
            if issue_count >= 1:
                break
            time.sleep(0.05)
        assert issue_count == 1
    finally:
        services.stop()


def test_positions_route_returns_computed_positions(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    db_path = tmp_config.db_path

    # Seed two consistent executions directly.
    from models.execution import Execution
    from services.import_db import bulk_insert_executions

    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            Execution(
                nt_execution_id="a", account="Sim101", instrument="MNQ",
                timestamp=100, side="Buy", original_action="Buy",
                quantity=1, price=4000.0, commission=0.0, entry_exit="Entry",
                position_after="1 L", source_order_id=None,
                source_filename="f.csv", imported_at=100,
            ),
            Execution(
                nt_execution_id="b", account="Sim101", instrument="MNQ",
                timestamp=200, side="Sell", original_action="Sell",
                quantity=1, price=4010.0, commission=0.0, entry_exit="Exit",
                position_after="-", source_order_id=None,
                source_filename="f.csv", imported_at=200,
            ),
        ])
    finally:
        conn.close()

    resp = app.test_client().get("/api/positions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["entry_execution_id"] == "a"
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan11.py -q
```

Expected: the hook test fails because no issue row is created; the route test fails because `/api/positions` is not registered. Both will be fixed over Tasks 12–15.

- [ ] **Step 3: Add the hook in `app.py`**

Edit `app.py`. Add an import at the top:

```python
from services.integrity import run_integrity_diff
```

And replace the `post_tick_hooks=[]` line with a registered hook builder. Change the `pipeline = ImportPipeline(...)` construction to:

```python
    def _integrity_hook(_result, _parsed, affected):
        for acct, inst in affected:
            try:
                run_integrity_diff(config.db_path, acct, inst)
            except Exception:
                log.exception(
                    "integrity diff failed",
                    extra={"acct": acct, "inst": inst},
                )

    pipeline = ImportPipeline(
        db_path=config.db_path,
        trader_tz=trader_tz,
        post_tick_hooks=[_integrity_hook],
    )
```

- [ ] **Step 4: Run just the hook test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan11.py::test_integrity_hook_runs_after_tick_and_records_issues -q
```

Expected: 1 passed. The route test still fails — it is fixed by Task 15.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app_factory_plan11.py
git commit -m "feat(positions): register integrity diff hook on import tick"
```

---

## Task 13: `positions_service` query layer

Route handlers should stay thin. `positions_service` loads executions per filter and calls `build_positions`.

**Files:**
- Create: `services/positions_service.py`
- Create: `tests/test_positions_service.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from db import connect
from models.execution import Execution
from services.import_db import bulk_insert_executions
from services.positions_service import get_position, list_positions


def _ex(eid, side, qty, ts, *, account="Sim101", instrument="MNQ",
        position_after="1 L", entry_exit="Entry", price=4000.0):
    return Execution(
        nt_execution_id=eid, account=account, instrument=instrument,
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def _seed(db_path: Path, rows):
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, rows)
    finally:
        conn.close()


def test_list_positions_returns_computed_positions(migrated_db: Path):
    _seed(migrated_db, [
        _ex("a", "Buy", 1, 100, position_after="1 L"),
        _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
    ])
    positions = list_positions(migrated_db)
    assert len(positions) == 1
    assert positions[0].entry_execution_id == "a"


def test_list_positions_filters_by_account(migrated_db: Path):
    _seed(migrated_db, [
        _ex("a", "Buy", 1, 100, account="Sim101", position_after="1 L"),
        _ex("b", "Sell", 1, 200, account="Sim101", entry_exit="Exit", position_after="-"),
        _ex("c", "Buy", 1, 300, account="APEX-1", position_after="1 L"),
        _ex("d", "Sell", 1, 400, account="APEX-1", entry_exit="Exit", position_after="-"),
    ])
    sim = list_positions(migrated_db, account="Sim101")
    apex = list_positions(migrated_db, account="APEX-1")
    assert len(sim) == 1
    assert len(apex) == 1
    assert sim[0].account == "Sim101"
    assert apex[0].account == "APEX-1"


def test_list_positions_filters_by_instrument(migrated_db: Path):
    _seed(migrated_db, [
        _ex("a", "Buy", 1, 100, instrument="MNQ", position_after="1 L"),
        _ex("b", "Sell", 1, 200, instrument="MNQ", entry_exit="Exit", position_after="-"),
        _ex("c", "Buy", 1, 300, instrument="ES", position_after="1 L"),
        _ex("d", "Sell", 1, 400, instrument="ES", entry_exit="Exit", position_after="-"),
    ])
    mnq = list_positions(migrated_db, instrument="MNQ")
    es = list_positions(migrated_db, instrument="ES")
    assert len(mnq) == 1 and mnq[0].instrument == "MNQ"
    assert len(es) == 1 and es[0].instrument == "ES"


def test_get_position_by_natural_key(migrated_db: Path):
    _seed(migrated_db, [
        _ex("a", "Buy", 1, 100, position_after="1 L"),
        _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
    ])
    p = get_position(migrated_db, account="Sim101", instrument="MNQ", entry_execution_id="a")
    assert p is not None
    assert p.entry_execution_id == "a"


def test_get_position_returns_none_when_missing(migrated_db: Path):
    assert get_position(
        migrated_db, account="Sim101", instrument="MNQ", entry_execution_id="nope",
    ) is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'services.positions_service'`.

- [ ] **Step 3: Implement `services/positions_service.py`**

```python
from pathlib import Path

from db import connect
from models.execution import Execution
from models.position import Position
from services.positions import build_positions


def _load_executions(
    db_path: Path | str,
    *,
    account: str | None = None,
    instrument: str | None = None,
) -> list[Execution]:
    sql = (
        "SELECT nt_execution_id, account, instrument, timestamp, side,"
        " original_action, quantity, price, commission, entry_exit,"
        " position_after, source_order_id, source_filename, imported_at "
        "FROM executions"
    )
    clauses: list[str] = []
    params: list[object] = []
    if account is not None:
        clauses.append("account = ?")
        params.append(account)
    if instrument is not None:
        clauses.append("instrument = ?")
        params.append(instrument)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY account, instrument, timestamp, nt_execution_id"

    conn = connect(db_path)
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()
    return [
        Execution(
            nt_execution_id=r["nt_execution_id"],
            account=r["account"],
            instrument=r["instrument"],
            timestamp=r["timestamp"],
            side=r["side"],
            original_action=r["original_action"],
            quantity=r["quantity"],
            price=r["price"],
            commission=r["commission"],
            entry_exit=r["entry_exit"],
            position_after=r["position_after"],
            source_order_id=r["source_order_id"],
            source_filename=r["source_filename"],
            imported_at=r["imported_at"],
        )
        for r in rows
    ]


def list_positions(
    db_path: Path | str,
    *,
    account: str | None = None,
    instrument: str | None = None,
) -> list[Position]:
    """Load executions per filters, group by (account, instrument), build positions."""
    executions = _load_executions(db_path, account=account, instrument=instrument)
    groups: dict[tuple[str, str], list[Execution]] = {}
    for e in executions:
        groups.setdefault((e.account, e.instrument), []).append(e)

    positions: list[Position] = []
    for _key, group in groups.items():
        p, _issues = build_positions(group)
        positions.extend(p)
    return positions


def get_position(
    db_path: Path | str,
    *,
    account: str,
    instrument: str,
    entry_execution_id: str,
) -> Position | None:
    positions = list_positions(db_path, account=account, instrument=instrument)
    for p in positions:
        if p.entry_execution_id == entry_execution_id:
            return p
    return None
```

- [ ] **Step 4: Run to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_positions_service.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add services/positions_service.py tests/test_positions_service.py
git commit -m "feat(positions): positions_service query layer"
```

---

## Task 14: Routes — `/api/positions` and `/api/integrity-issues`

One blueprint hosts both surfaces. Routes are thin: parse args, call the service, serialize.

**Files:**
- Create: `routes/positions.py`
- Create: `tests/test_routes_positions.py`
- Create: `tests/test_routes_integrity.py`

- [ ] **Step 1: Write the positions-route test**

Create `tests/test_routes_positions.py`:

```python
from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.execution import Execution
from routes.positions import build_positions_blueprint
from services.import_db import bulk_insert_executions


@pytest.fixture
def app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _ex(eid, side, qty, ts, *, account="Sim101", instrument="MNQ",
        position_after="1 L", entry_exit="Entry", price=4000.0):
    return Execution(
        nt_execution_id=eid, account=account, instrument=instrument,
        timestamp=ts, side=side, original_action=side, quantity=qty,
        price=price, commission=0.0, entry_exit=entry_exit,
        position_after=position_after, source_order_id=None,
        source_filename="f.csv", imported_at=ts,
    )


def test_list_empty(app):
    app_, _ = app
    resp = app_.test_client().get("/api/positions")
    assert resp.status_code == 200
    assert resp.get_json() == {"positions": []}


def test_list_returns_all_positions(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            _ex("a", "Buy", 1, 100, position_after="1 L"),
            _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
        ])
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["entry_execution_id"] == "a"


def test_list_filters_by_account(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            _ex("a", "Buy", 1, 100, account="Sim101", position_after="1 L"),
            _ex("b", "Sell", 1, 200, account="Sim101",
                entry_exit="Exit", position_after="-"),
            _ex("c", "Buy", 1, 300, account="APEX-1", position_after="1 L"),
            _ex("d", "Sell", 1, 400, account="APEX-1",
                entry_exit="Exit", position_after="-"),
        ])
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions?account=APEX-1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["account"] == "APEX-1"


def test_get_position_by_natural_key(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            _ex("a", "Buy", 1, 100, position_after="1 L"),
            _ex("b", "Sell", 1, 200, entry_exit="Exit", position_after="-"),
        ])
    finally:
        conn.close()
    resp = app_.test_client().get("/api/positions/Sim101/MNQ/a")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entry_execution_id"] == "a"


def test_get_position_404(app):
    app_, _ = app
    resp = app_.test_client().get("/api/positions/Sim101/MNQ/nope")
    assert resp.status_code == 404
```

- [ ] **Step 2: Write the integrity-route test**

Create `tests/test_routes_integrity.py`:

```python
from pathlib import Path

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from models.position import IntegrityIssue
from routes.positions import build_positions_blueprint
from services.integrity_db import upsert_issue


@pytest.fixture
def app(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.register_blueprint(build_positions_blueprint())
    return app, db_path


def _issue(eid="abc"):
    return IntegrityIssue(
        account="Sim101", instrument="MNQ", execution_id=eid,
        severity="high", type="position_column_mismatch", description="x",
    )


def test_list_integrity_empty(app):
    app_, _ = app
    resp = app_.test_client().get("/api/integrity-issues")
    assert resp.status_code == 200
    assert resp.get_json() == {"issues": []}


def test_list_integrity_returns_open_issues(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
        upsert_issue(conn, _issue("b"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().get("/api/integrity-issues")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["issues"]) == 2


def test_resolve_issue(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post(
        "/api/integrity-issues/1/resolve", json={"note": "fixed"}
    )
    assert resp.status_code == 200
    resp2 = app_.test_client().get("/api/integrity-issues")
    assert resp2.get_json() == {"issues": []}


def test_ignore_issue(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post(
        "/api/integrity-issues/1/ignore", json={"note": "known noise"}
    )
    assert resp.status_code == 200
    resp2 = app_.test_client().get("/api/integrity-issues")
    assert resp2.get_json() == {"issues": []}


def test_ignore_requires_note(app):
    app_, db_path = app
    conn = connect(db_path)
    try:
        upsert_issue(conn, _issue("a"), now=100)
    finally:
        conn.close()
    resp = app_.test_client().post(
        "/api/integrity-issues/1/ignore", json={}
    )
    assert resp.status_code == 400
```

- [ ] **Step 3: Run both to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_positions.py tests/test_routes_integrity.py -q
```

Expected: `ModuleNotFoundError: No module named 'routes.positions'`.

- [ ] **Step 4: Implement `routes/positions.py`**

```python
import time

from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger
from services.integrity_db import mark_ignored, mark_resolved_by_user
from services.positions_service import get_position, list_positions

log = get_logger("http.positions")


def build_positions_blueprint() -> Blueprint:
    bp = Blueprint("positions", __name__)

    def _db_path():
        return current_app.config["FTL_DB_PATH"]

    @bp.get("/api/positions")
    def list_endpoint():
        account = request.args.get("account")
        instrument = request.args.get("instrument")
        positions = list_positions(
            _db_path(), account=account, instrument=instrument,
        )
        return jsonify({"positions": [p.model_dump() for p in positions]})

    @bp.get("/api/positions/<account>/<instrument>/<entry_execution_id>")
    def get_endpoint(account: str, instrument: str, entry_execution_id: str):
        p = get_position(
            _db_path(),
            account=account,
            instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(p.model_dump())

    @bp.get("/api/integrity-issues")
    def list_integrity():
        conn = connect(_db_path())
        try:
            rows = conn.execute(
                "SELECT * FROM integrity_issues "
                "WHERE resolved_at IS NULL AND ignored = 0 "
                "ORDER BY issue_id DESC LIMIT 500"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"issues": [dict(r) for r in rows]})

    @bp.post("/api/integrity-issues/<int:issue_id>/resolve")
    def resolve_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            return jsonify({"error": "note must be a string"}), 400
        conn = connect(_db_path())
        try:
            conn.execute("BEGIN")
            try:
                mark_resolved_by_user(
                    conn, issue_id=issue_id, now=int(time.time()), note=note,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return jsonify({"ok": True})

    @bp.post("/api/integrity-issues/<int:issue_id>/ignore")
    def ignore_integrity(issue_id: int):
        body = request.get_json(silent=True) or {}
        note = body.get("note")
        if not isinstance(note, str) or not note:
            return jsonify({"error": "note is required"}), 400
        conn = connect(_db_path())
        try:
            conn.execute("BEGIN")
            try:
                mark_ignored(conn, issue_id=issue_id, note=note)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return jsonify({"ok": True})

    return bp
```

- [ ] **Step 5: Run both route tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_positions.py tests/test_routes_integrity.py -q
```

Expected: 5 + 5 = 10 passed.

- [ ] **Step 6: Commit**

```bash
git add routes/positions.py tests/test_routes_positions.py tests/test_routes_integrity.py
git commit -m "feat(positions): /api/positions and /api/integrity-issues routes"
```

---

## Task 15: Wire the positions blueprint into the app factory

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Edit `app.py`**

Add the import near the other route imports:

```python
from routes.positions import build_positions_blueprint
```

And register it next to the imports blueprint:

```python
    app.register_blueprint(health_routes.bp)
    app.register_blueprint(build_imports_blueprint())
    app.register_blueprint(build_positions_blueprint())
```

- [ ] **Step 2: Run the full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes, including the `test_positions_route_returns_computed_positions` test from Task 12 which was waiting on this registration. Final count ≈ 155.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(positions): register positions blueprint in app factory"
```

---

## Task 16: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes.

- [ ] **Step 2: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```

Expected: no errors, no diffs. If `format --check` reports diffs, run `ruff format .` and commit as `chore(positions): ruff format pass`.

- [ ] **Step 3: Bring up the container and exercise end-to-end**

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/api/positions
curl -fsS http://localhost:8000/api/integrity-issues
```

Expected: `Up (healthy)`; `{"positions": []}`; `{"issues": []}`.

Drop a CSV whose `Position` column disagrees with the builder and confirm an issue surfaces:

```bash
docker compose exec -T web sh -c "cat > /app/data/inbox/NinjaTrader_Executions_20260413.csv" <<'EOF'
Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,Commission,Rate,Account,Connection,TradeValidation
MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,plan11smoke,Entry,99 L,1,n,$0.00,1,Sim101,Apex Trader Funding ,
EOF
```

Wait ~2 seconds and re-hit:

```bash
curl -fsS http://localhost:8000/api/positions
curl -fsS http://localhost:8000/api/integrity-issues
```

Expected: `/api/positions` shows one open long position with `entry_execution_id="plan11smoke"`. `/api/integrity-issues` lists one issue of type `position_column_mismatch` referencing `plan11smoke`.

- [ ] **Step 4: Bring it down**

```bash
docker compose down
```

- [ ] **Step 5: Commit any formatting fixes** (only if Step 2 reported diffs)

```bash
git status
git add -u
git commit -m "chore(positions): ruff format pass"
```

---

## Task 17: Update the rebuild-spec progress table

**Files:**
- Modify: `docs/rebuild-spec/00-README.md`

- [ ] **Step 1: Update the row and status**

Find:

```markdown
| 11 — Position Building | `build_positions` pure function, reversal splitter, `IntegrityValidator`, `integrity_issues` diff, hooked into import tick | ⏳ **Next** |
| 14 — OHLC Pipeline | `Bar` model, `OhlcSource` protocol, yfinance + Stooq adapters, circuit breaker, fetcher, gap detection, `bars` table, scheduled refresh jobs, fetch job API | ⏳ |
```

Replace with:

```markdown
| [11 — Position Building](../superpowers/plans/2026-04-13-11-position-building.md) | `build_positions` pure function, reversal splitter, `IntegrityValidator`, `integrity_issues` diff, hooked into import tick | ✅ **Complete** (2026-04-13) |
| 14 — OHLC Pipeline | `Bar` model, `OhlcSource` protocol, yfinance + Stooq adapters, circuit breaker, fetcher, gap detection, `bars` table, scheduled refresh jobs, fetch job API | ⏳ **Next** |
```

- [ ] **Step 2: Append a "What Plan 11 landed" section**

Below the existing `### What Plan 10 landed` section, append:

```markdown
### What Plan 11 landed

- **Pure `build_positions`.** `services/positions.py::build_positions(executions)` sorts by `(timestamp, nt_execution_id)`, walks once, emits one `Position` per quantity-flow cycle plus any trailing open position. Direction-reversing fills are split in-memory into `#close`/`#open` sub-fills with proportional commission. No DB access, no globals, no caching.
- **`Position` and `IntegrityIssue` models.** Typed Pydantic StrictModels keyed on the natural tuple `(account, instrument, entry_execution_id)`. No `positions` table exists — positions are computed on every read.
- **Integrity cross-check.** `services/integrity.py::cross_check_against_source_position_column` compares the builder's running quantity to the exporter's `Position` column on every execution and emits a `high`-severity `position_column_mismatch` issue whenever they disagree.
- **`run_integrity_diff` composer.** Loads executions for one `(account, instrument)`, computes issues, upserts new ones, auto-resolves stale ones (`resolved_by = 'system'`), and leaves ignored rows untouched. Plan 11's one post-tick hook on `ImportPipeline.post_tick_hooks` iterates `affected` and calls this once per pair.
- **`integrity_issues` table.** Migration 003 adds the table from doc 11 with `UNIQUE(account, instrument, execution_id, type)` and the `idx_integrity_open` partial index on `resolved_at IS NULL AND ignored = 0`.
- **Instrument multiplier stub.** `services/instruments.py::get_multiplier` ships a small dict of common futures multipliers so `dollars_pnl = points_pnl × multiplier` works today. Plan 16 replaces this with a JSON-backed registry.
- **API surface.** `/api/positions` (with `account` and `instrument` filters), `/api/positions/{account}/{instrument}/{entry_execution_id}`, `/api/integrity-issues`, `POST /api/integrity-issues/{id}/resolve`, `POST /api/integrity-issues/{id}/ignore`.
- **End-to-end verified in Docker.** Dropping a CSV with a mismatched `Position` column causes both a position (via `/api/positions`) and an integrity issue (via `/api/integrity-issues`) to appear within ~1 second.
- **No positions table, no rebuild lifecycle, no stale state.** Per Rule 1.
```

- [ ] **Step 3: Commit**

```bash
git add docs/rebuild-spec/00-README.md
git commit -m "docs(rebuild-spec): record Plan 11 completion"
```

---

## What this plan deliberately does NOT do

- **No positions table, no memoization cache.** The spec's escape hatch is to add an LRU cache keyed on `(account, instrument, max_execution_time)` *if profiling shows it's needed*. Do not ship it speculatively.
- **No `bars` table or OHLC fetching.** Plan 14. Plan 14 will register a *second* post-tick hook alongside plan 11's integrity hook.
- **No execution_notes / execution_flags / link groups.** Plan 12.
- **No custom fields / instrument registry JSON.** Plan 16. `services/instruments.py` is a stub.
- **No statistics or reports.** Plan 15.
- **No frontend templates or JS.** Plan 12 opens the first real page.
- **No monitoring dashboard.** Plan 17 consumes `integrity_issues` via the API added here.
- **No auto-resolution of ignored issues when the underlying data changes.** Per doc 11's open question resolution: ignored stays ignored until the user explicitly unignores. The API exposed here has no unignore endpoint because no such endpoint is listed in the spec — adding one is a plan 17 decision.

## Definition of done for plan 11

1. `pytest` runs green. Plan 11 adds ~65 new tests across 14 files; plan 10's suite remains green.
2. `ruff check .` and `ruff format --check .` are clean.
3. `docker compose up -d --build` brings up exactly one container and `docker compose ps` shows `Up (healthy)`.
4. Dropping a CSV whose `Position` column disagrees with the computed running quantity causes `/api/integrity-issues` to list a `position_column_mismatch` issue within ~1 second.
5. `/api/positions` and `/api/positions/{account}/{instrument}/{entry_execution_id}` return computed positions derived from `executions` via `build_positions`.
6. `POST /api/integrity-issues/{id}/resolve` marks the issue resolved by user; `POST /api/integrity-issues/{id}/ignore` (requires a `note`) marks it ignored. Both drop it from the open list.
7. Re-running `run_integrity_diff` with consistent data auto-resolves the previously-open mismatch (`resolved_by = 'system'`).
8. `docs/rebuild-spec/00-README.md` lists plan 11 as complete and plan 14 as next.

After this plan is merged, plan 14 can begin: it will add `migrations/004_bars.sql`, the OHLC adapter protocol, yfinance and Stooq adapters, the circuit breaker, and register a second post-tick hook that submits fetch jobs to the existing thread pool.
