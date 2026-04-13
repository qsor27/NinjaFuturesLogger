# Import Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the single entry point for all data in the system — a watchdog-driven tailing importer that reads `ExecutionExporter.cs` CSVs from `data/inbox/`, parses them into the `executions` table, records per-tick audit rows in `import_runs`, and never produces duplicates. Plan 10 also adds the session-end archival job, the safety-sweep scheduled tick, the import-monitoring API surface, and the execution rollback endpoint.

**Architecture:** One `ImportPipeline` class owning `ingest_tick(path)`, `scan_inbox()`, `archive_completed_sessions()`, and `rollback(execution_ids)`. Watchdog events dispatch through a thin `_TickHandler` into `ingest_tick`. A per-path `threading.Lock` registry serializes concurrent ticks on one file while leaving different files parallel. After each tick commits, the pipeline fires a list of `post_tick_hooks(tick_result, parsed, affected)` — plan 11 will register the integrity-diff hook, plan 14 will register the OHLC-fetch hook. Plan 10 ships with the hook list empty. Idempotency is enforced at the schema level by `PRIMARY KEY (nt_execution_id, account)` with `INSERT … ON CONFLICT DO NOTHING`; file state is tracked only as a byte cursor for read efficiency. Session-end archival and a 5-minute safety sweep are APScheduler jobs registered from the app factory into the existing `BackgroundServices` scheduler.

**Tech Stack:** Python 3.11, Flask 3, Pydantic v2, APScheduler 3, watchdog 4, SQLite (stdlib `sqlite3`), pytest, ruff. No new third-party deps.

## Spec references

- `docs/rebuild-spec/01-mission-and-principles.md` — The Six Rules. Rules 1 (single source of truth — executions, no positions table), 2 (business logic in services, routes are thin), 3 (pipelines explicit and traceable), 4 (typed contracts) all bear directly on this plan.
- `docs/rebuild-spec/02-glossary.md` — Execution, Action, Side (normalized), position_after, Entry/Exit, Trading session, Session date, NT ExecutionId.
- `docs/rebuild-spec/10-import-pipeline.md` — The full feature spec. This plan is the literal implementation of it.
- `docs/rebuild-spec/11-position-building.md` — Read for the shape of `run_integrity_diff`; plan 10 only defines the seam.
- `docs/rebuild-spec/90-preserved-assets.md` — The 15-column CSV contract. Immutable. The parser in this plan consumes exactly this format.
- `docs/superpowers/plans/2026-04-13-00-foundation.md` — File-layout conventions, test style, commit-message style, TDD rhythm.

## Load-bearing rules from the spec

Four decisions from doc 10 drive most of this plan. If you find yourself violating any of them, stop:

1. **Idempotency is the schema, not the code.** The composite PK `(nt_execution_id, account)` plus `INSERT … ON CONFLICT DO NOTHING` is the *only* deduplication mechanism. Do not add a pre-insert "have I seen this?" check anywhere. Duplicates are expected on every tick (overlapping reads re-present already-inserted rows) — they must be *counted* in `rows_skipped_duplicate`, never eliminated in Python.
2. **Files are not the unit of truth; executions are.** `import_cursors` is a read-efficiency optimization, not a dedup mechanism. If the cursor row is lost, re-reading from offset 0 is safe because `UNIQUE` absorbs everything. No "have I processed this filename before?" logic.
3. **Ticks do not wait for downstream work.** The tick transaction contains only the cursor update, the execution inserts, the rejects, and the `import_runs` rows. Integrity diff and OHLC fetch go to post-tick hooks that run *after* the path lock releases and the DB transaction commits.
4. **Today's file is never archived.** Only files whose filename-date is strictly earlier than the current CME trade date are eligible. The archival job takes one final safety `ingest_tick` on each eligible file before renaming it.

## File layout this plan creates or modifies

```
/
├── migrations/
│   └── 002_executions.sql           # NEW: executions, import_cursors, import_runs, import_rejects
├── models/
│   ├── execution.py                 # NEW: Execution, TickResult, RejectRecord StrictModels
│   └── __init__.py                  # MODIFY: export new models
├── services/
│   ├── csv_parser.py                # NEW: parse_execution_row, ParseError
│   ├── import_pipeline.py           # NEW: ImportPipeline class
│   ├── import_db.py                 # NEW: DB helpers (bulk_insert, cursors, runs, rejects, rollback)
│   └── time_utils.py                # MODIFY: add resolve_current_trade_date()
├── routes/
│   ├── imports.py                   # NEW: /api/imports/* and /api/executions/rollback blueprint
│   └── __init__.py                  # MODIFY (if it lists routes)
├── background.py                    # MODIFY: BackgroundServices.start() accepts watchdog handler
├── app.py                           # MODIFY: build ImportPipeline, wire handler, register jobs, register blueprint
└── tests/
    ├── conftest.py                  # MODIFY: add migrated_db and import_pipeline fixtures
    ├── test_migrations_002.py       # NEW
    ├── test_models_execution.py     # NEW
    ├── test_csv_parser.py           # NEW
    ├── test_import_db.py            # NEW
    ├── test_import_pipeline.py      # NEW (tick algorithm)
    ├── test_import_watchdog.py      # NEW (handler wiring)
    ├── test_archival.py             # NEW (session-end job)
    ├── test_safety_sweep.py         # NEW (5-minute tick-on-today)
    ├── test_routes_imports.py       # NEW (all /api/imports/* + rollback)
    └── test_app_factory_plan10.py   # NEW (end-to-end factory wiring)
```

The existing `background.py` signature change is backward-compatible: `start(handler=None)` defaults to the current `_NoopHandler`, so existing tests continue to pass.

---

## Task 1: Migration 002 — executions and import tables

**Files:**
- Create: `migrations/002_executions.sql`
- Create: `tests/test_migrations_002.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrations_002.py`:

```python
from pathlib import Path

from db import connect
from migrations import applied_versions, run_migrations


def _migrate(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def test_002_is_applied(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        assert "002_executions" in applied_versions(conn)
    finally:
        conn.close()


def test_executions_table_columns(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(executions)").fetchall()}
        assert cols == {
            "nt_execution_id", "account", "instrument", "timestamp",
            "side", "original_action", "quantity", "price", "commission",
            "entry_exit", "position_after", "source_order_id",
            "source_filename", "imported_at",
        }
    finally:
        conn.close()


def test_executions_primary_key_is_composite(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        rows = conn.execute("PRAGMA table_info(executions)").fetchall()
        pk_cols = sorted([r[1] for r in rows if r[5] > 0], key=lambda c: c)
        assert pk_cols == ["account", "nt_execution_id"]
    finally:
        conn.close()


def test_executions_on_conflict_do_nothing(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        insert = (
            "INSERT INTO executions "
            "(nt_execution_id, account, instrument, timestamp, side, "
            " original_action, quantity, price, commission, entry_exit, "
            " position_after, source_order_id, source_filename, imported_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING"
        )
        row = ("abc", "Sim101", "MNQ", 1700000000, "Buy", "Buy", 1, 4237.75,
               0.0, "Entry", "1 L", "order1", "file.csv", 1700000001)
        conn.execute(insert, row)
        conn.execute(insert, row)  # duplicate; ON CONFLICT DO NOTHING
        count = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_executions_unique_index_on_nt_execution_id(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        indexes = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='executions'"
        ).fetchall()
        names = {r[0] for r in indexes}
        assert "idx_executions_nt_execution_id" in names
        # Confirm it is UNIQUE:
        row = next(r for r in indexes if r[0] == "idx_executions_nt_execution_id")
        assert "UNIQUE" in (row[1] or "").upper()
    finally:
        conn.close()


def test_import_cursors_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_cursors)").fetchall()}
        assert cols == {"filename", "byte_offset", "last_tick_at", "last_modified"}
    finally:
        conn.close()


def test_import_runs_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_runs)").fetchall()}
        assert {"tick_id", "filename", "started_at", "finished_at",
                "cursor_before", "cursor_after", "lines_read", "rows_parsed",
                "rows_inserted", "rows_skipped_duplicate", "rows_rejected",
                "status", "error"}.issubset(cols)
    finally:
        conn.close()


def test_import_rejects_table(tmp_path: Path):
    conn = _migrate(tmp_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(import_rejects)").fetchall()}
        assert cols == {"reject_id", "tick_id", "line_number", "raw_line",
                        "reason", "created_at"}
    finally:
        conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_002.py -v
```

Expected: failures with "002_executions not in applied_versions" or "no such table: executions".

- [ ] **Step 3: Write `migrations/002_executions.sql`**

```sql
CREATE TABLE executions (
  nt_execution_id  TEXT NOT NULL,
  account          TEXT NOT NULL,
  instrument       TEXT NOT NULL,
  timestamp        INTEGER NOT NULL,
  side             TEXT NOT NULL CHECK(side IN ('Buy','Sell')),
  original_action  TEXT NOT NULL,
  quantity         INTEGER NOT NULL CHECK(quantity > 0),
  price            REAL NOT NULL,
  commission       REAL NOT NULL DEFAULT 0,
  entry_exit       TEXT NOT NULL CHECK(entry_exit IN ('Entry','Exit')),
  position_after   TEXT,
  source_order_id  TEXT,
  source_filename  TEXT NOT NULL,
  imported_at      INTEGER NOT NULL,
  PRIMARY KEY (nt_execution_id, account)
);

CREATE UNIQUE INDEX idx_executions_nt_execution_id
  ON executions(nt_execution_id);

CREATE INDEX idx_executions_account_instrument_time
  ON executions(account, instrument, timestamp);

CREATE INDEX idx_executions_timestamp
  ON executions(timestamp);

CREATE TABLE import_cursors (
  filename       TEXT PRIMARY KEY,
  byte_offset    INTEGER NOT NULL,
  last_tick_at   INTEGER NOT NULL,
  last_modified  INTEGER NOT NULL
);

CREATE TABLE import_runs (
  tick_id                INTEGER PRIMARY KEY AUTOINCREMENT,
  filename               TEXT NOT NULL,
  started_at             INTEGER NOT NULL,
  finished_at            INTEGER NOT NULL,
  cursor_before          INTEGER NOT NULL,
  cursor_after           INTEGER NOT NULL,
  lines_read             INTEGER NOT NULL,
  rows_parsed            INTEGER NOT NULL,
  rows_inserted          INTEGER NOT NULL,
  rows_skipped_duplicate INTEGER NOT NULL,
  rows_rejected          INTEGER NOT NULL,
  status                 TEXT NOT NULL CHECK(status IN ('ok','partial','failed')),
  error                  TEXT
);

CREATE INDEX idx_import_runs_filename_started
  ON import_runs(filename, started_at DESC);

CREATE TABLE import_rejects (
  reject_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_id      INTEGER NOT NULL REFERENCES import_runs(tick_id),
  line_number  INTEGER NOT NULL,
  raw_line     TEXT NOT NULL,
  reason       TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_migrations_002.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add migrations/002_executions.sql tests/test_migrations_002.py
git commit -m "feat(import): migration 002 — executions and import tables"
```

---

## Task 2: Pydantic models — Execution, TickResult, RejectRecord

**Files:**
- Create: `models/execution.py`
- Modify: `models/__init__.py`
- Create: `tests/test_models_execution.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_execution.py`:

```python
import pytest

from models.execution import Execution, RejectRecord, TickResult


def _valid_execution_kwargs():
    return dict(
        nt_execution_id="abc123",
        account="Sim101",
        instrument="MNQ",
        timestamp=1_700_000_000,
        side="Buy",
        original_action="Buy",
        quantity=3,
        price=4237.75,
        commission=0.50,
        entry_exit="Entry",
        position_after="3 L",
        source_order_id="ord1",
        source_filename="NinjaTrader_Executions_20260413.csv",
        imported_at=1_700_000_001,
    )


def test_execution_accepts_valid_values():
    e = Execution(**_valid_execution_kwargs())
    assert e.side == "Buy"
    assert e.quantity == 3


def test_execution_rejects_unknown_field():
    kwargs = _valid_execution_kwargs()
    kwargs["bogus"] = 1
    with pytest.raises(Exception):
        Execution(**kwargs)


def test_execution_rejects_invalid_side():
    kwargs = _valid_execution_kwargs()
    kwargs["side"] = "BuyToCover"  # must be normalized before this point
    with pytest.raises(Exception):
        Execution(**kwargs)


def test_execution_rejects_zero_quantity():
    kwargs = _valid_execution_kwargs()
    kwargs["quantity"] = 0
    with pytest.raises(Exception):
        Execution(**kwargs)


def test_execution_allows_null_position_after():
    kwargs = _valid_execution_kwargs()
    kwargs["position_after"] = None
    e = Execution(**kwargs)
    assert e.position_after is None


def test_tick_result_basic():
    r = TickResult(
        filename="f.csv",
        status="ok",
        lines_read=10,
        rows_parsed=10,
        rows_inserted=8,
        rows_skipped_duplicate=2,
        rows_rejected=0,
        cursor_before=0,
        cursor_after=1234,
        tick_id=1,
        error=None,
    )
    assert r.status == "ok"


def test_tick_result_rejects_bad_status():
    with pytest.raises(Exception):
        TickResult(
            filename="f.csv",
            status="bogus",
            lines_read=0,
            rows_parsed=0,
            rows_inserted=0,
            rows_skipped_duplicate=0,
            rows_rejected=0,
            cursor_before=0,
            cursor_after=0,
            tick_id=None,
            error=None,
        )


def test_reject_record_shape():
    r = RejectRecord(line_number=7, raw_line="oops", reason="bad column count")
    assert r.line_number == 7
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_execution.py -v
```

Expected: `ModuleNotFoundError: No module named 'models.execution'`.

- [ ] **Step 3: Implement `models/execution.py`**

```python
from typing import Literal

from models.base import StrictModel

Side = Literal["Buy", "Sell"]
EntryExit = Literal["Entry", "Exit"]
TickStatus = Literal["ok", "partial", "failed"]


class Execution(StrictModel):
    nt_execution_id: str
    account: str
    instrument: str
    timestamp: int
    side: Side
    original_action: str
    quantity: int
    price: float
    commission: float
    entry_exit: EntryExit
    position_after: str | None
    source_order_id: str | None
    source_filename: str
    imported_at: int

    def model_post_init(self, _context) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


class RejectRecord(StrictModel):
    line_number: int
    raw_line: str
    reason: str


class TickResult(StrictModel):
    filename: str
    status: TickStatus
    lines_read: int
    rows_parsed: int
    rows_inserted: int
    rows_skipped_duplicate: int
    rows_rejected: int
    cursor_before: int
    cursor_after: int
    tick_id: int | None
    error: str | None
```

- [ ] **Step 4: Update `models/__init__.py`**

```python
from models.base import StrictModel
from models.execution import Execution, RejectRecord, TickResult

__all__ = ["StrictModel", "Execution", "RejectRecord", "TickResult"]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_models_execution.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add models/execution.py models/__init__.py tests/test_models_execution.py
git commit -m "feat(import): typed Execution/TickResult/RejectRecord models"
```

---

## Task 3: CSV row parser

The parser consumes one line of the 15-column format documented in `docs/rebuild-spec/90-preserved-assets.md`. It uses the stdlib `csv` reader (RFC 4180 quoting), normalizes `Action` → `side`, parses the `M/d/yyyy h:mm:ss tt` US format with the trader's timezone (we reuse `config.session.exchange_timezone`, which defaults to `America/Chicago`), and raises `ParseError` on any per-row failure. `ParseError` is the only exception the caller needs to catch — every reject reason must be human-readable enough for `import_rejects.reason` to be debugged without reading code.

**Files:**
- Create: `services/csv_parser.py`
- Create: `tests/test_csv_parser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_csv_parser.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.csv_parser import ParseError, parse_execution_row

TRADER_TZ = ZoneInfo("America/Chicago")
IMPORTED_AT = 1_700_000_000
SRC = "NinjaTrader_Executions_20260413.csv"


def _parse(line: str):
    return parse_execution_row(
        line,
        source_filename=SRC,
        trader_tz=TRADER_TZ,
        imported_at=IMPORTED_AT,
    )


def test_parse_basic_buy_row():
    line = (
        "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM,abc123,Entry,3 L,"
        "12345,Manual Entry,$5.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.instrument == "MNQ"
    assert e.original_action == "Buy"
    assert e.side == "Buy"
    assert e.quantity == 3
    assert e.price == 4237.75
    assert e.nt_execution_id == "abc123"
    assert e.entry_exit == "Entry"
    assert e.position_after == "3 L"
    assert e.source_order_id == "12345"
    assert e.commission == 5.0
    assert e.account == "Sim101"
    assert e.source_filename == SRC
    assert e.imported_at == IMPORTED_AT
    expected = int(
        datetime(2025, 1, 15, 14, 45, 30, tzinfo=TRADER_TZ).timestamp()
    )
    assert e.timestamp == expected


def test_parse_normalizes_buy_to_cover_to_buy_side():
    line = (
        "ES,BuyToCover,2,5000.25,2/3/2025 9:00:00 AM,xid,Exit,-,"
        "9,Exit,$0.50,1,Sim101,Apex Trader Funding ,Valid"
    )
    e = _parse(line)
    assert e.original_action == "BuyToCover"
    assert e.side == "Buy"
    assert e.position_after == "-"


def test_parse_normalizes_sell_short_to_sell_side():
    line = (
        "CL,SellShort,1,72.34,3/10/2025 11:30:15 AM,xid,Entry,1 S,"
        "7,Short,$1.00,1,APEX-1,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.original_action == "SellShort"
    assert e.side == "Sell"


def test_parse_handles_rfc4180_quoted_field_with_comma():
    line = (
        'MNQ,Buy,1,4100.00,5/5/2025 10:00:00 AM,qid,Entry,1 L,'
        '1,"Name, with comma",$0.00,1,Sim101,Apex Trader Funding ,'
    )
    e = _parse(line)
    assert e.quantity == 1


def test_parse_rejects_wrong_column_count():
    line = "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM"
    with pytest.raises(ParseError, match="15 columns"):
        _parse(line)


def test_parse_rejects_unknown_action():
    line = (
        "MNQ,Teleport,1,4000,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="action"):
        _parse(line)


def test_parse_rejects_bad_quantity():
    line = (
        "MNQ,Buy,abc,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="quantity"):
        _parse(line)


def test_parse_rejects_zero_quantity():
    line = (
        "MNQ,Buy,0,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="quantity"):
        _parse(line)


def test_parse_rejects_bad_price():
    line = (
        "MNQ,Buy,1,notaprice,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="price"):
        _parse(line)


def test_parse_rejects_bad_time():
    line = (
        "MNQ,Buy,1,4237.75,yesterday,id,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="time"):
        _parse(line)


def test_parse_rejects_bad_entry_exit():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Maybe,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="E/X"):
        _parse(line)


def test_parse_rejects_empty_execution_id():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="execution id"):
        _parse(line)


def test_parse_rejects_empty_account():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,$0.00,1,,Apex Trader Funding ,"
    )
    with pytest.raises(ParseError, match="account"):
        _parse(line)


def test_parse_commission_with_no_dollar_prefix_still_accepted():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,2.50,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.commission == 2.50


def test_parse_empty_commission_becomes_zero():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,1 L,"
        "1,n,,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.commission == 0.0


def test_parse_empty_position_after_becomes_none():
    line = (
        "MNQ,Buy,1,4237.75,1/15/2025 2:45:30 PM,id,Entry,,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.position_after is None


def test_parse_dash_position_after_is_preserved_verbatim():
    line = (
        "MNQ,Sell,1,4237.75,1/15/2025 2:45:30 PM,id,Exit,-,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,"
    )
    e = _parse(line)
    assert e.position_after == "-"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_csv_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.csv_parser'`.

- [ ] **Step 3: Implement `services/csv_parser.py`**

```python
import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from models.execution import Execution

_VALID_ACTIONS = {"Buy", "Sell", "BuyToCover", "SellShort"}
_ACTION_TO_SIDE = {
    "Buy": "Buy",
    "BuyToCover": "Buy",
    "Sell": "Sell",
    "SellShort": "Sell",
}
_EXPECTED_COLS = 15
_TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


class ParseError(ValueError):
    """Raised for any per-row parse failure. The message becomes import_rejects.reason."""


def parse_execution_row(
    line: str,
    *,
    source_filename: str,
    trader_tz: ZoneInfo,
    imported_at: int,
) -> Execution:
    """Parse one line of the ExecutionExporter.cs CSV format (doc 90)."""
    try:
        fields = next(csv.reader(io.StringIO(line)))
    except StopIteration as e:
        raise ParseError("empty line") from e

    if len(fields) != _EXPECTED_COLS:
        raise ParseError(f"expected {_EXPECTED_COLS} columns, got {len(fields)}")

    (
        instrument,
        action,
        qty_s,
        price_s,
        time_s,
        exec_id,
        entry_exit,
        position,
        order_id,
        _name,
        commission_s,
        _rate,
        account,
        _connection,
        _validation,
    ) = fields

    if action not in _VALID_ACTIONS:
        raise ParseError(f"invalid action: {action!r}")
    side = _ACTION_TO_SIDE[action]

    try:
        quantity = int(qty_s)
    except ValueError as e:
        raise ParseError(f"invalid quantity: {qty_s!r}") from e
    if quantity <= 0:
        raise ParseError(f"non-positive quantity: {quantity}")

    try:
        price = float(price_s)
    except ValueError as e:
        raise ParseError(f"invalid price: {price_s!r}") from e

    try:
        local_naive = datetime.strptime(time_s, _TIME_FORMAT)
    except ValueError as e:
        raise ParseError(f"invalid time: {time_s!r}") from e
    local_aware = local_naive.replace(tzinfo=trader_tz)
    timestamp = int(local_aware.timestamp())

    if entry_exit not in {"Entry", "Exit"}:
        raise ParseError(f"invalid E/X: {entry_exit!r}")

    commission_clean = commission_s.lstrip("$").strip() or "0"
    try:
        commission = float(commission_clean)
    except ValueError as e:
        raise ParseError(f"invalid commission: {commission_s!r}") from e

    if not exec_id:
        raise ParseError("empty execution id")
    if not account:
        raise ParseError("empty account")

    return Execution(
        nt_execution_id=exec_id,
        account=account,
        instrument=instrument,
        timestamp=timestamp,
        side=side,
        original_action=action,
        quantity=quantity,
        price=price,
        commission=commission,
        entry_exit=entry_exit,
        position_after=(position or None),
        source_order_id=(order_id or None),
        source_filename=source_filename,
        imported_at=imported_at,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_csv_parser.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add services/csv_parser.py tests/test_csv_parser.py
git commit -m "feat(import): CSV row parser for ExecutionExporter format"
```

---

## Task 4: Import DB helpers

The pipeline needs tight, typed SQL helpers that know nothing about file I/O. Keeping them in a separate module makes the tick algorithm trivially testable (the tick test can use a real migrated SQLite DB in `tmp_path`) and keeps the `ImportPipeline` class small.

**Files:**
- Create: `services/import_db.py`
- Create: `tests/test_import_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_import_db.py`:

```python
from pathlib import Path

from db import connect
from migrations import run_migrations
from models.execution import Execution, RejectRecord
from services.import_db import (
    bulk_insert_executions,
    delete_cursor,
    delete_executions,
    get_cursor,
    insert_rejects,
    record_run,
    save_cursor,
)


def _migrated(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    run_migrations(conn, Path("migrations"))
    return conn


def _ex(i: int, account: str = "Sim101"):
    return Execution(
        nt_execution_id=f"id-{i}",
        account=account,
        instrument="MNQ",
        timestamp=1_700_000_000 + i,
        side="Buy",
        original_action="Buy",
        quantity=1,
        price=4000.0 + i,
        commission=0.0,
        entry_exit="Entry",
        position_after=f"{i} L",
        source_order_id=None,
        source_filename="file.csv",
        imported_at=1_700_000_100,
    )


def test_cursor_lifecycle(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        assert get_cursor(conn, "file.csv") is None
        save_cursor(conn, "file.csv", byte_offset=123, file_mtime=456)
        assert get_cursor(conn, "file.csv") == 123
        save_cursor(conn, "file.csv", byte_offset=456, file_mtime=789)
        assert get_cursor(conn, "file.csv") == 456
        delete_cursor(conn, "file.csv")
        assert get_cursor(conn, "file.csv") is None
    finally:
        conn.close()


def test_bulk_insert_counts_inserted_and_skipped(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        rows = [_ex(1), _ex(2), _ex(3)]
        inserted, skipped = bulk_insert_executions(conn, rows)
        assert inserted == 3
        assert skipped == 0
        # Re-inserting the same rows should all be skipped.
        inserted, skipped = bulk_insert_executions(conn, rows)
        assert inserted == 0
        assert skipped == 3
        # Mixed: two existing + one new.
        inserted, skipped = bulk_insert_executions(conn, [_ex(2), _ex(4)])
        assert inserted == 1
        assert skipped == 1
    finally:
        conn.close()


def test_bulk_insert_empty_list_is_noop(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        inserted, skipped = bulk_insert_executions(conn, [])
        assert (inserted, skipped) == (0, 0)
    finally:
        conn.close()


def test_record_run_and_insert_rejects(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        tick_id = record_run(
            conn,
            filename="file.csv",
            started_at=100,
            finished_at=101,
            cursor_before=0,
            cursor_after=500,
            lines_read=3,
            rows_parsed=2,
            rows_inserted=2,
            rows_skipped_duplicate=0,
            rows_rejected=1,
            status="ok",
            error=None,
        )
        assert isinstance(tick_id, int) and tick_id > 0
        insert_rejects(
            conn,
            tick_id,
            [RejectRecord(line_number=3, raw_line="oops", reason="bad cols")],
        )
        row = conn.execute(
            "SELECT filename, status, rows_inserted FROM import_runs WHERE tick_id=?",
            (tick_id,),
        ).fetchone()
        assert row["filename"] == "file.csv"
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 2
        rej = conn.execute(
            "SELECT line_number, raw_line, reason FROM import_rejects WHERE tick_id=?",
            (tick_id,),
        ).fetchall()
        assert len(rej) == 1
        assert rej[0]["line_number"] == 3
    finally:
        conn.close()


def test_delete_executions_removes_only_matches(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        bulk_insert_executions(conn, [_ex(1), _ex(2), _ex(3)])
        deleted = delete_executions(conn, ["id-1", "id-3"])
        assert deleted == 2
        remaining = [
            r[0] for r in conn.execute(
                "SELECT nt_execution_id FROM executions ORDER BY nt_execution_id"
            ).fetchall()
        ]
        assert remaining == ["id-2"]
    finally:
        conn.close()


def test_delete_executions_empty_list(tmp_path: Path):
    conn = _migrated(tmp_path)
    try:
        assert delete_executions(conn, []) == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_import_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.import_db'`.

- [ ] **Step 3: Implement `services/import_db.py`**

```python
import sqlite3
import time
from collections.abc import Iterable, Sequence

from models.execution import Execution, RejectRecord

_INSERT_EXECUTION_SQL = (
    "INSERT INTO executions ("
    " nt_execution_id, account, instrument, timestamp, side,"
    " original_action, quantity, price, commission, entry_exit,"
    " position_after, source_order_id, source_filename, imported_at"
    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING"
)


def get_cursor(conn: sqlite3.Connection, filename: str) -> int | None:
    row = conn.execute(
        "SELECT byte_offset FROM import_cursors WHERE filename = ?",
        (filename,),
    ).fetchone()
    return int(row[0]) if row is not None else None


def save_cursor(
    conn: sqlite3.Connection,
    filename: str,
    *,
    byte_offset: int,
    file_mtime: int,
) -> None:
    conn.execute(
        "INSERT INTO import_cursors (filename, byte_offset, last_tick_at, last_modified) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(filename) DO UPDATE SET "
        " byte_offset = excluded.byte_offset,"
        " last_tick_at = excluded.last_tick_at,"
        " last_modified = excluded.last_modified",
        (filename, byte_offset, int(time.time()), file_mtime),
    )


def delete_cursor(conn: sqlite3.Connection, filename: str) -> None:
    conn.execute("DELETE FROM import_cursors WHERE filename = ?", (filename,))


def bulk_insert_executions(
    conn: sqlite3.Connection,
    executions: Sequence[Execution],
) -> tuple[int, int]:
    """Insert executions with ON CONFLICT DO NOTHING.

    Returns (inserted, skipped). Because SQLite's conflict resolution doesn't
    report per-row status, we count by comparing total_changes before/after.
    """
    if not executions:
        return (0, 0)
    inserted = 0
    for e in executions:
        before = conn.total_changes
        conn.execute(
            _INSERT_EXECUTION_SQL,
            (
                e.nt_execution_id, e.account, e.instrument, e.timestamp, e.side,
                e.original_action, e.quantity, e.price, e.commission, e.entry_exit,
                e.position_after, e.source_order_id, e.source_filename, e.imported_at,
            ),
        )
        if conn.total_changes > before:
            inserted += 1
    skipped = len(executions) - inserted
    return (inserted, skipped)


def insert_rejects(
    conn: sqlite3.Connection,
    tick_id: int,
    rejects: Iterable[RejectRecord],
) -> None:
    now = int(time.time())
    conn.executemany(
        "INSERT INTO import_rejects (tick_id, line_number, raw_line, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(tick_id, r.line_number, r.raw_line, r.reason, now) for r in rejects],
    )


def record_run(
    conn: sqlite3.Connection,
    *,
    filename: str,
    started_at: int,
    finished_at: int,
    cursor_before: int,
    cursor_after: int,
    lines_read: int,
    rows_parsed: int,
    rows_inserted: int,
    rows_skipped_duplicate: int,
    rows_rejected: int,
    status: str,
    error: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO import_runs ("
        " filename, started_at, finished_at, cursor_before, cursor_after,"
        " lines_read, rows_parsed, rows_inserted, rows_skipped_duplicate,"
        " rows_rejected, status, error"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            filename, started_at, finished_at, cursor_before, cursor_after,
            lines_read, rows_parsed, rows_inserted, rows_skipped_duplicate,
            rows_rejected, status, error,
        ),
    )
    return int(cur.lastrowid)


def delete_executions(
    conn: sqlite3.Connection,
    nt_execution_ids: Sequence[str],
) -> int:
    if not nt_execution_ids:
        return 0
    placeholders = ",".join("?" for _ in nt_execution_ids)
    cur = conn.execute(
        f"DELETE FROM executions WHERE nt_execution_id IN ({placeholders})",
        tuple(nt_execution_ids),
    )
    return int(cur.rowcount)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_import_db.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add services/import_db.py tests/test_import_db.py
git commit -m "feat(import): SQLite helpers for executions and import audit tables"
```

---

## Task 5: `ImportPipeline.ingest_tick` core algorithm

This task is the heart of the plan. The tick function is specified in doc 10 as concrete Python; we implement it faithfully. Notable properties:

- Per-path locking uses a `dict[str, threading.Lock]` guarded by an outer `threading.Lock`. This serializes concurrent ticks on one file while leaving different files parallel.
- File shrinkage resets the cursor to 0; `UNIQUE` absorbs duplicates.
- The header line is dropped only on the first tick (cursor == 0).
- The DB transaction contains only: cursor update, execution inserts, rejects, `import_runs` row. Post-tick hooks run *after* commit, *outside* the path lock.
- Post-tick hooks are a list of callables `(tick_result, parsed, affected) -> None`. Plan 10 ships an empty list; plans 11 and 14 will append. Because plan 10 cannot yet submit to the thread pool meaningfully, we still pass `pool` in so plan 14's hook can use it.

**Files:**
- Create: `services/import_pipeline.py`
- Create: `tests/test_import_pipeline.py`
- Modify: `tests/conftest.py` — add a `migrated_db` helper fixture used by tick tests.

- [ ] **Step 1: Update `tests/conftest.py` — add migrated-DB fixture**

Append to `tests/conftest.py`:

```python
from db import connect
from migrations import run_migrations
from pathlib import Path as _Path


@pytest.fixture
def migrated_db(tmp_path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, _Path("migrations"))
    try:
        yield db_path
    finally:
        conn.close()
```

Note the `_Path` alias — `Path` is already imported at the top of the existing conftest; if it is not, add `from pathlib import Path` at the top instead of aliasing.

- [ ] **Step 2: Write the failing test**

Create `tests/test_import_pipeline.py`:

```python
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from db import connect
from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")

HEADER = (
    "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
    "Commission,Rate,Account,Connection,TradeValidation\n"
)
ROW1 = (
    "MNQ,Buy,3,4237.75,1/15/2025 2:45:30 PM,abc123,Entry,3 L,"
    "12345,Manual Entry,$5.00,1,Sim101,Apex Trader Funding ,\n"
)
ROW2 = (
    "MNQ,Sell,3,4240.00,1/15/2025 3:00:00 PM,abc124,Exit,-,"
    "12346,Manual Exit,$5.00,1,Sim101,Apex Trader Funding ,\n"
)
BAD_ROW = (
    "MNQ,Teleport,1,4000,1/15/2025 2:45:30 PM,badid,Entry,1 L,"
    "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
)


def _pipeline(db_path: Path, hooks=None):
    return ImportPipeline(
        db_path=db_path,
        trader_tz=TZ,
        post_tick_hooks=hooks or [],
    )


def _count_executions(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    finally:
        conn.close()


def test_first_tick_drops_header_and_inserts_rows(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + ROW2, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.status == "ok"
    assert result.rows_parsed == 2
    assert result.rows_inserted == 2
    assert result.rows_skipped_duplicate == 0
    assert result.rows_rejected == 0
    assert _count_executions(migrated_db) == 2


def test_second_tick_is_noop_when_file_unchanged(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    result = pipeline.ingest_tick(path)
    assert result.lines_read == 0
    assert result.rows_inserted == 0
    assert _count_executions(migrated_db) == 1


def test_tick_resumes_from_cursor_when_rows_are_appended(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(ROW2)
    result = pipeline.ingest_tick(path)
    assert result.rows_parsed == 1
    assert result.rows_inserted == 1
    assert _count_executions(migrated_db) == 2


def test_tick_ignores_trailing_partial_line(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + "MNQ,Buy,3", encoding="utf-8")  # partial
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
    # Now complete the line:
    with path.open("a", encoding="utf-8") as f:
        f.write(",4240.00,1/15/2025 3:00:00 PM,zid,Exit,-,"
                "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n")
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
    assert _count_executions(migrated_db) == 2


def test_tick_returns_partial_when_no_newline_seen_yet(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("Instrument,Action,", encoding="utf-8")  # no \n at all
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.status == "partial"
    assert result.rows_inserted == 0


def test_tick_records_reject_rows(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + BAD_ROW, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    assert result.rows_parsed == 1
    assert result.rows_rejected == 1
    conn = connect(migrated_db)
    try:
        rejects = conn.execute(
            "SELECT reason FROM import_rejects WHERE tick_id = ?",
            (result.tick_id,),
        ).fetchall()
        assert len(rejects) == 1
        assert "action" in rejects[0]["reason"]
    finally:
        conn.close()


def test_tick_shrinking_file_resets_cursor(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1 + ROW2, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    pipeline.ingest_tick(path)
    # Shrink the file back to just header + ROW1:
    path.write_text(HEADER + ROW1, encoding="utf-8")
    result = pipeline.ingest_tick(path)
    # Cursor reset to 0 → re-read ROW1 which gets absorbed as duplicate.
    assert result.rows_inserted == 0
    assert result.rows_skipped_duplicate == 1


def test_tick_records_row_in_import_runs(tmp_path: Path, migrated_db: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db)
    result = pipeline.ingest_tick(path)
    conn = connect(migrated_db)
    try:
        row = conn.execute(
            "SELECT filename, status, rows_inserted, cursor_before, cursor_after "
            "FROM import_runs WHERE tick_id = ?",
            (result.tick_id,),
        ).fetchone()
        assert row["filename"] == path.name
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 1
        assert row["cursor_before"] == 0
        assert row["cursor_after"] > 0
    finally:
        conn.close()


def test_post_tick_hook_fires_after_commit(tmp_path: Path, migrated_db: Path):
    calls = []

    def hook(result, parsed, affected):
        calls.append((result.rows_inserted, len(parsed), affected))

    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db, hooks=[hook])
    pipeline.ingest_tick(path)
    assert len(calls) == 1
    rows_inserted, parsed_count, affected = calls[0]
    assert rows_inserted == 1
    assert parsed_count == 1
    assert ("Sim101", "MNQ") in affected


def test_post_tick_hook_exception_does_not_break_tick(tmp_path: Path, migrated_db: Path):
    def bad_hook(*_a, **_kw):
        raise RuntimeError("boom")

    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text(HEADER + ROW1, encoding="utf-8")
    pipeline = _pipeline(migrated_db, hooks=[bad_hook])
    # Should not raise — hook errors are logged and swallowed so one bad hook
    # can't block ingestion.
    result = pipeline.ingest_tick(path)
    assert result.rows_inserted == 1
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_import_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.import_pipeline'`.

- [ ] **Step 4: Implement `services/import_pipeline.py`**

```python
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect
from logging_config import get_logger
from models.execution import Execution, RejectRecord, TickResult
from services.csv_parser import ParseError, parse_execution_row
from services.import_db import (
    bulk_insert_executions,
    delete_cursor,
    delete_executions,
    get_cursor,
    insert_rejects,
    record_run,
    save_cursor,
)

log = get_logger("import.pipeline")

PostTickHook = Callable[[TickResult, list[Execution], set[tuple[str, str]]], None]


class ImportPipeline:
    """Single entry point for all data. One instance per process."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        trader_tz: ZoneInfo,
        post_tick_hooks: list[PostTickHook] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.trader_tz = trader_tz
        self.post_tick_hooks: list[PostTickHook] = list(post_tick_hooks or [])
        self._path_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ public

    def ingest_tick(self, path: Path) -> TickResult:
        """Read any new bytes from `path`, parse complete lines, insert executions."""
        path = Path(path)
        filename = path.name
        started_at = int(time.time())

        with self._lock_for(filename):
            tick_result, parsed = self._run_tick(path, filename, started_at)

        if parsed:
            affected = {(e.account, e.instrument) for e in parsed}
        else:
            affected = set()
        self._fire_hooks(tick_result, parsed, affected)
        return tick_result

    def scan_inbox(self, inbox_dir: Path | str) -> list[TickResult]:
        results: list[TickResult] = []
        for p in sorted(Path(inbox_dir).glob("NinjaTrader_Executions_*.csv")):
            try:
                results.append(self.ingest_tick(p))
            except Exception as e:
                log.exception("scan_inbox: tick failed", extra={"path": str(p)})
                results.append(TickResult(
                    filename=p.name,
                    status="failed",
                    lines_read=0, rows_parsed=0, rows_inserted=0,
                    rows_skipped_duplicate=0, rows_rejected=0,
                    cursor_before=0, cursor_after=0,
                    tick_id=None, error=str(e),
                ))
        return results

    def rollback(self, nt_execution_ids: Sequence[str]) -> int:
        """Delete executions by NT ExecutionId. Integrity diff is plan 11's problem."""
        conn = connect(self.db_path)
        try:
            conn.execute("BEGIN")
            try:
                deleted = delete_executions(conn, nt_execution_ids)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return deleted

    def archive_completed_sessions(
        self,
        *,
        inbox_dir: Path | str,
        archive_dir: Path | str,
        current_trade_date,
    ) -> list[Path]:
        """Rename yesterday-and-earlier files into archive/YYYY-MM-DD/.

        Caller supplies the current CME trade date so this function remains a
        pure file-mover. Before renaming each eligible file we take one final
        safety-net ingest_tick so end-of-session writes are not orphaned.
        """
        from datetime import date as _date  # local to avoid polluting module top
        inbox = Path(inbox_dir)
        archive = Path(archive_dir)
        moved: list[Path] = []
        for path in sorted(inbox.glob("NinjaTrader_Executions_*.csv")):
            file_date = _parse_date_from_filename(path.name)
            if file_date is None:
                continue
            if not isinstance(current_trade_date, _date):
                raise TypeError("current_trade_date must be a date")
            if file_date >= current_trade_date:
                continue
            self.ingest_tick(path)
            dest_dir = archive / file_date.isoformat()
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / path.name
            path.rename(dest)
            conn = connect(self.db_path)
            try:
                conn.execute("BEGIN")
                try:
                    delete_cursor(conn, path.name)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
            moved.append(dest)
            log.info("archived", extra={"filename": path.name, "dest": str(dest)})
        return moved

    # ----------------------------------------------------------------- internals

    def _lock_for(self, filename: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._path_locks.get(filename)
            if lock is None:
                lock = threading.Lock()
                self._path_locks[filename] = lock
            return lock

    def _run_tick(
        self,
        path: Path,
        filename: str,
        started_at: int,
    ) -> tuple[TickResult, list[Execution]]:
        conn = connect(self.db_path)
        try:
            cursor = get_cursor(conn, filename) or 0
            size = path.stat().st_size
            mtime = int(path.stat().st_mtime)

            if size < cursor:
                log.warning(
                    "file shrank, resetting cursor",
                    extra={"filename": filename, "old": cursor, "new": size},
                )
                cursor = 0

            if size == cursor:
                return self._finish(
                    conn, path, filename, started_at, cursor, cursor,
                    lines=[], parsed=[], rejects=[], status="ok",
                    mtime=mtime,
                )

            with open(path, "rb") as f:
                f.seek(cursor)
                chunk = f.read(size - cursor)

            last_nl = chunk.rfind(b"\n")
            if last_nl == -1:
                return self._finish(
                    conn, path, filename, started_at, cursor, cursor,
                    lines=[], parsed=[], rejects=[], status="partial",
                    mtime=mtime,
                )

            complete = chunk[: last_nl + 1]
            new_cursor = cursor + len(complete)
            try:
                text = complete.decode("utf-8")
            except UnicodeDecodeError as e:
                # Entire chunk unreadable — treat as failed tick, record it, advance cursor
                # so we don't get stuck. This is extremely unlikely (exporter writes ASCII).
                log.exception("decode error", extra={"filename": filename})
                tick_id = record_run(
                    conn,
                    filename=filename,
                    started_at=started_at,
                    finished_at=int(time.time()),
                    cursor_before=cursor,
                    cursor_after=new_cursor,
                    lines_read=0,
                    rows_parsed=0,
                    rows_inserted=0,
                    rows_skipped_duplicate=0,
                    rows_rejected=0,
                    status="failed",
                    error=f"decode: {e}",
                )
                save_cursor(conn, filename, byte_offset=new_cursor, file_mtime=mtime)
                return (
                    TickResult(
                        filename=filename, status="failed",
                        lines_read=0, rows_parsed=0, rows_inserted=0,
                        rows_skipped_duplicate=0, rows_rejected=0,
                        cursor_before=cursor, cursor_after=new_cursor,
                        tick_id=tick_id, error=f"decode: {e}",
                    ),
                    [],
                )
            lines = text.splitlines()

            if cursor == 0 and lines and lines[0].startswith("Instrument"):
                lines = lines[1:]

            parsed: list[Execution] = []
            rejects: list[RejectRecord] = []
            imported_at = int(time.time())
            for i, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    parsed.append(
                        parse_execution_row(
                            line,
                            source_filename=filename,
                            trader_tz=self.trader_tz,
                            imported_at=imported_at,
                        )
                    )
                except ParseError as e:
                    rejects.append(RejectRecord(
                        line_number=i, raw_line=line, reason=str(e),
                    ))

            return self._finish(
                conn, path, filename, started_at, cursor, new_cursor,
                lines=lines, parsed=parsed, rejects=rejects, status="ok",
                mtime=mtime,
            )
        finally:
            conn.close()

    def _finish(
        self,
        conn,
        path: Path,
        filename: str,
        started_at: int,
        cursor_before: int,
        cursor_after: int,
        *,
        lines: list[str],
        parsed: list[Execution],
        rejects: list[RejectRecord],
        status: str,
        mtime: int,
    ) -> tuple[TickResult, list[Execution]]:
        conn.execute("BEGIN")
        try:
            inserted, skipped = bulk_insert_executions(conn, parsed)
            tick_id = record_run(
                conn,
                filename=filename,
                started_at=started_at,
                finished_at=int(time.time()),
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                lines_read=len(lines),
                rows_parsed=len(parsed),
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped,
                rows_rejected=len(rejects),
                status=status,
                error=None,
            )
            if rejects:
                insert_rejects(conn, tick_id, rejects)
            save_cursor(conn, filename, byte_offset=cursor_after, file_mtime=mtime)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return (
            TickResult(
                filename=filename,
                status=status,
                lines_read=len(lines),
                rows_parsed=len(parsed),
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped,
                rows_rejected=len(rejects),
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                tick_id=tick_id,
                error=None,
            ),
            parsed,
        )

    def _fire_hooks(
        self,
        result: TickResult,
        parsed: list[Execution],
        affected: set[tuple[str, str]],
    ) -> None:
        for hook in self.post_tick_hooks:
            try:
                hook(result, parsed, affected)
            except Exception:
                log.exception("post-tick hook failed", extra={"hook": repr(hook)})


def _parse_date_from_filename(name: str):
    """`NinjaTrader_Executions_YYYYMMDD.csv` → date, or None if pattern mismatched."""
    from datetime import date
    prefix = "NinjaTrader_Executions_"
    suffix = ".csv"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    core = name[len(prefix):-len(suffix)]
    if len(core) != 8 or not core.isdigit():
        return None
    try:
        return date(int(core[:4]), int(core[4:6]), int(core[6:8]))
    except ValueError:
        return None
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_import_pipeline.py -v
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add services/import_pipeline.py tests/test_import_pipeline.py tests/conftest.py
git commit -m "feat(import): ImportPipeline.ingest_tick tailing algorithm"
```

---

## Task 6: Watchdog handler wiring into BackgroundServices

`BackgroundServices.start()` currently hardcodes `_NoopHandler`. Plan 10 replaces it by letting the caller inject a handler, defaulting to the existing `_NoopHandler` so the foundation tests remain green. The new `_TickHandler` calls `ImportPipeline.ingest_tick` on every `on_created` / `on_modified` event for files matching `NinjaTrader_Executions_*.csv`.

**Files:**
- Modify: `background.py`
- Create: `services/import_watchdog.py`
- Create: `tests/test_import_watchdog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_import_watchdog.py`:

```python
import time
from pathlib import Path
from unittest.mock import MagicMock

from watchdog.events import FileCreatedEvent, FileModifiedEvent

from services.import_watchdog import TickHandler


def test_tick_handler_calls_ingest_on_created(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_created(FileCreatedEvent(str(path)))
    pipeline.ingest_tick.assert_called_once_with(path)


def test_tick_handler_calls_ingest_on_modified(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_modified(FileModifiedEvent(str(path)))
    pipeline.ingest_tick.assert_called_once_with(path)


def test_tick_handler_ignores_non_matching_filenames(tmp_path: Path):
    path = tmp_path / "some_other_file.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    handler.on_modified(FileModifiedEvent(str(path)))
    pipeline.ingest_tick.assert_not_called()


def test_tick_handler_ignores_directory_events(tmp_path: Path):
    pipeline = MagicMock()
    handler = TickHandler(pipeline)
    # watchdog emits these for directories; we must not dispatch.
    from watchdog.events import DirModifiedEvent
    handler.on_modified(DirModifiedEvent(str(tmp_path)))
    pipeline.ingest_tick.assert_not_called()


def test_tick_handler_swallows_pipeline_errors(tmp_path: Path):
    path = tmp_path / "NinjaTrader_Executions_20260413.csv"
    path.write_text("", encoding="utf-8")
    pipeline = MagicMock()
    pipeline.ingest_tick.side_effect = RuntimeError("boom")
    handler = TickHandler(pipeline)
    # Must not raise — watchdog threads should never die from a bad tick.
    handler.on_modified(FileModifiedEvent(str(path)))
    assert pipeline.ingest_tick.called


def test_background_services_accepts_injected_handler(tmp_path: Path):
    from background import BackgroundServices
    from config import Config, SchedulerConfig, SessionConfig, ThreadPoolConfig

    cfg = Config(
        data_dir=str(tmp_path),
        db_path=str(tmp_path / "t.db"),
        inbox_dir=str(tmp_path / "inbox"),
        archive_dir=str(tmp_path / "archive"),
        log_dir=str(tmp_path / "logs"),
        session=SessionConfig(exchange_timezone="America/Chicago",
                              trade_date_rollover="16:00", archive_job_time="18:00"),
        thread_pool=ThreadPoolConfig(max_workers=2),
        scheduler=SchedulerConfig(heartbeat_seconds=60),
    )
    Path(cfg.inbox_dir).mkdir()
    services = BackgroundServices(cfg)
    pipeline = MagicMock()
    services.start(handler=TickHandler(pipeline))
    try:
        time.sleep(0.05)
        assert services.observer_alive()
    finally:
        services.stop()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_import_watchdog.py -v
```

Expected: `ModuleNotFoundError: No module named 'services.import_watchdog'`.

- [ ] **Step 3: Implement `services/import_watchdog.py`**

```python
from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)

from logging_config import get_logger

log = get_logger("import.watchdog")

_PREFIX = "NinjaTrader_Executions_"
_SUFFIX = ".csv"


class TickHandler(FileSystemEventHandler):
    """Route watchdog events into `ImportPipeline.ingest_tick`."""

    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline

    def on_created(self, event):
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent)):
            return
        if isinstance(event, FileCreatedEvent):
            self._dispatch(event.src_path)

    def on_modified(self, event):
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent)):
            return
        if isinstance(event, FileModifiedEvent):
            self._dispatch(event.src_path)

    def _dispatch(self, src_path: str) -> None:
        p = Path(src_path)
        if not (p.name.startswith(_PREFIX) and p.name.endswith(_SUFFIX)):
            return
        try:
            self.pipeline.ingest_tick(p)
        except Exception:
            log.exception("ingest_tick failed in watchdog thread",
                          extra={"path": str(p)})
```

- [ ] **Step 4: Modify `background.py` — accept an injected handler**

Change the `start` method signature and body. Keep `_NoopHandler` as the default.

Replace the existing `start` method with:

```python
    def start(self, *, handler=None) -> None:
        if self._started:
            return
        Path(self.config.inbox_dir).mkdir(parents=True, exist_ok=True)
        self.scheduler.add_job(
            self._heartbeat,
            trigger=IntervalTrigger(seconds=self.config.scheduler.heartbeat_seconds),
            id="heartbeat",
            replace_existing=True,
        )
        self.scheduler.start()
        use_handler = handler if handler is not None else _NoopHandler()
        self.observer.schedule(use_handler, self.config.inbox_dir, recursive=False)
        self.observer.start()
        self._started = True
        log.info(
            "background services started",
            extra={
                "max_workers": self.config.thread_pool.max_workers,
                "handler": type(use_handler).__name__,
            },
        )
```

- [ ] **Step 5: Run all tests to verify nothing regressed**

```bash
.venv/Scripts/python.exe -m pytest tests/test_background.py tests/test_import_watchdog.py tests/test_app_factory.py -v
```

Expected: all pass. `test_background.py` still works because `start()` accepts the same zero-arg call (handler defaults to `None` → `_NoopHandler`).

- [ ] **Step 6: Commit**

```bash
git add background.py services/import_watchdog.py tests/test_import_watchdog.py
git commit -m "feat(import): watchdog TickHandler and injectable BackgroundServices handler"
```

---

## Task 7: `resolve_current_trade_date` helper

Archival and the API both need to know "what is the current CME trade date right now?". This is a small addition to `services/time_utils.py` that reuses the existing rollover constant.

**Files:**
- Modify: `services/time_utils.py`
- Create: `tests/test_resolve_current_trade_date.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve_current_trade_date.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from services.time_utils import resolve_current_trade_date

TZ = ZoneInfo("America/Chicago")


def test_before_rollover_returns_today():
    # 2026-04-13 15:59 Central → still Monday's session
    now = datetime(2026, 4, 13, 15, 59, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-13"


def test_at_rollover_returns_next_day():
    now = datetime(2026, 4, 13, 16, 0, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-14"


def test_after_rollover_returns_next_day():
    now = datetime(2026, 4, 13, 17, 30, tzinfo=TZ)
    assert resolve_current_trade_date(now).isoformat() == "2026-04-14"


def test_rejects_naive():
    import pytest
    with pytest.raises(ValueError):
        resolve_current_trade_date(datetime(2026, 4, 13, 16, 0))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_resolve_current_trade_date.py -v
```

Expected: `ImportError: cannot import name 'resolve_current_trade_date'`.

- [ ] **Step 3: Add the function to `services/time_utils.py`**

Append below `compute_session_date`:

```python
def resolve_current_trade_date(now_local: datetime) -> date:
    """Map a timezone-aware *local-exchange* datetime to its CME trade date.

    Mirrors `compute_session_date` but takes an already-localized datetime
    so the archival job can decide "is this file date < today's trade date?"
    without a UTC round-trip.
    """
    if now_local.tzinfo is None:
        raise ValueError("resolve_current_trade_date requires a timezone-aware datetime")
    if now_local.time() >= ROLLOVER:
        return (now_local + timedelta(days=1)).date()
    return now_local.date()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_resolve_current_trade_date.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add services/time_utils.py tests/test_resolve_current_trade_date.py
git commit -m "feat(import): resolve_current_trade_date helper"
```

---

## Task 8: Session-end archival — integration test

`ImportPipeline.archive_completed_sessions` was written in Task 5. This task adds an end-to-end test that exercises it against a fake inbox and verifies file moves and cursor deletion.

**Files:**
- Create: `tests/test_archival.py`

- [ ] **Step 1: Write the test**

```python
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from db import connect
from services.import_db import get_cursor, save_cursor
from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")


def _pipeline(db_path: Path):
    return ImportPipeline(db_path=db_path, trader_tz=TZ)


def test_archive_moves_older_files_only(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    yesterday = inbox / "NinjaTrader_Executions_20260412.csv"
    today = inbox / "NinjaTrader_Executions_20260413.csv"
    yesterday.write_text("", encoding="utf-8")
    today.write_text("", encoding="utf-8")

    # Seed a cursor for the yesterday file so we can confirm it is deleted.
    conn = connect(migrated_db)
    try:
        save_cursor(conn, yesterday.name, byte_offset=0, file_mtime=0)
    finally:
        conn.close()

    pipeline = _pipeline(migrated_db)
    moved = pipeline.archive_completed_sessions(
        inbox_dir=inbox,
        archive_dir=archive,
        current_trade_date=date(2026, 4, 13),
    )

    assert len(moved) == 1
    assert not yesterday.exists()
    assert today.exists()
    expected = archive / "2026-04-12" / yesterday.name
    assert expected.exists()

    conn = connect(migrated_db)
    try:
        assert get_cursor(conn, yesterday.name) is None
    finally:
        conn.close()


def test_archive_ignores_nonmatching_filenames(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    (inbox / "random.csv").write_text("", encoding="utf-8")
    (inbox / "NinjaTrader_Executions_notadate.csv").write_text("", encoding="utf-8")

    pipeline = _pipeline(migrated_db)
    moved = pipeline.archive_completed_sessions(
        inbox_dir=inbox,
        archive_dir=archive,
        current_trade_date=date(2026, 4, 13),
    )
    assert moved == []
    assert (inbox / "random.csv").exists()
    assert (inbox / "NinjaTrader_Executions_notadate.csv").exists()
```

- [ ] **Step 2: Run the test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_archival.py -v
```

Expected: 2 passed. No implementation changes required — `archive_completed_sessions` was already implemented in Task 5.

- [ ] **Step 3: Commit**

```bash
git add tests/test_archival.py
git commit -m "test(import): session-end archival integration test"
```

---

## Task 9: Safety-sweep scheduled tick

The spec's "Open questions" section recommends a 5-minute safety sweep against today's file (in case watchdog misses an `on_modified` event on Windows). Implement it as a method on `ImportPipeline` that scans the inbox and calls `ingest_tick` on every matching file. The scheduler wiring happens in Task 12.

`scan_inbox` already exists from Task 5 — it is exactly the safety sweep. This task just tests it directly.

**Files:**
- Create: `tests/test_safety_sweep.py`

- [ ] **Step 1: Write the test**

```python
from pathlib import Path
from zoneinfo import ZoneInfo

from services.import_pipeline import ImportPipeline

TZ = ZoneInfo("America/Chicago")

HEADER = (
    "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
    "Commission,Rate,Account,Connection,TradeValidation\n"
)
ROW = (
    "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,swid,Entry,1 L,"
    "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
)


def test_scan_inbox_ticks_every_matching_file(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "NinjaTrader_Executions_20260413.csv").write_text(HEADER + ROW, encoding="utf-8")
    (inbox / "NinjaTrader_Executions_20260412.csv").write_text(HEADER + ROW.replace("swid", "swid2"), encoding="utf-8")
    (inbox / "unrelated.txt").write_text("ignored", encoding="utf-8")

    pipeline = ImportPipeline(db_path=migrated_db, trader_tz=TZ)
    results = pipeline.scan_inbox(inbox)
    filenames = sorted(r.filename for r in results)
    assert filenames == [
        "NinjaTrader_Executions_20260412.csv",
        "NinjaTrader_Executions_20260413.csv",
    ]
    assert sum(r.rows_inserted for r in results) == 2


def test_scan_inbox_empty_directory(tmp_path: Path, migrated_db: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pipeline = ImportPipeline(db_path=migrated_db, trader_tz=TZ)
    assert pipeline.scan_inbox(inbox) == []
```

- [ ] **Step 2: Run the test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_safety_sweep.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_safety_sweep.py
git commit -m "test(import): scan_inbox safety-sweep behavior"
```

---

## Task 10: Import API routes — list runs, cursors, rejects, scan

Routes are thin wrappers per Rule 2. They parse the request, call exactly one service or DB query, and serialize the result. No business logic.

**Files:**
- Create: `routes/imports.py`
- Create: `tests/test_routes_imports.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_imports.py`:

```python
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from db import connect
from migrations import run_migrations
from routes.imports import build_imports_blueprint
from services.import_db import bulk_insert_executions, record_run, save_cursor
from services.import_pipeline import ImportPipeline
from models.execution import Execution

TZ = ZoneInfo("America/Chicago")


@pytest.fixture
def app_and_pipeline(tmp_path: Path):
    db_path = tmp_path / "t.db"
    conn = connect(db_path)
    run_migrations(conn, Path("migrations"))
    conn.close()

    inbox = tmp_path / "inbox"
    inbox.mkdir()

    pipeline = ImportPipeline(db_path=db_path, trader_tz=TZ)
    app = Flask(__name__)
    app.config["FTL_DB_PATH"] = str(db_path)
    app.config["FTL_INBOX_DIR"] = str(inbox)
    app.config["FTL_IMPORT_PIPELINE"] = pipeline
    app.register_blueprint(build_imports_blueprint())
    return app, pipeline, db_path, inbox


def _seed_run(db_path: Path, filename: str, status: str = "ok") -> int:
    conn = connect(db_path)
    try:
        tid = record_run(
            conn,
            filename=filename, started_at=100, finished_at=101,
            cursor_before=0, cursor_after=100,
            lines_read=1, rows_parsed=1, rows_inserted=1,
            rows_skipped_duplicate=0, rows_rejected=0,
            status=status, error=None,
        )
        return tid
    finally:
        conn.close()


def test_get_runs_returns_latest_first(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    t1 = _seed_run(db_path, "a.csv")
    t2 = _seed_run(db_path, "b.csv")
    client = app.test_client()
    resp = client.get("/api/imports/runs")
    assert resp.status_code == 200
    body = resp.get_json()
    ids = [r["tick_id"] for r in body["runs"]]
    assert ids == [t2, t1]


def test_get_single_run(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    tid = _seed_run(db_path, "a.csv")
    client = app.test_client()
    resp = client.get(f"/api/imports/runs/{tid}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tick_id"] == tid
    assert "rejects" in body
    assert body["rejects"] == []


def test_get_single_run_not_found(app_and_pipeline):
    app, _, _, _ = app_and_pipeline
    resp = app.test_client().get("/api/imports/runs/99999")
    assert resp.status_code == 404


def test_get_cursors(app_and_pipeline):
    app, _, db_path, _ = app_and_pipeline
    conn = connect(db_path)
    try:
        save_cursor(conn, "file.csv", byte_offset=42, file_mtime=0)
    finally:
        conn.close()
    resp = app.test_client().get("/api/imports/cursors")
    assert resp.status_code == 200
    body = resp.get_json()
    assert any(c["filename"] == "file.csv" and c["byte_offset"] == 42 for c in body["cursors"])


def test_get_rejects(app_and_pipeline):
    app, _, db_path, _ = app_and_pipeline
    tid = _seed_run(db_path, "a.csv")
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO import_rejects (tick_id, line_number, raw_line, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (tid, 3, "oops", "bad", 0),
        )
    finally:
        conn.close()
    resp = app.test_client().get("/api/imports/rejects")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["rejects"]) == 1
    assert body["rejects"][0]["line_number"] == 3


def test_scan_triggers_ingest(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    header = (
        "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
        "Commission,Rate,Account,Connection,TradeValidation\n"
    )
    row = (
        "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,scanid,Entry,1 L,"
        "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
    )
    (Path(inbox) / "NinjaTrader_Executions_20260413.csv").write_text(
        header + row, encoding="utf-8"
    )
    resp = app.test_client().post("/api/imports/scan")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticked"] >= 1
    conn = connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 1
    finally:
        conn.close()


def test_rollback_deletes_rows(app_and_pipeline):
    app, pipeline, db_path, inbox = app_and_pipeline
    conn = connect(db_path)
    try:
        bulk_insert_executions(conn, [
            Execution(
                nt_execution_id="del1", account="Sim101", instrument="MNQ",
                timestamp=1, side="Buy", original_action="Buy",
                quantity=1, price=1.0, commission=0.0, entry_exit="Entry",
                position_after="1 L", source_order_id=None,
                source_filename="f.csv", imported_at=1,
            ),
            Execution(
                nt_execution_id="keep1", account="Sim101", instrument="MNQ",
                timestamp=2, side="Sell", original_action="Sell",
                quantity=1, price=2.0, commission=0.0, entry_exit="Exit",
                position_after="-", source_order_id=None,
                source_filename="f.csv", imported_at=1,
            ),
        ])
    finally:
        conn.close()
    resp = app.test_client().post(
        "/api/executions/rollback", json={"execution_ids": ["del1"]}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deleted"] == 1
    conn = connect(db_path)
    try:
        remaining = [
            r[0] for r in conn.execute(
                "SELECT nt_execution_id FROM executions"
            ).fetchall()
        ]
        assert remaining == ["keep1"]
    finally:
        conn.close()


def test_rollback_rejects_bad_body(app_and_pipeline):
    app, *_ = app_and_pipeline
    resp = app.test_client().post("/api/executions/rollback", json={})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_imports.py -v
```

Expected: `ModuleNotFoundError: No module named 'routes.imports'`.

- [ ] **Step 3: Implement `routes/imports.py`**

```python
from flask import Blueprint, current_app, jsonify, request

from db import connect
from logging_config import get_logger

log = get_logger("http.imports")


def build_imports_blueprint() -> Blueprint:
    bp = Blueprint("imports", __name__)

    def _db():
        return connect(current_app.config["FTL_DB_PATH"])

    def _pipeline():
        return current_app.config["FTL_IMPORT_PIPELINE"]

    @bp.get("/api/imports/runs")
    def list_runs():
        limit = min(int(request.args.get("limit", "100")), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT tick_id, filename, started_at, finished_at, cursor_before,"
                " cursor_after, lines_read, rows_parsed, rows_inserted,"
                " rows_skipped_duplicate, rows_rejected, status, error "
                "FROM import_runs ORDER BY tick_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"runs": [dict(r) for r in rows]})

    @bp.get("/api/imports/runs/<int:tick_id>")
    def get_run(tick_id: int):
        conn = _db()
        try:
            row = conn.execute(
                "SELECT * FROM import_runs WHERE tick_id = ?", (tick_id,)
            ).fetchone()
            if row is None:
                return jsonify({"error": "not found"}), 404
            rejects = conn.execute(
                "SELECT reject_id, line_number, raw_line, reason, created_at "
                "FROM import_rejects WHERE tick_id = ? ORDER BY reject_id",
                (tick_id,),
            ).fetchall()
        finally:
            conn.close()
        body = dict(row)
        body["rejects"] = [dict(r) for r in rejects]
        return jsonify(body)

    @bp.get("/api/imports/cursors")
    def list_cursors():
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT filename, byte_offset, last_tick_at, last_modified "
                "FROM import_cursors ORDER BY filename"
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"cursors": [dict(r) for r in rows]})

    @bp.post("/api/imports/scan")
    def scan():
        pipeline = _pipeline()
        inbox = current_app.config["FTL_INBOX_DIR"]
        results = pipeline.scan_inbox(inbox)
        return jsonify({
            "ticked": len(results),
            "results": [r.model_dump() for r in results],
        })

    @bp.get("/api/imports/rejects")
    def list_rejects():
        limit = min(int(request.args.get("limit", "100")), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT reject_id, tick_id, line_number, raw_line, reason, created_at "
                "FROM import_rejects ORDER BY reject_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        finally:
            conn.close()
        return jsonify({"rejects": [dict(r) for r in rows]})

    @bp.post("/api/executions/rollback")
    def rollback():
        body = request.get_json(silent=True) or {}
        ids = body.get("execution_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            return jsonify({"error": "execution_ids must be a non-empty list of strings"}), 400
        deleted = _pipeline().rollback(ids)
        return jsonify({"deleted": deleted})

    return bp
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/Scripts/python.exe -m pytest tests/test_routes_imports.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add routes/imports.py tests/test_routes_imports.py
git commit -m "feat(import): /api/imports/* routes and rollback endpoint"
```

---

## Task 11: App factory wiring — build pipeline, register blueprint, schedule jobs

The app factory now owns three new responsibilities:

1. Construct `ImportPipeline` and place it in `app.config["FTL_IMPORT_PIPELINE"]`.
2. Register the imports blueprint.
3. Register two scheduled jobs on `services.scheduler` — the safety sweep (every 5 minutes by default) and the session-end archival (daily at `config.session.archive_job_time`).
4. Pass a `TickHandler(pipeline)` into `services.start()` when `start_background=True`.

**Files:**
- Modify: `app.py`
- Create: `tests/test_app_factory_plan10.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_factory_plan10.py`:

```python
from pathlib import Path

from app import create_app
from services.import_pipeline import ImportPipeline


def test_pipeline_is_registered_in_app_config(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    pipeline = app.config.get("FTL_IMPORT_PIPELINE")
    assert isinstance(pipeline, ImportPipeline)


def test_imports_blueprint_is_registered(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    client = app.test_client()
    resp = client.get("/api/imports/runs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"runs": []}


def test_inbox_dir_is_in_app_config(tmp_config):
    app, services = create_app(tmp_config, start_background=False)
    assert Path(app.config["FTL_INBOX_DIR"]) == Path(tmp_config.inbox_dir)


def test_scheduler_has_archival_and_sweep_jobs_when_started(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        ids = {j.id for j in services.scheduler.get_jobs()}
        assert "heartbeat" in ids
        assert "import_safety_sweep" in ids
        assert "archive_completed_sessions" in ids
    finally:
        services.stop()


def test_watchdog_uses_tick_handler_when_started(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        # The injected handler is TickHandler — verify by checking observer state.
        # We can't reach into watchdog's private fields portably, so just assert
        # observer is alive and the pipeline reference is the one in app.config.
        assert services.observer_alive()
        assert app.config["FTL_IMPORT_PIPELINE"] is not None
    finally:
        services.stop()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan10.py -v
```

Expected: failures because `FTL_IMPORT_PIPELINE` is not set, `/api/imports/runs` returns 404, etc.

- [ ] **Step 3: Rewrite `app.py`**

Replace the entire file with:

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from background import BackgroundServices
from config import Config
from db import connect
from logging_config import configure_logging, get_logger
from migrations import run_migrations
from routes import health as health_routes
from routes.imports import build_imports_blueprint
from services.import_pipeline import ImportPipeline
from services.import_watchdog import TickHandler
from services.time_utils import resolve_current_trade_date

log = get_logger("http")

SAFETY_SWEEP_SECONDS = 300  # 5 minutes


def create_app(
    config: Config,
    *,
    start_background: bool = False,
) -> tuple[Flask, BackgroundServices]:
    """Build the Flask app and its BackgroundServices container."""
    configure_logging(level="INFO")

    conn = connect(config.db_path)
    try:
        run_migrations(conn, Path("migrations"))
    finally:
        conn.close()

    services = BackgroundServices(config)
    trader_tz = ZoneInfo(config.session.exchange_timezone)
    pipeline = ImportPipeline(
        db_path=config.db_path,
        trader_tz=trader_tz,
        post_tick_hooks=[],  # plan 11 and 14 will register here
    )

    app = Flask(__name__)
    app.config["BACKGROUND_SERVICES"] = services
    app.config["DB_PATH"] = config.db_path
    app.config["HEARTBEAT_SECONDS"] = config.scheduler.heartbeat_seconds
    app.config["FTL_CONFIG"] = config
    app.config["FTL_DB_PATH"] = config.db_path
    app.config["FTL_INBOX_DIR"] = config.inbox_dir
    app.config["FTL_IMPORT_PIPELINE"] = pipeline

    app.register_blueprint(health_routes.bp)
    app.register_blueprint(build_imports_blueprint())

    # Safety sweep: re-tick every file in inbox periodically, in case watchdog
    # missed an on_modified event. Cheap, idempotent.
    services.scheduler.add_job(
        lambda: pipeline.scan_inbox(config.inbox_dir),
        trigger=IntervalTrigger(seconds=SAFETY_SWEEP_SECONDS),
        id="import_safety_sweep",
        replace_existing=True,
    )

    # Session-end archival: daily, at config.session.archive_job_time (exchange tz).
    hour, minute = _parse_hhmm(config.session.archive_job_time)
    services.scheduler.add_job(
        lambda: _run_archival(pipeline, config, trader_tz),
        trigger=CronTrigger(hour=hour, minute=minute, timezone=trader_tz),
        id="archive_completed_sessions",
        replace_existing=True,
    )

    if start_background:
        services.start(handler=TickHandler(pipeline))

    log.info("app created", extra={"start_background": start_background})
    return app, services


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def _run_archival(pipeline: ImportPipeline, config: Config, trader_tz: ZoneInfo) -> None:
    now_local = datetime.now(trader_tz)
    today = resolve_current_trade_date(now_local)
    pipeline.archive_completed_sessions(
        inbox_dir=config.inbox_dir,
        archive_dir=config.archive_dir,
        current_trade_date=today,
    )
```

- [ ] **Step 4: Run the new tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan10.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the whole suite to catch regressions**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: every test passes. If `test_app_factory.py::test_create_app_with_background_services` fails because the scheduler picks up the safety sweep mid-test, that is fine — the test only checks `scheduler_running()` and `observer_alive()`. If anything else fails, diagnose.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_factory_plan10.py
git commit -m "feat(import): wire ImportPipeline, routes, and scheduled jobs into app factory"
```

---

## Task 12: End-to-end smoke — live watchdog drop

This is a slower integration test that writes a file into the inbox of a real app built by the factory with `start_background=True`, waits for the handler to pick it up, and asserts a row landed in `executions`. It protects against subtle wiring bugs between watchdog and the pipeline.

**Files:**
- Modify: `tests/test_app_factory_plan10.py` — add the smoke test.

- [ ] **Step 1: Append to `tests/test_app_factory_plan10.py`**

```python
import time

from db import connect as _connect


def test_watchdog_drop_reaches_executions(tmp_config):
    app, services = create_app(tmp_config, start_background=True)
    try:
        header = (
            "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,"
            "Commission,Rate,Account,Connection,TradeValidation\n"
        )
        row = (
            "MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,watchid,Entry,1 L,"
            "1,n,$0.00,1,Sim101,Apex Trader Funding ,\n"
        )
        path = Path(tmp_config.inbox_dir) / "NinjaTrader_Executions_20260413.csv"
        path.write_text(header + row, encoding="utf-8")

        # Give watchdog up to 3 seconds to fire and the pipeline to commit.
        deadline = time.time() + 3.0
        inserted = 0
        while time.time() < deadline:
            conn = _connect(tmp_config.db_path)
            try:
                inserted = conn.execute(
                    "SELECT COUNT(*) FROM executions WHERE nt_execution_id = 'watchid'"
                ).fetchone()[0]
            finally:
                conn.close()
            if inserted == 1:
                break
            time.sleep(0.05)
        assert inserted == 1
    finally:
        services.stop()
```

- [ ] **Step 2: Run the test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_app_factory_plan10.py::test_watchdog_drop_reaches_executions -v
```

Expected: 1 passed. If it flakes because watchdog is slow on Windows, bump the deadline to 5 seconds and note the change in the commit message — that is the only valid reason to change this test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_app_factory_plan10.py
git commit -m "test(import): end-to-end watchdog smoke test"
```

---

## Task 13: `/healthz` reports unhealthy when imports are failing (deferred note)

Doc 10 does not require `/healthz` to inspect import state in plan 10. Plan 17 will add an import-health panel that gates on "most recent tick is `ok`". Plan 10 intentionally leaves `/healthz` unchanged so we don't ship an under-specified implementation now. **No code in this task** — this is a reminder to future-you that the current `/healthz` semantics are correct for plan 10.

- [ ] **Step 1: Confirm `/healthz` still passes without modification**

```bash
.venv/Scripts/python.exe -m pytest tests/test_health.py -v
```

Expected: 2 passed (same count as plan 00).

No commit.

---

## Task 14: Final verification

- [ ] **Step 1: Run the full test suite**

```bash
.venv/Scripts/python.exe -m pytest -v
```

Expected: every test passes. Plan 10 adds roughly 55 new tests across nine files; plan 00's 22 continue to pass. Final count ≈ 75–80.

- [ ] **Step 2: Run ruff**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```

Expected: no errors, no diffs. If `format --check` reports diffs, run `ruff format .` and commit the result as `chore(import): ruff format pass`.

- [ ] **Step 3: Bring up the container and exercise the API end-to-end**

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/api/imports/runs
curl -fsS http://localhost:8000/api/imports/cursors
```

Expected:

- `docker compose ps` shows one service, `futurestradinglog`, status `Up (healthy)` within ~30s.
- `/healthz` returns 200 with every flag true.
- `/api/imports/runs` returns `{"runs": []}`.
- `/api/imports/cursors` returns `{"cursors": []}`.

Drop a valid CSV into the container's inbox volume and confirm a row lands in executions:

```bash
docker compose exec web sh -c "cat > /app/data/inbox/NinjaTrader_Executions_20260413.csv" <<'EOF'
Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,Commission,Rate,Account,Connection,TradeValidation
MNQ,Buy,1,4000.00,1/15/2025 9:00:00 AM,smoke1,Entry,1 L,1,n,$0.00,1,Sim101,Apex Trader Funding ,
EOF
sleep 2
curl -fsS http://localhost:8000/api/imports/runs
```

Expected: the `runs` list contains at least one entry with `rows_inserted >= 1`.

- [ ] **Step 4: Bring it down**

```bash
docker compose down
```

- [ ] **Step 5: Commit any formatting fixes**

```bash
git status
# if anything reformatted:
git add -u
git commit -m "chore(import): ruff format pass"
```

---

## Task 15: Update the rebuild-spec progress table

After everything is green, record plan 10 as complete in the README's progress table.

**Files:**
- Modify: `docs/rebuild-spec/00-README.md`

- [ ] **Step 1: Update the progress row**

Find the line:

```markdown
| 10 — Import Pipeline | `executions` schema, CSV parser, `ingest_tick`, watchdog handler, `import_runs`/`import_rejects`/`import_cursors`, session archival job, rollback API | ⏳ Next |
```

Replace with:

```markdown
| [10 — Import Pipeline](../superpowers/plans/2026-04-13-10-import-pipeline.md) | `executions` schema, CSV parser, `ingest_tick`, watchdog handler, `import_runs`/`import_rejects`/`import_cursors`, session archival job, rollback API | ✅ **Complete** (2026-04-13) |
```

Also update `| 11 — Position Building |`'s status column to `⏳ **Next**`.

- [ ] **Step 2: Add a "What Plan 10 landed" section**

Append below the existing `### What Plan 00 landed` section:

```markdown
### What Plan 10 landed

- **Executions table.** `migrations/002_executions.sql` ships `executions`, `import_cursors`, `import_runs`, `import_rejects`. Composite PK `(nt_execution_id, account)` plus `UNIQUE INDEX idx_executions_nt_execution_id` gives plan 12/16 user-metadata tables a clean single-column FK target.
- **CSV parser.** `services/csv_parser.parse_execution_row` consumes the 15-column format from doc 90, normalizes Action → Side (`Buy`/`BuyToCover` → `Buy`; `Sell`/`SellShort` → `Sell`), and raises `ParseError` per row with a reason suitable for `import_rejects.reason`.
- **ImportPipeline.** `services/import_pipeline.ImportPipeline` owns `ingest_tick(path)`, `scan_inbox(dir)`, `archive_completed_sessions(...)`, and `rollback(ids)`. A per-path `threading.Lock` registry serializes ticks on one file while leaving different files parallel. The tick transaction contains only cursor/executions/rejects/import_runs writes; integrity diff and OHLC fetch are post-tick hooks that plans 11 and 14 will register.
- **Watchdog handler.** `services/import_watchdog.TickHandler` replaces the Plan 00 `_NoopHandler`. `BackgroundServices.start(handler=…)` now accepts an injected handler and still defaults to `_NoopHandler` for the foundation tests.
- **Scheduled jobs.** The app factory registers two jobs on the existing APScheduler: a 5-minute safety sweep that calls `scan_inbox`, and a daily archival job at `config.session.archive_job_time` that moves yesterday's files to `data/archive/YYYY-MM-DD/` after one final safety-net tick.
- **API surface.** `/api/imports/runs`, `/api/imports/runs/{id}`, `/api/imports/cursors`, `/api/imports/rejects`, `POST /api/imports/scan`, `POST /api/executions/rollback`.
- **No batches, no file tracking, no upload endpoint.** Per doc 10 fragmentation hazards 1–8.
```

- [ ] **Step 3: Commit**

```bash
git add docs/rebuild-spec/00-README.md
git commit -m "docs(rebuild-spec): record Plan 10 completion"
```

---

## What this plan deliberately does NOT do

These belong to later plans and will fail the spec if added here:

- **No `build_positions` function, no position records, no `integrity_issues` table.** Plan 11. The post-tick hook list ships empty; plan 11 registers the integrity-diff hook there.
- **No OHLC fetching, no `bars` table, no fetch submission.** Plan 14. Plan 14 will register the fetch hook alongside plan 11's.
- **No `/api/positions`, no `/api/integrity-issues`, no `/api/bars`.** Plans 11 / 14 / 12.
- **No `instruments.json`.** Plan 16.
- **No HTML templates or JS beyond what plan 00 shipped.** Plan 12 opens the first real page.
- **No monitoring dashboard.** Plan 17. Plan 10 provides the raw API rows plan 17 will consume.
- **No `trader_timezone` config split.** For plan 10, `config.session.exchange_timezone` is reused as the trader timezone. If a trader ever runs NT on a non-exchange clock, a follow-up plan adds a dedicated field; until then, YAGNI.
- **No `/healthz` change to include import freshness.** Plan 17.

## Definition of done for plan 10

1. `pytest` runs green on a fresh clone after `pip install -r requirements.txt`. All plan 00 tests still pass; plan 10 adds ~55 new tests across 9 files.
2. `ruff check .` and `ruff format --check .` are clean.
3. `docker compose up -d --build` brings up exactly one container and `docker compose ps` shows `Up (healthy)`.
4. Dropping a valid CSV into the container inbox causes a row to appear in `executions` within ~3 seconds without any manual action.
5. `/api/imports/runs` shows at least one tick for every dropped file.
6. `POST /api/executions/rollback` deletes the specified rows and returns the deleted count.
7. Duplicate re-drops of the same CSV produce no new rows; `rows_skipped_duplicate` in the most recent run reflects the duplicates accurately.
8. `docs/rebuild-spec/00-README.md`'s progress table lists plan 10 as complete and plan 11 as next.

After this plan is merged, plan 11 can begin: it will add `build_positions`, the integrity diff, the `integrity_issues` table, and register the integrity-diff hook on the existing `ImportPipeline.post_tick_hooks` list.
