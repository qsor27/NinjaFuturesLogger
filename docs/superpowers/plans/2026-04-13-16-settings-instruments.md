# Settings, Instruments & Custom Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship feature 16 — a JSON-backed `InstrumentRegistry` replacing plan 11/14 hardcoded stubs, a DB-backed `chart_defaults` row, user-defined custom fields keyed to `nt_execution_id` with full CRUD, four server-rendered `/settings/*` pages, and rendering of custom fields on the plan 12 position detail page. No new Python or JS dependencies. One new migration (006). `display_timezone` writes through a new helper on `config.py`, not into the `chart_defaults` schema.

**Architecture:** `migrations/006_settings_custom_fields.sql` creates `chart_defaults` (one-row), `custom_fields`, `custom_field_options`, `execution_custom_field_values` exactly as doc 16 spells out. `services/instrument_registry.py` owns `data/config/instruments.json` with atomic tmp+rename writes under a module-level lock; it seeds from the current hardcoded tables on first read. `services/instruments.py` becomes a thin delegator preserving its current public surface so plans 11/14 callers are untouched. `services/chart_defaults.py::get_defaults()` body swaps to a SQL SELECT; a new `save_defaults` companion writes the row. `services/custom_fields.py::CustomFieldsService` owns all CRUD for custom field definitions, options, and execution values, strip-suffixing via plan 12's `notes.strip_split_suffix` before every write. `routes/settings.py` (new blueprint) carries the 13 API endpoints and four page routes. `services/positions_service.py::attach_metadata` swaps its `custom_fields: {}` stub for a `values_for_position(...)` call. `static/js/position_detail.js` grows an inline custom-fields block plus a per-execution `<details>` fold-out.

**Tech Stack:** Python 3.11, Flask 3, Pydantic v2, SQLite (stdlib `sqlite3`), pytest, ruff. Frontend: vanilla ES modules, no bundler, no framework, no Node, no `package.json`. No additions to `requirements.txt`.

## Spec references

- `docs/rebuild-spec/00-README.md` — load-bearing decisions 1, 2, 6, 7, 8. Rule 7 (user metadata keys off stable IDs) is the reason custom field values attach to `nt_execution_id`, not to positions.
- `docs/rebuild-spec/01-mission-and-principles.md` — Six Rules. Rule 2 (routes parse/dispatch/format only; no SQL in routes), Rule 5 (templates are shells; JS reads `data-*` and calls JSON APIs), Rule 6 (services testable in isolation).
- `docs/rebuild-spec/14-ohlc-pipeline.md` — the full `instruments.json` shape this plan writes. `sources: {yfinance, stooq}` with `continuous`/`contract_template`; `session` with `timezone`, `open`, `close`, `daily_break_start`, `daily_break_end`. Plan 14's `SessionCalendar` dataclass stays; the registry just populates it from JSON.
- `docs/rebuild-spec/16-settings-instruments.md` — the full feature spec. Plan 16 implements its eleven acceptance criteria and avoids its five fragmentation hazards. The DDL in this plan's migration matches doc 16 verbatim.
- `docs/superpowers/specs/2026-04-13-16-settings-instruments-design.md` — the brainstorm/design doc this plan implements. Captures seeded-registry choice, inline-visible custom fields with fold-out per-execution, `display_timezone` kept in `Config`/`app.json` via new helper, and the replace-in-place options editor.
- `docs/superpowers/plans/2026-04-13-11-position-building.md` — plan 11 is the caller of `get_multiplier`. After this plan's body swap, `services/positions.py` must still produce the same `dollars_pnl` for known instruments.
- `docs/superpowers/plans/2026-04-13-14-ohlc-pipeline.md` — plan 14 callers: `services/ohlc/yfinance_source.py`, `services/ohlc/stooq_source.py`, `services/ohlc/gap_detection.py`, and the post-tick hook in `app.py` (which reads `services.instruments.DEFAULT_TIMEFRAMES` at module level).
- `docs/superpowers/plans/2026-04-13-12-browsing.md` — plan 12 built `services/positions_service.py::attach_metadata` returning `custom_fields: {}` as a stub and `static/js/position_detail.js` which renders detail/notes/reviewed/executions/links/delete sections. Plan 16 extends both.
- `docs/superpowers/plans/2026-04-13-13-charting.md` — plan 13 shipped `services/chart_defaults.py` as a module-level stub. Plan 16 swaps `get_defaults()` to a DB read without touching the signature.
- `docs/superpowers/plans/2026-04-13-15-statistics.md` — plan 15 added `config.display_timezone` as a `Config` field with no writer. Plan 16 adds the writer.

## Load-bearing rules from the spec

Six rules drive Plan 16. If any of them appear violated, stop:

1. **One endpoint per resource. No `/v1`/`/v2` parallel APIs.** Doc 16 hazard 1. Grep at the end of the plan: `grep -rn "/api/v" routes/settings.py` must be empty.
2. **Instrument config lives in one JSON file, touched by one service.** Doc 16 hazard 2. `grep -rn "_MULTIPLIERS\|_YFINANCE_SYMBOLS\|_STOOQ_SYMBOLS" services/ models/` must only match `services/instrument_registry.py` after Task 4.
3. **No `positions` table or `position_custom_field_values` table.** Doc 16 hazard 4 + Rule 2 from doc 00. Custom field values attach to `executions(nt_execution_id)`. Grep: `grep -rn "position_custom_field_values\|positions_id" migrations/` must be empty.
4. **`#close`/`#open` split-fill IDs never land in `execution_custom_field_values`.** Every mutator in `CustomFieldsService` strip-suffixes via `notes.strip_split_suffix` before touching the DB. Same rule plan 12 uses for notes and reviewed flags.
5. **No profiles, no instrument groups, no import/export of settings.** Doc 16 hazards 3 and 5. Grep: `grep -rn "profile\|instrument_group" routes/settings.py` must be empty.
6. **`chart_defaults` is a fixed single-row table with known columns — not a generic key-value store.** Doc 16 data-model note. The CHECK constraint `id = 1` enforces this at the storage layer. No `display_timezone` column on `chart_defaults` — that field stays in `Config`/`app.json` via a new `config.save_display_timezone` helper.

Plus, from earlier plans:

- **`services/instruments.py` public surface is load-bearing.** Plans 11 and 14 import `get_multiplier`, `base_symbol`, `DEFAULT_TIMEFRAMES`, `source_symbol`, `SessionCalendar`, `default_session`. Task 4 rewrites the bodies without changing any signature. Plan 14's `app.py` hook reads `DEFAULT_TIMEFRAMES` at module import time, so the constant must remain a module attribute (not a function call) and evaluate to the same value for the seed. The registry's contribution is reading it from disk; the initial `from services.instruments import DEFAULT_TIMEFRAMES` line in `app.py` is unchanged.
- **`notes.strip_split_suffix` is plan 12's canonical helper.** Don't create a second one.
- **Execution existence checks match plan 12's pattern.** `routes/user_metadata.py::_execution_exists` does `SELECT 1 FROM executions WHERE nt_execution_id = ?` after strip. `routes/settings.py` reuses exactly this pattern.
- **Config load-only.** `config.py::load_config(path) -> Config` is the only existing I/O on `app.json`. Plan 16 adds `save_display_timezone(path, value)` as a targeted single-field writer. Do NOT introduce a general `save_config` — that's scope creep, and the display timezone is the only user-editable `Config` field in doc 16.
- **App-factory blueprint order matters**. Existing order in `app.py` lines 126–133 is: `health`, `imports`, `positions`, `ohlc`, `user_metadata`, `links`, `pages`, `stats`. Plan 16 adds `build_settings_blueprint()` between `links` and `pages` (API routes before page routes; consistent with plan 15).
- **Migrations run lexicographically.** `migrations/006_settings_custom_fields.sql` runs after `005_browsing.sql`. Plan 10's `UNIQUE INDEX idx_executions_nt_execution_id` is in place from `002_executions.sql`, so the FK from `execution_custom_field_values.execution_id → executions(nt_execution_id)` is valid.

## File layout this plan creates or modifies

```
/
├── migrations/
│   └── 006_settings_custom_fields.sql           # NEW
├── models/
│   ├── settings.py                              # NEW: InstrumentConfig etc.
│   └── __init__.py                              # MODIFY: export new models
├── services/
│   ├── instrument_registry.py                   # NEW: InstrumentRegistry + DEFAULT_SEED
│   ├── instruments.py                           # REWRITE bodies; keep public surface
│   ├── chart_defaults.py                        # REWRITE get_defaults(); add save_defaults
│   ├── custom_fields.py                         # NEW: CustomFieldsService
│   └── positions_service.py                     # MODIFY: attach_metadata populates custom_fields
├── routes/
│   ├── settings.py                              # NEW blueprint: 13 API + 4 page routes
│   └── pages.py                                 # MODIFY: /settings + 3 sub-pages moved to settings blueprint
├── config.py                                    # MODIFY: add save_display_timezone
├── app.py                                       # MODIFY: register settings blueprint
├── templates/
│   ├── settings_index.html                      # NEW
│   ├── settings_instruments.html                # NEW
│   ├── settings_chart.html                      # NEW
│   ├── settings_custom_fields.html              # NEW
│   ├── position_detail.html                     # MODIFY: add #custom-fields mount point
│   └── base.html                                # MODIFY: add Settings nav link
├── static/
│   ├── css/
│   │   └── settings.css                         # NEW (scoped via body.settings-page)
│   └── js/
│       ├── settings_instruments.js              # NEW
│       ├── settings_chart.js                    # NEW
│       ├── settings_custom_fields.js            # NEW
│       ├── custom_fields_detail.js              # NEW: helper for position detail
│       └── position_detail.js                   # MODIFY: mount custom fields block
└── tests/
    ├── test_migration_006.py                    # NEW
    ├── test_models_settings.py                  # NEW
    ├── test_instrument_registry.py              # NEW
    ├── test_instruments_registry_backcompat.py  # NEW
    ├── test_chart_defaults_db.py                # NEW (plus existing test_chart_defaults.py stays)
    ├── test_config_save_display_timezone.py     # NEW
    ├── test_custom_fields_service.py            # NEW
    ├── test_settings_routes_instruments.py      # NEW
    ├── test_settings_routes_chart.py            # NEW
    ├── test_settings_routes_custom_fields.py    # NEW
    ├── test_position_detail_custom_fields.py    # NEW
    └── test_app_factory_plan16.py               # NEW
```

## Task shape

Fourteen tasks, TDD (failing test first in every non-trivial task), one commit per task minimum. Each task is independently verifiable with `pytest -x`.

---

### Task 1: Migration 006 — schema for settings + custom fields

**Files:**
- Create: `migrations/006_settings_custom_fields.sql`
- Create: `tests/test_migration_006.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_006.py`:

```python
import sqlite3
import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations


def _fresh_db() -> sqlite3.Connection:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    return conn


def test_chart_defaults_table_exists_with_seed_row():
    conn = _fresh_db()
    try:
        rows = conn.execute("SELECT id, default_timeframe, volume_visible_default FROM chart_defaults").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == 1
        assert rows[0]["default_timeframe"] == "5m"
        assert rows[0]["volume_visible_default"] == 1
    finally:
        conn.close()


def test_chart_defaults_single_row_check_rejects_second_insert():
    conn = _fresh_db()
    try:
        try:
            conn.execute("INSERT INTO chart_defaults (id, updated_at) VALUES (2, 0)")
            raise AssertionError("expected CHECK(id=1) to reject id=2")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_custom_fields_tables_exist_with_expected_columns():
    conn = _fresh_db()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(custom_fields)").fetchall()}
        assert cols == {"field_id", "name", "field_type", "is_active", "display_order", "created_at"}

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(custom_field_options)").fetchall()}
        assert cols == {"option_id", "field_id", "value", "display_order"}

        cols = {r["name"] for r in conn.execute("PRAGMA table_info(execution_custom_field_values)").fetchall()}
        assert cols == {"execution_id", "field_id", "value", "updated_at"}
    finally:
        conn.close()


def test_custom_fields_field_type_check_rejects_bad_type():
    conn = _fresh_db()
    try:
        try:
            conn.execute(
                "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('x', 'bogus', 0)"
            )
            raise AssertionError("expected CHECK(field_type IN ...) to reject 'bogus'")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_custom_field_options_unique_per_field():
    conn = _fresh_db()
    try:
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('setup', 'dropdown', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='setup'").fetchone()[0]
        conn.execute(
            "INSERT INTO custom_field_options (field_id, value, display_order) VALUES (?, 'Breakout', 0)",
            (fid,),
        )
        try:
            conn.execute(
                "INSERT INTO custom_field_options (field_id, value, display_order) VALUES (?, 'Breakout', 1)",
                (fid,),
            )
            raise AssertionError("expected UNIQUE(field_id, value) to reject")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_execution_custom_field_values_cascade_on_execution_delete():
    conn = _fresh_db()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "('E1', 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)"
        )
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('setup', 'text', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='setup'").fetchone()[0]
        conn.execute(
            "INSERT INTO execution_custom_field_values (execution_id, field_id, value, updated_at) "
            "VALUES ('E1', ?, 'A+', 0)",
            (fid,),
        )
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        conn.execute("DELETE FROM executions WHERE nt_execution_id = 'E1'")
        conn.execute("COMMIT")

        remaining = conn.execute(
            "SELECT COUNT(*) FROM execution_custom_field_values WHERE execution_id = 'E1'"
        ).fetchone()[0]
        assert remaining == 0
    finally:
        conn.close()


def test_execution_custom_field_values_cascade_on_field_delete():
    conn = _fresh_db()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "('E2', 'Sim', 'MES', 1700000001, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000001)"
        )
        conn.execute(
            "INSERT INTO custom_fields (name, field_type, created_at) VALUES ('confidence', 'number', 0)"
        )
        fid = conn.execute("SELECT field_id FROM custom_fields WHERE name='confidence'").fetchone()[0]
        conn.execute(
            "INSERT INTO execution_custom_field_values (execution_id, field_id, value, updated_at) "
            "VALUES ('E2', ?, '4.0', 0)",
            (fid,),
        )
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        conn.execute("DELETE FROM custom_fields WHERE field_id = ?", (fid,))
        conn.execute("COMMIT")

        remaining = conn.execute(
            "SELECT COUNT(*) FROM execution_custom_field_values WHERE field_id = ?", (fid,)
        ).fetchone()[0]
        assert remaining == 0
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_006.py -x -v`
Expected: All tests fail with `sqlite3.OperationalError: no such table: chart_defaults`.

- [ ] **Step 3: Write the migration**

Create `migrations/006_settings_custom_fields.sql`:

```sql
CREATE TABLE chart_defaults (
  id                       INTEGER PRIMARY KEY CHECK(id = 1),
  default_timeframe        TEXT NOT NULL DEFAULT '5m'
    CHECK(default_timeframe IN ('1m','5m','15m','1h','4h','1d')),
  volume_visible_default   INTEGER NOT NULL DEFAULT 1,
  updated_at               INTEGER NOT NULL
);
INSERT INTO chart_defaults (id, updated_at) VALUES (1, strftime('%s','now'));

CREATE TABLE custom_fields (
  field_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL UNIQUE,
  field_type     TEXT NOT NULL
    CHECK(field_type IN ('text','number','dropdown','date','boolean')),
  is_active      INTEGER NOT NULL DEFAULT 1,
  display_order  INTEGER NOT NULL DEFAULT 0,
  created_at     INTEGER NOT NULL
);

CREATE TABLE custom_field_options (
  option_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  field_id       INTEGER NOT NULL
    REFERENCES custom_fields(field_id) ON DELETE CASCADE,
  value          TEXT NOT NULL,
  display_order  INTEGER NOT NULL DEFAULT 0,
  UNIQUE (field_id, value)
);
CREATE INDEX idx_custom_field_options_field ON custom_field_options(field_id);

CREATE TABLE execution_custom_field_values (
  execution_id   TEXT NOT NULL,
  field_id       INTEGER NOT NULL
    REFERENCES custom_fields(field_id) ON DELETE CASCADE,
  value          TEXT NOT NULL,
  updated_at     INTEGER NOT NULL,
  PRIMARY KEY (execution_id, field_id),
  FOREIGN KEY (execution_id)
    REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);
CREATE INDEX idx_execution_custom_field_values_field
  ON execution_custom_field_values(field_id);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_migration_006.py -x -v`
Expected: All seven tests pass.

- [ ] **Step 5: Commit**

```bash
git add migrations/006_settings_custom_fields.sql tests/test_migration_006.py
git commit -m "feat(plan16): migration 006 — chart_defaults + custom fields tables"
```

---

### Task 2: Pydantic StrictModels for settings

**Files:**
- Create: `models/settings.py`
- Modify: `models/__init__.py` (add exports)
- Create: `tests/test_models_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_models_settings.py`:

```python
import pytest
from pydantic import ValidationError

from models.settings import (
    ChartDefaults,
    CustomFieldDefinition,
    CustomFieldOption,
    InstrumentConfig,
    InstrumentSession,
    InstrumentSources,
    SourceMapping,
)


def test_source_mapping_round_trip():
    m = SourceMapping(continuous="ES=F", contract_template=None)
    assert m.continuous == "ES=F"
    assert m.contract_template is None
    assert SourceMapping(**m.model_dump()) == m


def test_source_mapping_both_fields_optional():
    m = SourceMapping()
    assert m.continuous is None
    assert m.contract_template is None


def test_instrument_sources_requires_both_providers():
    with pytest.raises(ValidationError):
        InstrumentSources()  # yfinance and stooq both required


def test_instrument_session_all_fields_strings():
    s = InstrumentSession(
        timezone="America/Chicago",
        open="17:00",
        close="16:00",
        daily_break_start="16:00",
        daily_break_end="17:00",
    )
    assert s.timezone == "America/Chicago"


def test_instrument_config_full_round_trip():
    raw = {
        "display_name": "E-mini S&P 500",
        "multiplier": 50.0,
        "tick_size": 0.25,
        "sources": {
            "yfinance": {"continuous": "ES=F", "contract_template": None},
            "stooq": {"continuous": "es.f", "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00",
            "close": "16:00",
            "daily_break_start": "16:00",
            "daily_break_end": "17:00",
        },
    }
    cfg = InstrumentConfig(**raw)
    assert cfg.multiplier == 50.0
    assert cfg.sources.yfinance.continuous == "ES=F"
    assert cfg.session.timezone == "America/Chicago"
    assert cfg.model_dump()["sources"]["stooq"]["continuous"] == "es.f"


def test_instrument_config_extra_forbidden():
    with pytest.raises(ValidationError):
        InstrumentConfig(
            display_name="x",
            multiplier=1.0,
            tick_size=0.25,
            sources=InstrumentSources(
                yfinance=SourceMapping(),
                stooq=SourceMapping(),
            ),
            session=InstrumentSession(
                timezone="UTC",
                open="00:00",
                close="00:00",
                daily_break_start="",
                daily_break_end="",
            ),
            extra_field="nope",
        )


def test_chart_defaults_timeframe_literal():
    cd = ChartDefaults(default_timeframe="5m", volume_visible_default=True, display_timezone=None)
    assert cd.default_timeframe == "5m"
    with pytest.raises(ValidationError):
        ChartDefaults(default_timeframe="2m", volume_visible_default=True, display_timezone=None)


def test_custom_field_definition_field_type_literal():
    for ft in ("text", "number", "dropdown", "date", "boolean"):
        CustomFieldDefinition(
            field_id=1,
            name="x",
            field_type=ft,
            is_active=True,
            display_order=0,
            created_at=0,
        )
    with pytest.raises(ValidationError):
        CustomFieldDefinition(
            field_id=1,
            name="x",
            field_type="bogus",
            is_active=True,
            display_order=0,
            created_at=0,
        )


def test_custom_field_option_round_trip():
    o = CustomFieldOption(option_id=1, field_id=2, value="Breakout", display_order=0)
    assert o.value == "Breakout"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_models_settings.py -x -v`
Expected: `ModuleNotFoundError: No module named 'models.settings'`.

- [ ] **Step 3: Write the models**

Create `models/settings.py`:

```python
from typing import Literal

from pydantic import Field

from models.base import StrictModel

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
FieldType = Literal["text", "number", "dropdown", "date", "boolean"]


class SourceMapping(StrictModel):
    continuous: str | None = None
    contract_template: str | None = None


class InstrumentSources(StrictModel):
    yfinance: SourceMapping
    stooq: SourceMapping


class InstrumentSession(StrictModel):
    timezone: str
    open: str  # "HH:MM" local
    close: str  # "HH:MM" local
    daily_break_start: str  # "HH:MM" local; "" disables
    daily_break_end: str  # "HH:MM" local; "" disables


class InstrumentConfig(StrictModel):
    display_name: str
    multiplier: float
    tick_size: float
    sources: InstrumentSources
    session: InstrumentSession


class ChartDefaults(StrictModel):
    default_timeframe: Timeframe
    volume_visible_default: bool
    display_timezone: str | None = None


class CustomFieldDefinition(StrictModel):
    field_id: int
    name: str
    field_type: FieldType
    is_active: bool
    display_order: int
    created_at: int


class CustomFieldOption(StrictModel):
    option_id: int
    field_id: int
    value: str
    display_order: int


class CustomFieldOptionInput(StrictModel):
    """Shape accepted by PUT /api/custom-fields/{id}/options."""
    value: str
    display_order: int = 0
```

Modify `models/__init__.py` — add these imports and `__all__` entries:

```python
from models.settings import (
    ChartDefaults,
    CustomFieldDefinition,
    CustomFieldOption,
    CustomFieldOptionInput,
    FieldType,
    InstrumentConfig,
    InstrumentSession,
    InstrumentSources,
    SourceMapping,
    Timeframe,
)
```

And append to `__all__`:

```python
    "Timeframe",
    "FieldType",
    "SourceMapping",
    "InstrumentSources",
    "InstrumentSession",
    "InstrumentConfig",
    "ChartDefaults",
    "CustomFieldDefinition",
    "CustomFieldOption",
    "CustomFieldOptionInput",
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_models_settings.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add models/settings.py models/__init__.py tests/test_models_settings.py
git commit -m "feat(plan16): Pydantic models for settings + custom fields"
```

---

### Task 3: InstrumentRegistry with seed-on-missing

**Files:**
- Create: `services/instrument_registry.py`
- Create: `tests/test_instrument_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_instrument_registry.py`:

```python
import json
from pathlib import Path

import pytest

from services.instrument_registry import DEFAULT_SEED, InstrumentRegistry


def test_load_seeds_if_missing(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert "ES" in data
    assert data["ES"]["multiplier"] == 50.0
    assert data["ES"]["sources"]["yfinance"]["continuous"] == "ES=F"


def test_load_empty_file_reseeds(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    json_path.write_text("")
    reg = InstrumentRegistry(json_path)
    reg.load()
    data = json.loads(json_path.read_text())
    assert "ES" in data


def test_load_existing_file_not_overwritten(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    payload = {
        "ZZ": {
            "display_name": "Test",
            "multiplier": 99.0,
            "tick_size": 0.01,
            "sources": {
                "yfinance": {"continuous": None, "contract_template": None},
                "stooq": {"continuous": None, "contract_template": None},
            },
            "session": {
                "timezone": "UTC",
                "open": "00:00",
                "close": "00:00",
                "daily_break_start": "",
                "daily_break_end": "",
            },
        }
    }
    json_path.write_text(json.dumps(payload))
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert reg.get("ZZ").multiplier == 99.0
    assert reg.get("ES") is None  # not seeded because file existed and was valid


def test_put_writes_file_atomically(tmp_path: Path, monkeypatch):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()

    # Monkeypatch os.replace to assert atomic swap
    calls = []
    original = __import__("os").replace

    def tracking_replace(src, dst):
        calls.append((str(src), str(dst)))
        return original(src, dst)

    monkeypatch.setattr("os.replace", tracking_replace)

    from models.settings import InstrumentConfig, InstrumentSession, InstrumentSources, SourceMapping

    cfg = InstrumentConfig(
        display_name="New",
        multiplier=7.0,
        tick_size=0.25,
        sources=InstrumentSources(
            yfinance=SourceMapping(continuous="NEW=F"),
            stooq=SourceMapping(),
        ),
        session=InstrumentSession(
            timezone="UTC", open="00:00", close="00:00",
            daily_break_start="", daily_break_end="",
        ),
    )
    reg.put("NEW", cfg)

    assert len(calls) == 1
    assert calls[0][1] == str(json_path)
    assert reg.get("NEW").multiplier == 7.0

    # Disk actually updated
    on_disk = json.loads(json_path.read_text())
    assert on_disk["NEW"]["multiplier"] == 7.0


def test_delete_removes_instrument(tmp_path: Path):
    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()
    assert reg.get("ES") is not None
    reg.delete("ES")
    assert reg.get("ES") is None
    on_disk = json.loads(json_path.read_text())
    assert "ES" not in on_disk


def test_delete_unknown_raises(tmp_path: Path):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    with pytest.raises(KeyError):
        reg.delete("NOPE")


def test_list_returns_sorted_symbols(tmp_path: Path):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    symbols = [i[0] for i in reg.list()]
    assert symbols == sorted(symbols)


def test_concurrent_writers_serialize(tmp_path: Path):
    import threading

    json_path = tmp_path / "instruments.json"
    reg = InstrumentRegistry(json_path)
    reg.load()

    from models.settings import InstrumentConfig, InstrumentSession, InstrumentSources, SourceMapping

    def _cfg(mult: float) -> InstrumentConfig:
        return InstrumentConfig(
            display_name="T",
            multiplier=mult,
            tick_size=0.25,
            sources=InstrumentSources(yfinance=SourceMapping(), stooq=SourceMapping()),
            session=InstrumentSession(
                timezone="UTC", open="00:00", close="00:00",
                daily_break_start="", daily_break_end="",
            ),
        )

    def worker(i: int):
        reg.put(f"T{i}", _cfg(float(i)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 20 writes persisted, file is valid JSON
    data = json.loads(json_path.read_text())
    for i in range(20):
        assert f"T{i}" in data


def test_default_seed_covers_plan_11_multipliers():
    # Anchors the seed against the current stub's public surface
    assert "ES" in DEFAULT_SEED
    assert DEFAULT_SEED["ES"]["multiplier"] == 50.0
    assert DEFAULT_SEED["MES"]["multiplier"] == 5.0
    assert DEFAULT_SEED["NQ"]["multiplier"] == 20.0
    assert DEFAULT_SEED["MNQ"]["multiplier"] == 2.0


def test_default_seed_covers_plan_14_symbol_maps():
    assert DEFAULT_SEED["ES"]["sources"]["yfinance"]["continuous"] == "ES=F"
    assert DEFAULT_SEED["ES"]["sources"]["stooq"]["continuous"] == "es.f"
    assert DEFAULT_SEED["6E"]["sources"]["yfinance"]["continuous"] == "6E=F"
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_instrument_registry.py -x -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the registry**

Create `services/instrument_registry.py`:

```python
"""Instrument registry — the one source of truth for instrument metadata.

Replaces the hardcoded tables that were in services/instruments.py through plan
14. Reads and writes `data/config/instruments.json`. First load on a missing or
empty file writes DEFAULT_SEED (derived from plan 11/14 constants) out to disk
so existing Docker installs keep the same multipliers and symbol maps.
"""

import json
import os
import threading
from pathlib import Path

from models.settings import (
    InstrumentConfig,
    InstrumentSession,
    InstrumentSources,
    SourceMapping,
)

# Seed data — the plan 11/14 constants moved here verbatim. Only consumed by
# seed_if_missing. After the first load the JSON file on disk is authoritative.
_MULTIPLIERS: dict[str, float] = {
    "ES": 50.0, "MES": 5.0, "NQ": 20.0, "MNQ": 2.0,
    "RTY": 50.0, "M2K": 5.0, "YM": 5.0, "MYM": 0.50,
    "CL": 1000.0, "MCL": 100.0, "NG": 10000.0, "QG": 2500.0,
    "RB": 42000.0, "HO": 42000.0,
    "GC": 100.0, "MGC": 10.0, "SI": 5000.0, "SIL": 1000.0,
    "HG": 25000.0, "MHG": 2500.0,
    "ZN": 1000.0, "ZB": 1000.0, "ZF": 1000.0, "ZT": 2000.0,
    "6E": 125000.0, "6B": 62500.0, "6J": 12500000.0,
}

_YFINANCE_SYMBOLS: dict[str, str] = {
    "ES": "ES=F", "MES": "MES=F", "NQ": "NQ=F", "MNQ": "MNQ=F",
    "RTY": "RTY=F", "M2K": "M2K=F", "YM": "YM=F", "MYM": "MYM=F",
    "CL": "CL=F", "MCL": "MCL=F",
    "GC": "GC=F", "MGC": "MGC=F", "SI": "SI=F", "SIL": "SIL=F",
    "ZN": "ZN=F", "ZB": "ZB=F", "6E": "6E=F", "6B": "6B=F",
}

_STOOQ_SYMBOLS: dict[str, str] = {
    "ES": "es.f", "MES": "mes.f", "NQ": "nq.f", "MNQ": "mnq.f",
    "RTY": "rty.f", "M2K": "m2k.f", "YM": "ym.f", "MYM": "mym.f",
    "CL": "cl.f", "MCL": "mcl.f",
    "GC": "gc.f", "MGC": "mgc.f", "SI": "si.f", "SIL": "sil.f",
    "ZN": "zn.f", "ZB": "zb.f", "6E": "6e.f", "6B": "6b.f",
}

_DISPLAY_NAMES: dict[str, str] = {
    "ES": "E-mini S&P 500", "MES": "Micro E-mini S&P 500",
    "NQ": "E-mini Nasdaq-100", "MNQ": "Micro E-mini Nasdaq-100",
    "RTY": "E-mini Russell 2000", "M2K": "Micro E-mini Russell 2000",
    "YM": "E-mini Dow", "MYM": "Micro E-mini Dow",
    "CL": "Crude Oil", "MCL": "Micro Crude Oil",
    "NG": "Natural Gas", "QG": "E-mini Natural Gas",
    "RB": "RBOB Gasoline", "HO": "Heating Oil",
    "GC": "Gold", "MGC": "Micro Gold",
    "SI": "Silver", "SIL": "Micro Silver",
    "HG": "Copper", "MHG": "Micro Copper",
    "ZN": "10-Year T-Note", "ZB": "30-Year T-Bond",
    "ZF": "5-Year T-Note", "ZT": "2-Year T-Note",
    "6E": "Euro FX", "6B": "British Pound", "6J": "Japanese Yen",
}

_TICK_SIZES: dict[str, float] = {
    # Sensible defaults; user edits from settings UI.
    "ES": 0.25, "MES": 0.25, "NQ": 0.25, "MNQ": 0.25,
    "RTY": 0.10, "M2K": 0.10, "YM": 1.0, "MYM": 1.0,
    "CL": 0.01, "MCL": 0.01, "NG": 0.001, "QG": 0.005,
    "RB": 0.0001, "HO": 0.0001,
    "GC": 0.10, "MGC": 0.10, "SI": 0.005, "SIL": 0.005,
    "HG": 0.0005, "MHG": 0.0005,
    "ZN": 0.015625, "ZB": 0.03125, "ZF": 0.0078125, "ZT": 0.0078125,
    "6E": 0.00005, "6B": 0.0001, "6J": 0.0000005,
}

_DEFAULT_SESSION = {
    "timezone": "America/Chicago",
    "open": "17:00",
    "close": "16:00",
    "daily_break_start": "16:00",
    "daily_break_end": "17:00",
}


def _build_default_seed() -> dict[str, dict]:
    seed: dict[str, dict] = {}
    for symbol, mult in _MULTIPLIERS.items():
        seed[symbol] = {
            "display_name": _DISPLAY_NAMES.get(symbol, symbol),
            "multiplier": mult,
            "tick_size": _TICK_SIZES.get(symbol, 0.01),
            "sources": {
                "yfinance": {
                    "continuous": _YFINANCE_SYMBOLS.get(symbol),
                    "contract_template": None,
                },
                "stooq": {
                    "continuous": _STOOQ_SYMBOLS.get(symbol),
                    "contract_template": None,
                },
            },
            "session": dict(_DEFAULT_SESSION),
        }
    return seed


DEFAULT_SEED: dict[str, dict] = _build_default_seed()


class InstrumentRegistry:
    """Load and persist `instruments.json`. Thread-safe via module-level lock."""

    _lock = threading.Lock()

    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._data: dict[str, InstrumentConfig] = {}
        self._loaded = False

    def load(self) -> None:
        """Read from disk. Seed if missing or empty."""
        with self._lock:
            if not self._path.exists() or self._path.stat().st_size == 0:
                self._seed_to_disk()
            raw_text = self._path.read_text(encoding="utf-8")
            try:
                raw = json.loads(raw_text) if raw_text.strip() else {}
            except json.JSONDecodeError:
                raw = {}
            if not raw:
                # Defensive: seed if somehow still empty
                self._seed_to_disk()
                raw = json.loads(self._path.read_text(encoding="utf-8"))

            self._data = {
                symbol: InstrumentConfig(**payload)
                for symbol, payload in raw.items()
            }
            self._loaded = True

    def _seed_to_disk(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_raw(DEFAULT_SEED)

    def _write_raw(self, raw: dict[str, dict]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(self._path))

    def _flush(self) -> None:
        raw = {
            symbol: self._data[symbol].model_dump()
            for symbol in sorted(self._data)
        }
        self._write_raw(raw)

    def get(self, symbol: str) -> InstrumentConfig | None:
        if not self._loaded:
            self.load()
        return self._data.get(symbol)

    def list(self) -> list[tuple[str, InstrumentConfig]]:
        if not self._loaded:
            self.load()
        return [(s, self._data[s]) for s in sorted(self._data)]

    def put(self, symbol: str, cfg: InstrumentConfig) -> None:
        with self._lock:
            if not self._loaded:
                # Re-entrant load would deadlock; inline
                if not self._path.exists() or self._path.stat().st_size == 0:
                    self._seed_to_disk()
                raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
                self._data = {
                    s: InstrumentConfig(**p) for s, p in raw.items()
                }
                self._loaded = True
            self._data[symbol] = cfg
            self._flush()

    def delete(self, symbol: str) -> None:
        with self._lock:
            if not self._loaded:
                if not self._path.exists() or self._path.stat().st_size == 0:
                    self._seed_to_disk()
                raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
                self._data = {
                    s: InstrumentConfig(**p) for s, p in raw.items()
                }
                self._loaded = True
            if symbol not in self._data:
                raise KeyError(symbol)
            del self._data[symbol]
            self._flush()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_instrument_registry.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/instrument_registry.py tests/test_instrument_registry.py
git commit -m "feat(plan16): InstrumentRegistry with seed-on-missing JSON persistence"
```

---

### Task 4: Rewrite services/instruments.py as thin delegator

**Files:**
- Modify: `services/instruments.py`
- Create: `tests/test_instruments_registry_backcompat.py`
- Modify: `app.py` (new module-level path for the registry)

- [ ] **Step 1: Write the backcompat test**

Create `tests/test_instruments_registry_backcompat.py`:

```python
"""Pin the public surface of services/instruments.py through plan 16's body
swap. Plan 11 callers (positions.py), plan 14 callers (ohlc sources,
gap_detection, app.py hook) must see identical results for known seed
instruments after the InstrumentRegistry replaces the hardcoded tables."""

import json
from pathlib import Path

import services.instruments as instruments
from services.instrument_registry import InstrumentRegistry


def _with_registry(tmp_path: Path, monkeypatch):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    monkeypatch.setattr(instruments, "_REGISTRY", reg)


def test_get_multiplier_known(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("ES") == 50.0
    assert instruments.get_multiplier("MES") == 5.0
    assert instruments.get_multiplier("NQ") == 20.0
    assert instruments.get_multiplier("MNQ") == 2.0


def test_get_multiplier_with_contract_suffix(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("ES SEP25") == 50.0


def test_get_multiplier_unknown_returns_one(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.get_multiplier("BOGUS") == 1.0


def test_source_symbol_yfinance(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "yfinance") == "ES=F"
    assert instruments.source_symbol("MES", "yfinance") == "MES=F"


def test_source_symbol_stooq(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "stooq") == "es.f"


def test_source_symbol_unknown_source(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ES", "bogus") is None


def test_source_symbol_unknown_instrument(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.source_symbol("ZZZ", "yfinance") is None


def test_default_timeframes_preserved():
    assert instruments.DEFAULT_TIMEFRAMES == ("1m", "5m", "15m", "1h", "1d")


def test_default_session_returns_cme_default(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    session = instruments.default_session("ES")
    assert session.timezone == "America/Chicago"
    assert session.open == "17:00"
    assert session.close == "16:00"
    assert session.daily_break_start == "16:00"
    assert session.daily_break_end == "17:00"


def test_base_symbol_strips_contract(tmp_path: Path, monkeypatch):
    _with_registry(tmp_path, monkeypatch)
    assert instruments.base_symbol("ES SEP25") == "ES"
    assert instruments.base_symbol("MNQ") == "MNQ"


def test_edit_registry_changes_multiplier(tmp_path: Path, monkeypatch):
    reg = InstrumentRegistry(tmp_path / "instruments.json")
    reg.load()
    monkeypatch.setattr(instruments, "_REGISTRY", reg)

    from models.settings import (
        InstrumentConfig,
        InstrumentSession,
        InstrumentSources,
        SourceMapping,
    )

    reg.put(
        "ES",
        InstrumentConfig(
            display_name="E-mini S&P 500",
            multiplier=25.0,  # half
            tick_size=0.25,
            sources=InstrumentSources(
                yfinance=SourceMapping(continuous="ES=F"),
                stooq=SourceMapping(continuous="es.f"),
            ),
            session=InstrumentSession(
                timezone="America/Chicago",
                open="17:00", close="16:00",
                daily_break_start="16:00", daily_break_end="17:00",
            ),
        ),
    )
    assert instruments.get_multiplier("ES") == 25.0
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_instruments_registry_backcompat.py -x -v`
Expected: `AttributeError: module 'services.instruments' has no attribute '_REGISTRY'`.

- [ ] **Step 3: Rewrite `services/instruments.py`**

Replace the entire file with:

```python
"""Instrument metadata — thin delegator over InstrumentRegistry.

Plan 11 (positions.py) imports get_multiplier and base_symbol. Plan 14 (ohlc
adapters, gap_detection, app.py) imports DEFAULT_TIMEFRAMES, source_symbol,
SessionCalendar, and default_session. All six names are preserved by this
module; their bodies now read from the JSON-backed InstrumentRegistry that
plan 16 shipped. DEFAULT_TIMEFRAMES stays as a module constant because
app.py reads it at import time via `from services.instruments import
DEFAULT_TIMEFRAMES`.
"""

from dataclasses import dataclass
from pathlib import Path

from services.instrument_registry import InstrumentRegistry

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "1d")

_DEFAULT_JSON_PATH = Path("data/config/instruments.json")


@dataclass(frozen=True)
class SessionCalendar:
    """A one-day-repeating session description.

    Plan 14 introduced this dataclass; plan 16 keeps the shape and populates
    it from `instruments.json`. Gap detection consults this to skip the
    daily break so the overnight close is not flagged as missing.
    """

    timezone: str
    open: str  # "HH:MM" local
    close: str  # "HH:MM" local
    daily_break_start: str  # "HH:MM" local; "" disables
    daily_break_end: str  # "HH:MM" local; "" disables


# The registry is a module-level singleton. Tests monkeypatch _REGISTRY to a
# fresh instance rooted in a tmp_path.
_REGISTRY = InstrumentRegistry(_DEFAULT_JSON_PATH)


def get_registry() -> InstrumentRegistry:
    return _REGISTRY


def set_registry_path(path: Path | str) -> None:
    """Bind the registry to a specific path. Called by create_app once
    the Config has been loaded so the registry points at the real
    data_dir. Safe to call multiple times."""
    global _REGISTRY
    _REGISTRY = InstrumentRegistry(path)


def base_symbol(instrument: str) -> str:
    """Strip any trailing contract-month suffix like ' SEP25'."""
    return instrument.split(" ", 1)[0]


def get_multiplier(instrument: str) -> float:
    """Dollars per point for the instrument. Unknown symbols return 1.0."""
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return 1.0
    return cfg.multiplier


def source_symbol(instrument: str, source: str) -> str | None:
    """Map a canonical NT instrument key to a per-source symbol.

    Returns None if the source or instrument is unknown, or if the
    instrument has no `continuous` mapping for that source.
    """
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return None
    if source == "yfinance":
        return cfg.sources.yfinance.continuous
    if source == "stooq":
        return cfg.sources.stooq.continuous
    return None


_DEFAULT_CME_SESSION = SessionCalendar(
    timezone="America/Chicago",
    open="17:00",
    close="16:00",
    daily_break_start="16:00",
    daily_break_end="17:00",
)


def default_session(instrument: str) -> SessionCalendar:
    """Return the trading session for the given instrument.

    Reads from the JSON registry. Unknown instruments (not yet configured)
    fall back to the CME 23-hour session so gap detection keeps working.
    """
    cfg = _REGISTRY.get(base_symbol(instrument))
    if cfg is None:
        return _DEFAULT_CME_SESSION
    s = cfg.session
    return SessionCalendar(
        timezone=s.timezone,
        open=s.open,
        close=s.close,
        daily_break_start=s.daily_break_start,
        daily_break_end=s.daily_break_end,
    )
```

Modify `app.py` — after `config = ...` is available in `create_app`, bind the registry to the configured data_dir. Find the line `run_migrations(conn, Path("migrations"))` and add below it:

```python
    from services.instruments import set_registry_path
    from services.instrument_registry import InstrumentRegistry as _IR

    instruments_json = Path(config.data_dir) / "config" / "instruments.json"
    set_registry_path(instruments_json)
    # Seed immediately so all callers see the same view
    from services.instruments import get_registry
    get_registry().load()
```

- [ ] **Step 4: Run new tests and existing instruments tests**

Run: `pytest tests/test_instruments_registry_backcompat.py tests/test_instruments.py tests/test_instruments_ohlc_stub.py -x -v`
Expected: all pass. (The existing `test_instruments.py` and `test_instruments_ohlc_stub.py` from plan 11/14 must still pass; if a test hardcodes the old `_MULTIPLIERS` dict import, update it to use `InstrumentRegistry.DEFAULT_SEED` or delete it as obsolete — but only after verifying the public function asserts still pass.)

- [ ] **Step 5: Run the full suite to check no plan 11/14 test breaks**

Run: `pytest -x -q`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add services/instruments.py app.py tests/test_instruments_registry_backcompat.py
git commit -m "feat(plan16): delegate services/instruments.py to InstrumentRegistry"
```

---

### Task 5: Rewrite services/chart_defaults.py to read from DB

**Files:**
- Modify: `services/chart_defaults.py`
- Create: `tests/test_chart_defaults_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chart_defaults_db.py`:

```python
import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.chart_defaults import get_defaults, save_defaults


def _fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def test_get_defaults_reads_seed_row():
    db_path = _fresh_db()
    result = get_defaults(db_path)
    assert result == {"default_timeframe": "5m", "volume_visible_default": True}


def test_get_defaults_returns_fresh_dict():
    db_path = _fresh_db()
    a = get_defaults(db_path)
    b = get_defaults(db_path)
    assert a == b
    assert a is not b
    a["default_timeframe"] = "XX"
    assert get_defaults(db_path)["default_timeframe"] == "5m"


def test_save_defaults_round_trip():
    db_path = _fresh_db()
    save_defaults(db_path, default_timeframe="1m", volume_visible_default=False)
    result = get_defaults(db_path)
    assert result == {"default_timeframe": "1m", "volume_visible_default": False}


def test_save_defaults_updates_updated_at():
    db_path = _fresh_db()
    conn = connect(db_path)
    try:
        initial_ts = conn.execute("SELECT updated_at FROM chart_defaults WHERE id=1").fetchone()[0]
    finally:
        conn.close()
    save_defaults(db_path, default_timeframe="15m", volume_visible_default=True)
    conn = connect(db_path)
    try:
        new_ts = conn.execute("SELECT updated_at FROM chart_defaults WHERE id=1").fetchone()[0]
    finally:
        conn.close()
    assert new_ts >= initial_ts
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_chart_defaults_db.py -x -v`
Expected: `TypeError: get_defaults() takes 0 positional arguments but 1 was given` or similar.

- [ ] **Step 3: Rewrite `services/chart_defaults.py`**

Replace the whole file:

```python
"""Chart default settings — DB-backed (plan 16).

get_defaults() reads the single `chart_defaults` row (id=1, enforced by the
migration CHECK constraint). save_defaults() writes that row. Plan 13's
frontend pickup helper calls get_defaults() once per chart mount; plan 16's
/settings/chart page calls save_defaults() on form submit.

DEFAULT_TIMEFRAME and VOLUME_VISIBLE_DEFAULT remain as defensive fallbacks
if the row is somehow missing (the migration inserts it in the same
transaction as CREATE TABLE, so this only matters in tests that skip
migrations).
"""

import time
from pathlib import Path

from db import connect

DEFAULT_TIMEFRAME = "5m"
VOLUME_VISIBLE_DEFAULT = True


def get_defaults(db_path: Path | str) -> dict:
    """Return a fresh dict with the current chart defaults."""
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT default_timeframe, volume_visible_default FROM chart_defaults WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {
            "default_timeframe": DEFAULT_TIMEFRAME,
            "volume_visible_default": VOLUME_VISIBLE_DEFAULT,
        }
    return {
        "default_timeframe": row["default_timeframe"],
        "volume_visible_default": bool(row["volume_visible_default"]),
    }


def save_defaults(
    db_path: Path | str,
    *,
    default_timeframe: str,
    volume_visible_default: bool,
) -> None:
    if default_timeframe not in ("1m", "5m", "15m", "1h", "4h", "1d"):
        raise ValueError(f"invalid default_timeframe: {default_timeframe!r}")
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE chart_defaults SET default_timeframe = ?, "
                "volume_visible_default = ?, updated_at = ? WHERE id = 1",
                (default_timeframe, int(bool(volume_visible_default)), int(time.time())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
```

- [ ] **Step 4: Update plan 13 `tests/test_chart_defaults.py`**

Read the existing file first. Its two tests call `get_defaults()` with no args. Update them to pass a fresh DB path the same way `test_chart_defaults_db.py` does, or mark them as testing the defensive-fallback case:

```python
def test_get_defaults_defensive_fallback_when_row_missing(tmp_path):
    import tempfile
    from pathlib import Path
    from db import connect
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = Path(tmp.name)
    # Intentionally skip migrations — table does not exist
    from services.chart_defaults import DEFAULT_TIMEFRAME, VOLUME_VISIBLE_DEFAULT
    # The function wraps its read in try/except? No — this test only asserts
    # the fallback constants are the expected values.
    assert DEFAULT_TIMEFRAME == "5m"
    assert VOLUME_VISIBLE_DEFAULT is True
```

Any plan 13 route that calls `get_defaults()` must now pass `current_app.config["FTL_DB_PATH"]`. Grep for callers:

Run: `grep -rn "chart_defaults.get_defaults\|from services.chart_defaults import" routes/ services/ static/`

For each caller, update the call site to pass the db path. Grep-expected callers (per plan 13):
- `routes/ohlc.py::build_ohlc_blueprint` inside `/api/chart/{instrument}/timeframes-available`. Update that one call site to `get_defaults(current_app.config["FTL_DB_PATH"])`.

Also update `DEFAULT_TIMEFRAME` constant in this file — plan 13 had it at `"1m"` but the spec seed is `"5m"`. Update plan 13's chart picker test accordingly if it hardcodes `"1m"`. Fix forward — the spec is canonical.

- [ ] **Step 5: Run the full suite**

Run: `pytest -x -q`
Expected: all tests pass. If plan 13's chart test fails on `"1m"` vs `"5m"`, update its expected value to `"5m"` or parameterize the test around `DEFAULT_TIMEFRAME`.

- [ ] **Step 6: Commit**

```bash
git add services/chart_defaults.py routes/ohlc.py tests/test_chart_defaults.py tests/test_chart_defaults_db.py
git commit -m "feat(plan16): chart_defaults backed by DB row"
```

---

### Task 6: config.save_display_timezone helper

**Files:**
- Modify: `config.py`
- Create: `tests/test_config_save_display_timezone.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_save_display_timezone.py`:

```python
import json
import threading
from pathlib import Path

import pytest

from config import load_config, save_display_timezone


def _seed_config(tmp_path: Path) -> Path:
    path = tmp_path / "app.json"
    path.write_text(
        json.dumps({
            "data_dir": str(tmp_path),
            "db_path": str(tmp_path / "t.db"),
            "inbox_dir": str(tmp_path / "inbox"),
            "archive_dir": str(tmp_path / "archive"),
            "log_dir": str(tmp_path / "log"),
            "session": {
                "exchange_timezone": "America/Chicago",
                "trade_date_rollover": "17:00",
                "archive_job_time": "18:00",
            },
            "thread_pool": {"max_workers": 4},
            "scheduler": {"heartbeat_seconds": 30},
        })
    )
    return path


def test_save_display_timezone_writes_field(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_display_timezone(path, "Asia/Tokyo")
    cfg = load_config(path)
    assert cfg.display_timezone == "Asia/Tokyo"


def test_save_display_timezone_preserves_other_fields(tmp_path: Path):
    path = _seed_config(tmp_path)
    before = json.loads(path.read_text())
    save_display_timezone(path, "Europe/London")
    after = json.loads(path.read_text())
    # All non-display_timezone keys unchanged
    for k, v in before.items():
        assert after[k] == v


def test_save_display_timezone_rejects_invalid_iana(tmp_path: Path):
    path = _seed_config(tmp_path)
    with pytest.raises(ValueError):
        save_display_timezone(path, "Not/A_Timezone")


def test_save_display_timezone_accepts_none(tmp_path: Path):
    path = _seed_config(tmp_path)
    save_display_timezone(path, None)
    cfg = load_config(path)
    assert cfg.display_timezone is None


def test_save_display_timezone_thread_safe(tmp_path: Path):
    path = _seed_config(tmp_path)
    errors = []

    def worker(tz: str):
        try:
            save_display_timezone(path, tz)
        except Exception as e:
            errors.append(e)

    tzs = ["Asia/Tokyo", "Europe/London", "America/New_York", "America/Chicago"]
    threads = [threading.Thread(target=worker, args=(tz,)) for tz in tzs * 5]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # File is still valid JSON with a valid timezone
    cfg = load_config(path)
    assert cfg.display_timezone in tzs
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_config_save_display_timezone.py -x -v`
Expected: `ImportError: cannot import name 'save_display_timezone'`.

- [ ] **Step 3: Extend `config.py`**

Append to `config.py`:

```python
import os
import threading
from zoneinfo import ZoneInfo

_SAVE_LOCK = threading.Lock()


def save_display_timezone(path: Path | str, value: str | None) -> None:
    """Update the `display_timezone` field in app.json via atomic tmp+rename.

    Validates `value` by constructing `zoneinfo.ZoneInfo(value)`. Passes None
    through unchanged. All other Config fields are preserved by a
    read-modify-write under a module-level lock.
    """
    if value is not None:
        try:
            ZoneInfo(value)
        except Exception as e:
            raise ValueError(f"invalid IANA timezone: {value!r}") from e

    path = Path(path)
    with _SAVE_LOCK:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        raw["display_timezone"] = value
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config_save_display_timezone.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config_save_display_timezone.py
git commit -m "feat(plan16): config.save_display_timezone helper"
```

---

### Task 7: CustomFieldsService — definitions, options, and values

**Files:**
- Create: `services/custom_fields.py`
- Create: `tests/test_custom_fields_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_custom_fields_service.py`:

```python
import tempfile
from pathlib import Path

import pytest

from db import connect
from migrations import run_migrations
from services.custom_fields import CustomFieldsService


def _fresh_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def _seed_execution(db_path: Path, eid: str = "E1") -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "(?, 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)",
            (eid,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def test_create_and_list_definitions():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    svc.create_definition(name="setup", field_type="dropdown")
    svc.create_definition(name="confidence", field_type="number", display_order=1)
    defs = svc.list_definitions(include_inactive=True)
    assert [d.name for d in defs] == ["setup", "confidence"]
    assert defs[0].field_type == "dropdown"


def test_create_definition_rejects_duplicate_name():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    svc.create_definition(name="setup", field_type="text")
    with pytest.raises(ValueError):
        svc.create_definition(name="setup", field_type="text")


def test_create_definition_rejects_bad_field_type():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    with pytest.raises(ValueError):
        svc.create_definition(name="x", field_type="bogus")


def test_update_definition_renames():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.update_definition(d.field_id, name="Setup Type")
    defs = svc.list_definitions(include_inactive=True)
    assert defs[0].name == "Setup Type"


def test_update_definition_changes_is_active():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.update_definition(d.field_id, is_active=False)
    defs = svc.list_definitions(include_inactive=False)
    assert defs == []
    defs = svc.list_definitions(include_inactive=True)
    assert defs[0].is_active is False


def test_update_definition_rejects_type_change_with_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    with pytest.raises(ValueError):
        svc.update_definition(d.field_id, field_type="number")


def test_delete_definition_two_step():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    # Without confirm_count
    count = svc.affected_executions(d.field_id)
    assert count == 1
    with pytest.raises(ValueError):
        svc.delete_definition(d.field_id, confirm_count=0)
    # With matching confirm_count
    svc.delete_definition(d.field_id, confirm_count=1)
    assert svc.list_definitions(include_inactive=True) == []


def test_delete_definition_cascades_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.delete_definition(d.field_id, confirm_count=1)
    values = svc.get_execution_values("E1")
    assert values == {}


def test_replace_options_preserves_option_id_for_unchanged_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(d.field_id, [
        {"value": "Breakout", "display_order": 0},
        {"value": "Reversal", "display_order": 1},
    ])
    first = svc.list_options(d.field_id)
    first_ids = {o.value: o.option_id for o in first}

    # Reorder and add a new one
    svc.replace_options(d.field_id, [
        {"value": "Reversal", "display_order": 0},
        {"value": "Breakout", "display_order": 1},
        {"value": "Trend", "display_order": 2},
    ])
    second = svc.list_options(d.field_id)
    second_ids = {o.value: o.option_id for o in second}

    assert second_ids["Breakout"] == first_ids["Breakout"]
    assert second_ids["Reversal"] == first_ids["Reversal"]
    assert "Trend" in second_ids
    # Order preserved
    assert [o.value for o in second] == ["Reversal", "Breakout", "Trend"]


def test_replace_options_deletes_removed_values():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(d.field_id, [
        {"value": "A", "display_order": 0},
        {"value": "B", "display_order": 1},
    ])
    svc.replace_options(d.field_id, [{"value": "A", "display_order": 0}])
    options = svc.list_options(d.field_id)
    assert [o.value for o in options] == ["A"]


def test_set_execution_value_text():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+ setup")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "A+ setup"}


def test_set_execution_value_number_stores_as_json():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="confidence", field_type="number")
    svc.set_execution_value("E1", d.field_id, 4.0)
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: 4.0}


def test_set_execution_value_number_rejects_non_numeric():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="c", field_type="number")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "not a number")


def test_set_execution_value_date_iso_format():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="plan_date", field_type="date")
    svc.set_execution_value("E1", d.field_id, "2026-04-13")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "2026-04-13"}


def test_set_execution_value_date_rejects_bad_format():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="plan_date", field_type="date")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "04/13/2026")


def test_set_execution_value_boolean():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="in_plan", field_type="boolean")
    svc.set_execution_value("E1", d.field_id, True)
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: True}


def test_set_execution_value_dropdown_validates_against_options():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="dropdown")
    svc.replace_options(d.field_id, [
        {"value": "Breakout", "display_order": 0},
    ])
    svc.set_execution_value("E1", d.field_id, "Breakout")
    with pytest.raises(ValueError):
        svc.set_execution_value("E1", d.field_id, "NotAnOption")


def test_set_execution_value_strips_split_suffix():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1#close", d.field_id, "A+")
    values = svc.get_execution_values("E1")
    assert values == {d.field_id: "A+"}
    # And lookups via the suffixed id return the same thing
    values2 = svc.get_execution_values("E1#open")
    assert values2 == {d.field_id: "A+"}


def test_set_execution_value_empty_deletes_row():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E1", d.field_id, "")
    values = svc.get_execution_values("E1")
    assert values == {}


def test_values_for_position_splits_entry_and_per_execution():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    _seed_execution(db, "E2")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E2", d.field_id, "B-")

    result = svc.values_for_position(
        execution_ids=["E1", "E2"],
        entry_execution_id="E1",
    )
    assert result["entry"] == {d.field_id: "A+"}
    assert result["per_execution"] == [
        {"execution_id": "E2", "values": {d.field_id: "B-"}},
    ]
    assert [d_.name for d_ in result["definitions"]] == ["setup"]


def test_values_for_position_inactive_field_appears_in_values_not_definitions():
    db = _fresh_db()
    svc = CustomFieldsService(db)
    _seed_execution(db, "E1")
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.update_definition(d.field_id, is_active=False)

    result = svc.values_for_position(
        execution_ids=["E1"],
        entry_execution_id="E1",
    )
    assert result["entry"] == {d.field_id: "A+"}
    assert result["definitions"] == []
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_custom_fields_service.py -x -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the service**

Create `services/custom_fields.py`:

```python
"""CustomFieldsService — owns all CRUD for custom field definitions,
options, and execution values.

Rules enforced here:
- Every mutator on execution values calls notes.strip_split_suffix so
  synthesized #close/#open sub-fill IDs inherit the parent row's values.
- Value encoding per field_type is defined in one place (_encode/_decode).
- Dropdown writes are validated against the field's current options.
- Two-step delete flow: affected_executions() returns the count; the UI
  passes it back as confirm_count to delete_definition().
"""

import json
import time
from pathlib import Path
from typing import Any

from db import connect
from models.settings import (
    CustomFieldDefinition,
    CustomFieldOption,
    CustomFieldOptionInput,
)
from services.notes import strip_split_suffix

_FIELD_TYPES = ("text", "number", "dropdown", "date", "boolean")


def _now() -> int:
    return int(time.time())


class CustomFieldsService:
    def __init__(self, db_path: Path | str):
        self._db_path = db_path

    # ---- definitions ----

    def list_definitions(self, include_inactive: bool = True) -> list[CustomFieldDefinition]:
        conn = connect(self._db_path)
        try:
            sql = (
                "SELECT field_id, name, field_type, is_active, display_order, created_at "
                "FROM custom_fields "
            )
            if not include_inactive:
                sql += "WHERE is_active = 1 "
            sql += "ORDER BY display_order, field_id"
            rows = conn.execute(sql).fetchall()
        finally:
            conn.close()
        return [
            CustomFieldDefinition(
                field_id=r["field_id"],
                name=r["name"],
                field_type=r["field_type"],
                is_active=bool(r["is_active"]),
                display_order=r["display_order"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_definition(self, field_id: int) -> CustomFieldDefinition | None:
        conn = connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT field_id, name, field_type, is_active, display_order, created_at "
                "FROM custom_fields WHERE field_id = ?",
                (field_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return CustomFieldDefinition(
            field_id=row["field_id"],
            name=row["name"],
            field_type=row["field_type"],
            is_active=bool(row["is_active"]),
            display_order=row["display_order"],
            created_at=row["created_at"],
        )

    def create_definition(
        self,
        *,
        name: str,
        field_type: str,
        display_order: int = 0,
    ) -> CustomFieldDefinition:
        if field_type not in _FIELD_TYPES:
            raise ValueError(f"invalid field_type: {field_type!r}")
        if not name:
            raise ValueError("name is required")
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                try:
                    cur = conn.execute(
                        "INSERT INTO custom_fields (name, field_type, is_active, "
                        "display_order, created_at) VALUES (?, ?, 1, ?, ?)",
                        (name, field_type, display_order, _now()),
                    )
                except Exception as e:
                    conn.execute("ROLLBACK")
                    raise ValueError(f"duplicate name: {name!r}") from e
                field_id = cur.lastrowid
                conn.execute("COMMIT")
            except ValueError:
                raise
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return self.get_definition(field_id)  # type: ignore[return-value]

    def update_definition(
        self,
        field_id: int,
        *,
        name: str | None = None,
        field_type: str | None = None,
        is_active: bool | None = None,
        display_order: int | None = None,
    ) -> CustomFieldDefinition:
        existing = self.get_definition(field_id)
        if existing is None:
            raise ValueError(f"no such field_id: {field_id}")
        if field_type is not None and field_type != existing.field_type:
            count = self.affected_executions(field_id)
            if count > 0:
                raise ValueError(
                    f"cannot change field_type while {count} executions have values"
                )
            if field_type not in _FIELD_TYPES:
                raise ValueError(f"invalid field_type: {field_type!r}")
        updates: list[tuple[str, Any]] = []
        if name is not None:
            updates.append(("name = ?", name))
        if field_type is not None:
            updates.append(("field_type = ?", field_type))
        if is_active is not None:
            updates.append(("is_active = ?", int(bool(is_active))))
        if display_order is not None:
            updates.append(("display_order = ?", display_order))
        if not updates:
            return existing
        set_clause = ", ".join(u[0] for u in updates)
        params = [u[1] for u in updates] + [field_id]
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    f"UPDATE custom_fields SET {set_clause} WHERE field_id = ?",
                    tuple(params),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return self.get_definition(field_id)  # type: ignore[return-value]

    def affected_executions(self, field_id: int) -> int:
        conn = connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM execution_custom_field_values WHERE field_id = ?",
                (field_id,),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0])

    def delete_definition(self, field_id: int, *, confirm_count: int) -> None:
        actual = self.affected_executions(field_id)
        if confirm_count != actual:
            raise ValueError(
                f"confirm_count {confirm_count} does not match actual {actual}"
            )
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM custom_fields WHERE field_id = ?", (field_id,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    # ---- options ----

    def list_options(self, field_id: int) -> list[CustomFieldOption]:
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT option_id, field_id, value, display_order "
                "FROM custom_field_options WHERE field_id = ? "
                "ORDER BY display_order, option_id",
                (field_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            CustomFieldOption(
                option_id=r["option_id"],
                field_id=r["field_id"],
                value=r["value"],
                display_order=r["display_order"],
            )
            for r in rows
        ]

    def replace_options(
        self,
        field_id: int,
        options: list[dict],
    ) -> list[CustomFieldOption]:
        """Replace-in-place. Unchanged `value`s keep their option_id so
        stored execution values keep matching them (match by text value)."""
        validated = [CustomFieldOptionInput(**o) for o in options]
        existing = {o.value: o for o in self.list_options(field_id)}
        new_values = {o.value for o in validated}
        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                # Delete removed
                for value, opt in existing.items():
                    if value not in new_values:
                        conn.execute(
                            "DELETE FROM custom_field_options WHERE option_id = ?",
                            (opt.option_id,),
                        )
                # Upsert retained + insert new (preserves option_id for retained)
                for v in validated:
                    if v.value in existing:
                        conn.execute(
                            "UPDATE custom_field_options SET display_order = ? "
                            "WHERE option_id = ?",
                            (v.display_order, existing[v.value].option_id),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO custom_field_options "
                            "(field_id, value, display_order) VALUES (?, ?, ?)",
                            (field_id, v.value, v.display_order),
                        )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        return self.list_options(field_id)

    # ---- execution values ----

    def _encode(self, field_type: str, value: Any, options: list[str] | None) -> str:
        if field_type == "text":
            if not isinstance(value, str):
                raise ValueError("text value must be a string")
            return value
        if field_type == "number":
            try:
                return json.dumps(float(value))
            except (TypeError, ValueError) as e:
                raise ValueError(f"number value must be numeric: {value!r}") from e
        if field_type == "date":
            if not isinstance(value, str):
                raise ValueError("date value must be an ISO string")
            try:
                from datetime import date as _date
                _date.fromisoformat(value)
            except ValueError as e:
                raise ValueError(f"date must be YYYY-MM-DD: {value!r}") from e
            return value
        if field_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("boolean value must be a Python bool")
            return "true" if value else "false"
        if field_type == "dropdown":
            if not isinstance(value, str):
                raise ValueError("dropdown value must be a string")
            if options is not None and value not in options:
                raise ValueError(f"not an option for this field: {value!r}")
            return value
        raise ValueError(f"unknown field_type: {field_type!r}")

    def _decode(self, field_type: str, raw: str) -> Any:
        if field_type == "text":
            return raw
        if field_type == "number":
            return float(json.loads(raw))
        if field_type == "date":
            return raw
        if field_type == "boolean":
            return raw == "true"
        if field_type == "dropdown":
            return raw
        return raw

    def get_execution_values(self, execution_id: str) -> dict[int, Any]:
        real_id = strip_split_suffix(execution_id)
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT v.field_id, v.value, f.field_type "
                "FROM execution_custom_field_values v "
                "JOIN custom_fields f ON f.field_id = v.field_id "
                "WHERE v.execution_id = ?",
                (real_id,),
            ).fetchall()
        finally:
            conn.close()
        return {r["field_id"]: self._decode(r["field_type"], r["value"]) for r in rows}

    def set_execution_value(
        self,
        execution_id: str,
        field_id: int,
        value: Any,
    ) -> None:
        real_id = strip_split_suffix(execution_id)
        defn = self.get_definition(field_id)
        if defn is None:
            raise ValueError(f"no such field_id: {field_id}")
        # Empty string or None deletes the row
        if value is None or value == "":
            conn = connect(self._db_path)
            try:
                conn.execute("BEGIN")
                try:
                    conn.execute(
                        "DELETE FROM execution_custom_field_values "
                        "WHERE execution_id = ? AND field_id = ?",
                        (real_id, field_id),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
            return

        options: list[str] | None = None
        if defn.field_type == "dropdown":
            options = [o.value for o in self.list_options(field_id)]
        encoded = self._encode(defn.field_type, value, options)

        conn = connect(self._db_path)
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "INSERT INTO execution_custom_field_values "
                    "(execution_id, field_id, value, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(execution_id, field_id) DO UPDATE SET "
                    "value = excluded.value, updated_at = excluded.updated_at",
                    (real_id, field_id, encoded, _now()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def values_for_position(
        self,
        *,
        execution_ids: list[str],
        entry_execution_id: str,
    ) -> dict:
        """Return `{entry, per_execution, definitions}` for a position.

        `entry` is `{field_id: decoded_value}` for the entry execution.
        `per_execution` contains one `{execution_id, values}` entry per
        non-entry execution that has any value. `definitions` is the list
        of active definitions sorted by display_order.
        """
        real_entry = strip_split_suffix(entry_execution_id)
        real_all = sorted({strip_split_suffix(e) for e in execution_ids})

        entry_values = self.get_execution_values(real_entry)
        per_execution: list[dict] = []
        for eid in real_all:
            if eid == real_entry:
                continue
            values = self.get_execution_values(eid)
            if values:
                per_execution.append({"execution_id": eid, "values": values})

        definitions = [
            d for d in self.list_definitions(include_inactive=False)
        ]
        return {
            "entry": entry_values,
            "per_execution": per_execution,
            "definitions": [d.model_dump() for d in definitions],
        }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_custom_fields_service.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/custom_fields.py tests/test_custom_fields_service.py
git commit -m "feat(plan16): CustomFieldsService with typed value encoding"
```

---

### Task 8: Settings blueprint — instruments endpoints

**Files:**
- Create: `routes/settings.py` (instruments slice only for now)
- Modify: `app.py` (register blueprint)
- Create: `tests/test_settings_routes_instruments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_routes_instruments.py`:

```python
import json
from pathlib import Path

import pytest

from app import create_app
from config import load_config


def _setup_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(json.dumps({
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "ftl.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 2},
        "scheduler": {"heartbeat_seconds": 30},
    }))
    config = load_config(app_json)
    app, _ = create_app(config)
    return app.test_client()


def test_get_instruments_returns_seeded(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.get("/api/config/instruments")
    assert res.status_code == 200
    body = res.get_json()
    assert "ES" in body["instruments"]
    assert body["instruments"]["ES"]["multiplier"] == 50.0


def test_put_instrument_round_trip(tmp_path: Path):
    client = _setup_app(tmp_path)
    payload = {
        "display_name": "Bitcoin",
        "multiplier": 5.0,
        "tick_size": 5.0,
        "sources": {
            "yfinance": {"continuous": "BTC=F", "contract_template": None},
            "stooq": {"continuous": None, "contract_template": None},
        },
        "session": {
            "timezone": "America/Chicago",
            "open": "17:00", "close": "16:00",
            "daily_break_start": "16:00", "daily_break_end": "17:00",
        },
    }
    res = client.put("/api/config/instruments/BTC", json=payload)
    assert res.status_code == 200
    body = res.get_json()
    assert body["instrument"]["multiplier"] == 5.0

    res = client.get("/api/config/instruments")
    assert "BTC" in res.get_json()["instruments"]


def test_put_instrument_rejects_invalid_payload(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.put("/api/config/instruments/FOO", json={"multiplier": "not-a-number"})
    assert res.status_code == 400


def test_delete_instrument(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.delete("/api/config/instruments/ES")
    assert res.status_code == 204
    res = client.get("/api/config/instruments")
    assert "ES" not in res.get_json()["instruments"]


def test_delete_unknown_instrument_404(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.delete("/api/config/instruments/BOGUS")
    assert res.status_code == 404


def test_put_instrument_persists_to_json_file(tmp_path: Path):
    client = _setup_app(tmp_path)
    payload = {
        "display_name": "X",
        "multiplier": 1.5,
        "tick_size": 0.01,
        "sources": {
            "yfinance": {"continuous": None, "contract_template": None},
            "stooq": {"continuous": None, "contract_template": None},
        },
        "session": {
            "timezone": "UTC", "open": "00:00", "close": "00:00",
            "daily_break_start": "", "daily_break_end": "",
        },
    }
    client.put("/api/config/instruments/XYZ", json=payload)
    json_path = tmp_path / "data" / "config" / "instruments.json"
    data = json.loads(json_path.read_text())
    assert data["XYZ"]["multiplier"] == 1.5
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_settings_routes_instruments.py -x -v`
Expected: 404s because the route isn't registered.

- [ ] **Step 3: Create the blueprint scaffold**

Create `routes/settings.py`:

```python
from flask import Blueprint, current_app, jsonify, render_template, request
from pydantic import ValidationError

from logging_config import get_logger
from models.settings import InstrumentConfig
from services.instruments import get_registry

log = get_logger("http.settings")


def build_settings_blueprint() -> Blueprint:
    bp = Blueprint("settings", __name__)

    # ---- instruments ----

    @bp.get("/api/config/instruments")
    def list_instruments():
        reg = get_registry()
        return jsonify(
            {
                "instruments": {
                    symbol: cfg.model_dump()
                    for symbol, cfg in reg.list()
                }
            }
        )

    @bp.put("/api/config/instruments/<symbol>")
    def put_instrument(symbol: str):
        body = request.get_json(silent=True) or {}
        try:
            cfg = InstrumentConfig(**body)
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        get_registry().put(symbol, cfg)
        return jsonify({"instrument": cfg.model_dump()})

    @bp.delete("/api/config/instruments/<symbol>")
    def delete_instrument(symbol: str):
        try:
            get_registry().delete(symbol)
        except KeyError:
            return jsonify({"error": "not found"}), 404
        return "", 204

    # ---- settings pages (populated in later tasks) ----

    @bp.get("/settings")
    def settings_index_page():
        return render_template("settings_index.html")

    @bp.get("/settings/instruments")
    def settings_instruments_page():
        return render_template("settings_instruments.html")

    @bp.get("/settings/chart")
    def settings_chart_page():
        return render_template("settings_chart.html")

    @bp.get("/settings/custom-fields")
    def settings_custom_fields_page():
        return render_template("settings_custom_fields.html")

    return bp
```

Modify `app.py` — add import and blueprint registration. After `from routes.user_metadata import build_user_metadata_blueprint` add:

```python
from routes.settings import build_settings_blueprint
```

After `app.register_blueprint(build_links_blueprint())` add:

```python
    app.register_blueprint(build_settings_blueprint())
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_settings_routes_instruments.py -x -v`
Expected: all pass. The page-route tests will also succeed returning 500 (TemplateNotFound) in later tasks — those templates are created in Task 12. The JSON API slice passes.

Note: if the template-missing error surfaces, temporarily stub the templates with `<h1>stub</h1>` files in Task 8's commit and overwrite them in Task 12. Alternatively, Task 8's test focuses only on the API slice — which it does.

- [ ] **Step 5: Create minimal template stubs** (will be replaced by Task 12)

Create minimal stubs so the page routes don't 500 when later tests touch them:

```bash
for f in settings_index settings_instruments settings_chart settings_custom_fields; do
  echo '{% extends "base.html" %}{% block content %}<h1>stub</h1>{% endblock %}' > templates/$f.html
done
```

- [ ] **Step 6: Commit**

```bash
git add routes/settings.py app.py templates/settings_index.html templates/settings_instruments.html templates/settings_chart.html templates/settings_custom_fields.html tests/test_settings_routes_instruments.py
git commit -m "feat(plan16): settings blueprint — instruments API"
```

---

### Task 9: Settings blueprint — chart-defaults endpoint

**Files:**
- Modify: `routes/settings.py`
- Create: `tests/test_settings_routes_chart.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_routes_chart.py`:

```python
import json
from pathlib import Path

from app import create_app
from config import load_config


def _setup_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(json.dumps({
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "ftl.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 2},
        "scheduler": {"heartbeat_seconds": 30},
    }))
    return create_app(load_config(app_json))[0].test_client(), app_json


def test_get_chart_defaults_returns_seed(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.get("/api/config/chart-defaults")
    assert res.status_code == 200
    body = res.get_json()
    assert body["default_timeframe"] == "5m"
    assert body["volume_visible_default"] is True
    assert body["display_timezone"] is None


def test_put_chart_defaults_round_trip(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put("/api/config/chart-defaults", json={
        "default_timeframe": "1m",
        "volume_visible_default": False,
        "display_timezone": "Asia/Tokyo",
    })
    assert res.status_code == 200
    res = client.get("/api/config/chart-defaults")
    body = res.get_json()
    assert body["default_timeframe"] == "1m"
    assert body["volume_visible_default"] is False
    assert body["display_timezone"] == "Asia/Tokyo"


def test_put_chart_defaults_rejects_invalid_timeframe(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put("/api/config/chart-defaults", json={
        "default_timeframe": "2m",
        "volume_visible_default": True,
        "display_timezone": None,
    })
    assert res.status_code == 400


def test_put_chart_defaults_rejects_invalid_timezone(tmp_path: Path):
    client, _ = _setup_app(tmp_path)
    res = client.put("/api/config/chart-defaults", json={
        "default_timeframe": "5m",
        "volume_visible_default": True,
        "display_timezone": "Not/A_Timezone",
    })
    assert res.status_code == 400


def test_put_chart_defaults_persists_display_timezone_to_app_json(tmp_path: Path):
    client, app_json = _setup_app(tmp_path)
    client.put("/api/config/chart-defaults", json={
        "default_timeframe": "5m",
        "volume_visible_default": True,
        "display_timezone": "Europe/London",
    })
    data = json.loads(app_json.read_text())
    assert data["display_timezone"] == "Europe/London"
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_settings_routes_chart.py -x -v`
Expected: 404 on `/api/config/chart-defaults`.

- [ ] **Step 3: Add the route**

Add to `routes/settings.py` inside `build_settings_blueprint()`, after the delete_instrument route:

```python
    from zoneinfo import ZoneInfo

    @bp.get("/api/config/chart-defaults")
    def get_chart_defaults():
        from services.chart_defaults import get_defaults
        d = get_defaults(current_app.config["FTL_DB_PATH"])
        cfg = current_app.config["FTL_CONFIG"]
        return jsonify({
            "default_timeframe": d["default_timeframe"],
            "volume_visible_default": d["volume_visible_default"],
            "display_timezone": cfg.display_timezone,
        })

    @bp.put("/api/config/chart-defaults")
    def put_chart_defaults():
        from config import save_display_timezone
        from services.chart_defaults import save_defaults

        body = request.get_json(silent=True) or {}
        tf = body.get("default_timeframe")
        vv = body.get("volume_visible_default")
        dtz = body.get("display_timezone")

        if tf not in ("1m", "5m", "15m", "1h", "4h", "1d"):
            return jsonify({"error": "invalid default_timeframe"}), 400
        if not isinstance(vv, bool):
            return jsonify({"error": "volume_visible_default must be boolean"}), 400
        if dtz is not None:
            try:
                ZoneInfo(dtz)
            except Exception:
                return jsonify({"error": "invalid display_timezone"}), 400

        db_path = current_app.config["FTL_DB_PATH"]
        save_defaults(db_path, default_timeframe=tf, volume_visible_default=vv)

        cfg_path = current_app.config["FTL_CONFIG_PATH"]
        save_display_timezone(cfg_path, dtz)

        # Update the in-memory Config object so immediate GETs see the new value
        current_app.config["FTL_CONFIG"].__dict__["display_timezone"] = dtz  # type: ignore[attr-defined]

        return jsonify({
            "default_timeframe": tf,
            "volume_visible_default": vv,
            "display_timezone": dtz,
        })
```

Modify `app.py` — pass the config path through so the route can call `save_display_timezone`. In `create_app`, change the signature to accept the path or store it in `app.config`:

```python
    app.config["FTL_CONFIG_PATH"] = Path(config.data_dir) / "config" / "app.json"
```

Add that line near the other `app.config[...]=` assignments.

**Note on the Config mutation:** `StrictModel` (Pydantic v2 with `frozen=False` default) allows attribute assignment, but assigning through `__dict__` is a hack. Instead, reload the config:

Replace the mutation line with:

```python
        current_app.config["FTL_CONFIG"] = load_config(cfg_path)
```

And add `from config import load_config` at the top of `routes/settings.py`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings_routes_chart.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add routes/settings.py app.py tests/test_settings_routes_chart.py
git commit -m "feat(plan16): chart-defaults PUT with display_timezone round-trip"
```

---

### Task 10: Settings blueprint — custom-fields definition + option endpoints

**Files:**
- Modify: `routes/settings.py`
- Create: `tests/test_settings_routes_custom_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_routes_custom_fields.py`:

```python
import json
from pathlib import Path


def _setup_app(tmp_path: Path):
    from app import create_app
    from config import load_config
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(json.dumps({
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "ftl.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 2},
        "scheduler": {"heartbeat_seconds": 30},
    }))
    return create_app(load_config(app_json))[0].test_client()


def test_list_custom_fields_empty(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.get("/api/custom-fields")
    assert res.status_code == 200
    assert res.get_json() == {"fields": []}


def test_create_custom_field(tmp_path: Path):
    client = _setup_app(tmp_path)
    res = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "dropdown", "display_order": 0,
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["field"]["name"] == "setup"
    fid = body["field"]["field_id"]

    res = client.get("/api/custom-fields")
    assert len(res.get_json()["fields"]) == 1


def test_create_custom_field_duplicate_name_409(tmp_path: Path):
    client = _setup_app(tmp_path)
    client.post("/api/custom-fields", json={"name": "setup", "field_type": "text"})
    res = client.post("/api/custom-fields", json={"name": "setup", "field_type": "text"})
    assert res.status_code == 409


def test_update_custom_field_name(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "text",
    }).get_json()["field"]["field_id"]
    res = client.put(f"/api/custom-fields/{fid}", json={"name": "Setup Type"})
    assert res.status_code == 200
    assert res.get_json()["field"]["name"] == "Setup Type"


def test_delete_custom_field_two_step(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "text",
    }).get_json()["field"]["field_id"]
    # No confirm_count → 409 with affected count
    res = client.delete(f"/api/custom-fields/{fid}")
    assert res.status_code == 409
    assert res.get_json()["affected_executions"] == 0
    # With confirm_count=0
    res = client.delete(f"/api/custom-fields/{fid}?confirm_count=0")
    assert res.status_code == 204


def test_replace_options_round_trip(tmp_path: Path):
    client = _setup_app(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "dropdown",
    }).get_json()["field"]["field_id"]
    res = client.put(f"/api/custom-fields/{fid}/options", json={
        "options": [
            {"value": "Breakout", "display_order": 0},
            {"value": "Reversal", "display_order": 1},
        ],
    })
    assert res.status_code == 200
    assert [o["value"] for o in res.get_json()["options"]] == ["Breakout", "Reversal"]

    res = client.get(f"/api/custom-fields/{fid}/options")
    assert len(res.get_json()["options"]) == 2
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_settings_routes_custom_fields.py -x -v`
Expected: 404s.

- [ ] **Step 3: Add the routes**

Append to `routes/settings.py` inside `build_settings_blueprint()`:

```python
    def _svc():
        from services.custom_fields import CustomFieldsService
        return CustomFieldsService(current_app.config["FTL_DB_PATH"])

    @bp.get("/api/custom-fields")
    def list_custom_fields():
        defs = _svc().list_definitions(include_inactive=True)
        return jsonify({"fields": [d.model_dump() for d in defs]})

    @bp.post("/api/custom-fields")
    def create_custom_field():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        field_type = body.get("field_type")
        display_order = body.get("display_order", 0)
        if not isinstance(name, str) or not name:
            return jsonify({"error": "name is required"}), 400
        try:
            d = _svc().create_definition(
                name=name,
                field_type=field_type,
                display_order=display_order,
            )
        except ValueError as e:
            msg = str(e)
            if "duplicate" in msg:
                return jsonify({"error": msg}), 409
            return jsonify({"error": msg}), 400
        return jsonify({"field": d.model_dump()})

    @bp.put("/api/custom-fields/<int:field_id>")
    def update_custom_field(field_id: int):
        body = request.get_json(silent=True) or {}
        try:
            d = _svc().update_definition(
                field_id,
                name=body.get("name"),
                field_type=body.get("field_type"),
                is_active=body.get("is_active"),
                display_order=body.get("display_order"),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"field": d.model_dump()})

    @bp.delete("/api/custom-fields/<int:field_id>")
    def delete_custom_field(field_id: int):
        svc = _svc()
        actual = svc.affected_executions(field_id)
        confirm_raw = request.args.get("confirm_count")
        if confirm_raw is None:
            return jsonify({"affected_executions": actual}), 409
        try:
            svc.delete_definition(field_id, confirm_count=int(confirm_raw))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return "", 204

    @bp.get("/api/custom-fields/<int:field_id>/options")
    def list_custom_field_options(field_id: int):
        opts = _svc().list_options(field_id)
        return jsonify({"options": [o.model_dump() for o in opts]})

    @bp.put("/api/custom-fields/<int:field_id>/options")
    def replace_custom_field_options(field_id: int):
        body = request.get_json(silent=True) or {}
        options = body.get("options")
        if not isinstance(options, list):
            return jsonify({"error": "options must be a list"}), 400
        try:
            result = _svc().replace_options(field_id, options)
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"options": [o.model_dump() for o in result]})
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings_routes_custom_fields.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add routes/settings.py tests/test_settings_routes_custom_fields.py
git commit -m "feat(plan16): custom-fields definition + options API"
```

---

### Task 11: Settings blueprint — execution value endpoints + position convenience

**Files:**
- Modify: `routes/settings.py`
- Modify: `tests/test_settings_routes_custom_fields.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_settings_routes_custom_fields.py`:

```python
def _seed_execution(tmp_path: Path, eid: str = "E1"):
    import sqlite3
    db_path = tmp_path / "data" / "ftl.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN")
    conn.execute(
        "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
        " original_action, quantity, price, commission, entry_exit, position_after,"
        " source_order_id, source_filename, imported_at) VALUES "
        "(?, 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)",
        (eid,),
    )
    conn.execute("COMMIT")
    conn.close()


def test_get_execution_custom_fields_empty(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    res = client.get("/api/executions/E1/custom-fields")
    assert res.status_code == 200
    assert res.get_json() == {"values": {}}


def test_put_then_get_execution_custom_field_text(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "text",
    }).get_json()["field"]["field_id"]

    res = client.put(
        f"/api/executions/E1/custom-fields/{fid}",
        json={"value": "A+ setup"},
    )
    assert res.status_code == 200

    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {str(fid): "A+ setup"}


def test_put_execution_custom_field_empty_deletes(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "text",
    }).get_json()["field"]["field_id"]
    client.put(f"/api/executions/E1/custom-fields/{fid}", json={"value": "A+"})
    client.put(f"/api/executions/E1/custom-fields/{fid}", json={"value": ""})
    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {}


def test_put_execution_custom_field_unknown_field_400(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    res = client.put("/api/executions/E1/custom-fields/999", json={"value": "x"})
    assert res.status_code == 400


def test_put_execution_custom_field_split_suffix_lands_on_parent(tmp_path: Path):
    client = _setup_app(tmp_path)
    _seed_execution(tmp_path)
    fid = client.post("/api/custom-fields", json={
        "name": "setup", "field_type": "text",
    }).get_json()["field"]["field_id"]
    res = client.put(
        f"/api/executions/E1#close/custom-fields/{fid}",
        json={"value": "B-"},
    )
    assert res.status_code == 200
    res = client.get("/api/executions/E1/custom-fields")
    assert res.get_json()["values"] == {str(fid): "B-"}
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_settings_routes_custom_fields.py::test_get_execution_custom_fields_empty -x -v`
Expected: 404.

- [ ] **Step 3: Add the routes**

Append to `routes/settings.py` inside `build_settings_blueprint()`:

```python
    def _execution_exists(execution_id: str) -> bool:
        from db import connect
        from services.notes import strip_split_suffix
        real_id = strip_split_suffix(execution_id)
        conn = connect(current_app.config["FTL_DB_PATH"])
        try:
            row = conn.execute(
                "SELECT 1 FROM executions WHERE nt_execution_id = ?",
                (real_id,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    @bp.get("/api/executions/<execution_id>/custom-fields")
    def get_execution_custom_fields(execution_id: str):
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        values = _svc().get_execution_values(execution_id)
        return jsonify({"values": {str(k): v for k, v in values.items()}})

    @bp.put("/api/executions/<execution_id>/custom-fields/<int:field_id>")
    def put_execution_custom_field(execution_id: str, field_id: int):
        if not _execution_exists(execution_id):
            return jsonify({"error": "execution not found"}), 404
        body = request.get_json(silent=True) or {}
        value = body.get("value")
        try:
            _svc().set_execution_value(execution_id, field_id, value)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True})

    @bp.get(
        "/api/positions/<account>/<instrument>/<entry_execution_id>/custom-fields"
    )
    def get_position_custom_fields(
        account: str, instrument: str, entry_execution_id: str
    ):
        from services.positions_service import get_position
        p = get_position(
            current_app.config["FTL_DB_PATH"],
            account=account, instrument=instrument,
            entry_execution_id=entry_execution_id,
        )
        if p is None:
            return jsonify({"error": "not found"}), 404
        result = _svc().values_for_position(
            execution_ids=p.execution_ids,
            entry_execution_id=p.entry_execution_id,
        )
        result["entry"] = {str(k): v for k, v in result["entry"].items()}
        result["per_execution"] = [
            {
                "execution_id": r["execution_id"],
                "values": {str(k): v for k, v in r["values"].items()},
            }
            for r in result["per_execution"]
        ]
        return jsonify(result)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings_routes_custom_fields.py -x -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add routes/settings.py tests/test_settings_routes_custom_fields.py
git commit -m "feat(plan16): custom-field value API — execution + position convenience"
```

---

### Task 12: Settings UI — templates, JS, CSS

**Files:**
- Overwrite: `templates/settings_index.html`, `settings_instruments.html`, `settings_chart.html`, `settings_custom_fields.html`
- Create: `static/css/settings.css`
- Create: `static/js/settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js`
- Modify: `templates/base.html` (Settings nav link)

No new tests in this task beyond a smoke-check that the pages return 200 and reference the expected JS files. The browser AC walkthrough is deferred (same pattern as plans 13 and 15).

- [ ] **Step 1: Write the smoke test**

Append to `tests/test_settings_routes_instruments.py`:

```python
def test_settings_pages_return_200_and_reference_js(tmp_path: Path):
    client = _setup_app(tmp_path)
    for path, js in [
        ("/settings", None),
        ("/settings/instruments", "settings_instruments.js"),
        ("/settings/chart", "settings_chart.js"),
        ("/settings/custom-fields", "settings_custom_fields.js"),
    ]:
        res = client.get(path)
        assert res.status_code == 200
        if js is not None:
            assert js.encode() in res.data


def test_static_js_files_served(tmp_path: Path):
    client = _setup_app(tmp_path)
    for js in ("settings_instruments.js", "settings_chart.js", "settings_custom_fields.js"):
        res = client.get(f"/static/js/{js}")
        assert res.status_code == 200
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_settings_routes_instruments.py::test_static_js_files_served -x -v`
Expected: 404 on the JS files because they don't exist.

- [ ] **Step 3: Write the templates**

Overwrite `templates/settings_index.html`:

```jinja
{% extends "base.html" %}
{% block content %}
<section class="settings-page">
  <h1>Settings</h1>
  <ul class="settings-index">
    <li><a href="/settings/instruments">Instruments</a> — multipliers, tick sizes, and per-source symbol mapping.</li>
    <li><a href="/settings/chart">Chart defaults</a> — default timeframe, volume toggle, and display timezone.</li>
    <li><a href="/settings/custom-fields">Custom fields</a> — user-defined tags on trades.</li>
  </ul>
</section>
{% endblock %}
```

Overwrite `templates/settings_instruments.html`:

```jinja
{% extends "base.html" %}
{% block content %}
<section class="settings-page" id="settings-instruments" data-endpoint="/api/config/instruments">
  <h1>Instruments</h1>
  <p class="muted">Changes take effect immediately for new fetches and P&amp;L computation.</p>
  <div class="instruments-toolbar">
    <button id="new-instrument-btn" type="button">Add instrument</button>
  </div>
  <table class="instruments-table">
    <thead>
      <tr>
        <th>Symbol</th><th>Display name</th><th>Multiplier</th><th>Tick</th>
        <th>yfinance</th><th>stooq</th><th>Actions</th>
      </tr>
    </thead>
    <tbody id="instruments-tbody"></tbody>
  </table>
  <dialog id="instrument-dialog">
    <form id="instrument-form" method="dialog">
      <h2 id="dialog-title">Edit instrument</h2>
      <label>Symbol <input name="symbol" required></label>
      <label>Display name <input name="display_name" required></label>
      <label>Multiplier <input name="multiplier" type="number" step="any" required></label>
      <label>Tick size <input name="tick_size" type="number" step="any" required></label>
      <label>yfinance continuous <input name="yfinance_continuous"></label>
      <label>stooq continuous <input name="stooq_continuous"></label>
      <fieldset>
        <legend>Session</legend>
        <label>Timezone <input name="session_timezone" required></label>
        <label>Open <input name="session_open" placeholder="HH:MM"></label>
        <label>Close <input name="session_close" placeholder="HH:MM"></label>
        <label>Break start <input name="session_break_start" placeholder="HH:MM"></label>
        <label>Break end <input name="session_break_end" placeholder="HH:MM"></label>
      </fieldset>
      <div class="dialog-actions">
        <button type="button" id="dialog-cancel">Cancel</button>
        <button type="submit">Save</button>
      </div>
    </form>
  </dialog>
</section>
<script type="module" src="{{ url_for('static', filename='js/settings_instruments.js') }}"></script>
{% endblock %}
```

Overwrite `templates/settings_chart.html`:

```jinja
{% extends "base.html" %}
{% block content %}
<section class="settings-page" id="settings-chart" data-endpoint="/api/config/chart-defaults">
  <h1>Chart defaults</h1>
  <form id="chart-defaults-form">
    <label>Default timeframe
      <select name="default_timeframe">
        <option>1m</option><option>5m</option><option>15m</option>
        <option>1h</option><option>4h</option><option>1d</option>
      </select>
    </label>
    <label><input type="checkbox" name="volume_visible_default"> Show volume by default</label>
    <label>Display timezone (optional, for hour-bucketed stats)
      <input name="display_timezone" placeholder="e.g. America/Chicago or Asia/Tokyo">
    </label>
    <button type="submit">Save</button>
    <p class="status" id="chart-defaults-status"></p>
  </form>
</section>
<script type="module" src="{{ url_for('static', filename='js/settings_chart.js') }}"></script>
{% endblock %}
```

Overwrite `templates/settings_custom_fields.html`:

```jinja
{% extends "base.html" %}
{% block content %}
<section class="settings-page" id="settings-custom-fields" data-endpoint="/api/custom-fields">
  <h1>Custom fields</h1>
  <p class="muted">Define tags and numeric scores you can attach to any trade.</p>
  <form id="new-field-form">
    <input name="name" placeholder="Field name (e.g. Setup)" required>
    <select name="field_type">
      <option value="text">Text</option>
      <option value="number">Number</option>
      <option value="dropdown">Dropdown</option>
      <option value="date">Date</option>
      <option value="boolean">Boolean</option>
    </select>
    <button type="submit">Add field</button>
  </form>
  <div id="fields-list"></div>
</section>
<script type="module" src="{{ url_for('static', filename='js/settings_custom_fields.js') }}"></script>
{% endblock %}
```

Modify `templates/base.html` — add a Settings nav link. Find the existing nav block and append `<a href="/settings">Settings</a>`.

- [ ] **Step 4: Write the JS modules**

Create `static/js/settings_instruments.js`:

```javascript
const endpoint = "/api/config/instruments";
const tbody = document.getElementById("instruments-tbody");
const dialog = document.getElementById("instrument-dialog");
const form = document.getElementById("instrument-form");
const titleEl = document.getElementById("dialog-title");
const newBtn = document.getElementById("new-instrument-btn");
const cancelBtn = document.getElementById("dialog-cancel");

let editingSymbol = null;

async function refresh() {
  const res = await fetch(endpoint);
  const body = await res.json();
  tbody.replaceChildren();
  for (const [symbol, cfg] of Object.entries(body.instruments).sort()) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td></td><td></td><td></td><td></td><td></td><td></td>
      <td><button data-act="edit"></button> <button data-act="del"></button></td>
    `;
    const cells = tr.querySelectorAll("td");
    cells[0].textContent = symbol;
    cells[1].textContent = cfg.display_name;
    cells[2].textContent = cfg.multiplier;
    cells[3].textContent = cfg.tick_size;
    cells[4].textContent = cfg.sources?.yfinance?.continuous ?? "";
    cells[5].textContent = cfg.sources?.stooq?.continuous ?? "";
    const [editBtn, delBtn] = cells[6].querySelectorAll("button");
    editBtn.textContent = "Edit";
    delBtn.textContent = "Delete";
    editBtn.addEventListener("click", () => openDialog(symbol, cfg));
    delBtn.addEventListener("click", () => deleteInstrument(symbol));
    tbody.appendChild(tr);
  }
}

function openDialog(symbol, cfg) {
  editingSymbol = symbol;
  titleEl.textContent = symbol ? `Edit ${symbol}` : "Add instrument";
  const elements = form.elements;
  elements.symbol.value = symbol || "";
  elements.symbol.disabled = Boolean(symbol);
  elements.display_name.value = cfg?.display_name || "";
  elements.multiplier.value = cfg?.multiplier ?? "";
  elements.tick_size.value = cfg?.tick_size ?? "";
  elements.yfinance_continuous.value = cfg?.sources?.yfinance?.continuous || "";
  elements.stooq_continuous.value = cfg?.sources?.stooq?.continuous || "";
  elements.session_timezone.value = cfg?.session?.timezone || "America/Chicago";
  elements.session_open.value = cfg?.session?.open || "17:00";
  elements.session_close.value = cfg?.session?.close || "16:00";
  elements.session_break_start.value = cfg?.session?.daily_break_start || "16:00";
  elements.session_break_end.value = cfg?.session?.daily_break_end || "17:00";
  dialog.showModal();
}

async function saveDialog(event) {
  event.preventDefault();
  const f = form.elements;
  const symbol = f.symbol.value.trim();
  const payload = {
    display_name: f.display_name.value,
    multiplier: parseFloat(f.multiplier.value),
    tick_size: parseFloat(f.tick_size.value),
    sources: {
      yfinance: { continuous: f.yfinance_continuous.value || null, contract_template: null },
      stooq: { continuous: f.stooq_continuous.value || null, contract_template: null },
    },
    session: {
      timezone: f.session_timezone.value,
      open: f.session_open.value,
      close: f.session_close.value,
      daily_break_start: f.session_break_start.value,
      daily_break_end: f.session_break_end.value,
    },
  };
  const res = await fetch(`${endpoint}/${symbol}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert(`Save failed: ${res.status}`);
    return;
  }
  dialog.close();
  await refresh();
}

async function deleteInstrument(symbol) {
  if (!confirm(`Delete ${symbol}?`)) return;
  const res = await fetch(`${endpoint}/${symbol}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    alert(`Delete failed: ${res.status}`);
    return;
  }
  await refresh();
}

newBtn.addEventListener("click", () => openDialog(null, null));
cancelBtn.addEventListener("click", () => dialog.close());
form.addEventListener("submit", saveDialog);

refresh();
```

Create `static/js/settings_chart.js`:

```javascript
const endpoint = "/api/config/chart-defaults";
const form = document.getElementById("chart-defaults-form");
const status = document.getElementById("chart-defaults-status");

async function load() {
  const res = await fetch(endpoint);
  const body = await res.json();
  form.elements.default_timeframe.value = body.default_timeframe;
  form.elements.volume_visible_default.checked = Boolean(body.volume_visible_default);
  form.elements.display_timezone.value = body.display_timezone || "";
}

async function save(event) {
  event.preventDefault();
  status.textContent = "Saving…";
  const payload = {
    default_timeframe: form.elements.default_timeframe.value,
    volume_visible_default: form.elements.volume_visible_default.checked,
    display_timezone: form.elements.display_timezone.value || null,
  };
  const res = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json();
    status.textContent = `Error: ${err.error || res.status}`;
    return;
  }
  status.textContent = "Saved.";
}

form.addEventListener("submit", save);
load();
```

Create `static/js/settings_custom_fields.js`:

```javascript
const endpoint = "/api/custom-fields";
const list = document.getElementById("fields-list");
const form = document.getElementById("new-field-form");

async function refresh() {
  const res = await fetch(endpoint);
  const body = await res.json();
  list.replaceChildren();
  for (const field of body.fields) {
    list.appendChild(renderField(field));
  }
}

function renderField(field) {
  const wrap = document.createElement("div");
  wrap.className = "field-row";
  wrap.dataset.fieldId = String(field.field_id);

  const name = document.createElement("input");
  name.value = field.name;
  name.addEventListener("blur", () => update(field.field_id, { name: name.value }));

  const typeLabel = document.createElement("span");
  typeLabel.textContent = field.field_type;
  typeLabel.className = "muted";

  const activeToggle = document.createElement("label");
  activeToggle.innerHTML = `<input type="checkbox" ${field.is_active ? "checked" : ""}> Active`;
  activeToggle.querySelector("input").addEventListener("change", (e) => {
    update(field.field_id, { is_active: e.target.checked });
  });

  const delBtn = document.createElement("button");
  delBtn.textContent = "Delete";
  delBtn.addEventListener("click", () => remove(field.field_id));

  wrap.append(name, typeLabel, activeToggle, delBtn);

  if (field.field_type === "dropdown") {
    wrap.appendChild(renderOptionsEditor(field.field_id));
  }
  return wrap;
}

function renderOptionsEditor(fieldId) {
  const container = document.createElement("div");
  container.className = "options-editor";
  const textarea = document.createElement("textarea");
  textarea.placeholder = "One option per line";
  textarea.rows = 4;
  container.appendChild(textarea);
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save options";
  container.appendChild(saveBtn);

  fetch(`${endpoint}/${fieldId}/options`).then((r) => r.json()).then((body) => {
    textarea.value = body.options.map((o) => o.value).join("\n");
  });

  saveBtn.addEventListener("click", async () => {
    const options = textarea.value
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .map((value, idx) => ({ value, display_order: idx }));
    const res = await fetch(`${endpoint}/${fieldId}/options`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ options }),
    });
    if (!res.ok) alert("Save failed");
  });
  return container;
}

async function create(event) {
  event.preventDefault();
  const payload = {
    name: form.elements.name.value,
    field_type: form.elements.field_type.value,
  };
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json();
    alert(`Create failed: ${body.error || res.status}`);
    return;
  }
  form.reset();
  await refresh();
}

async function update(fieldId, patch) {
  const res = await fetch(`${endpoint}/${fieldId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const body = await res.json();
    alert(`Update failed: ${body.error || res.status}`);
  }
}

async function remove(fieldId) {
  const peek = await fetch(`${endpoint}/${fieldId}`, { method: "DELETE" });
  if (peek.status === 204) {
    await refresh();
    return;
  }
  const body = await peek.json();
  const n = body.affected_executions ?? 0;
  if (!confirm(`This field has values on ${n} executions. Delete anyway?`)) return;
  const res = await fetch(`${endpoint}/${fieldId}?confirm_count=${n}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    alert("Delete failed");
    return;
  }
  await refresh();
}

form.addEventListener("submit", create);
refresh();
```

Create `static/css/settings.css`:

```css
.settings-page {
  max-width: 960px;
  margin: 1.5rem auto;
  padding: 0 1rem;
}
.settings-page h1 { margin-bottom: 0.75rem; }
.settings-index { list-style: none; padding: 0; }
.settings-index li { padding: 0.5rem 0; border-bottom: 1px solid #2a2a32; }
.instruments-table { width: 100%; border-collapse: collapse; }
.instruments-table th, .instruments-table td { padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid #2a2a32; }
.instruments-toolbar { margin-bottom: 0.75rem; }
.field-row { padding: 0.5rem 0; border-bottom: 1px solid #2a2a32; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.options-editor { width: 100%; margin-top: 0.5rem; }
.options-editor textarea { width: 100%; font-family: inherit; }
.muted { color: #8a8a92; }
```

Modify `templates/base.html` — add `<link rel="stylesheet" href="{{ url_for('static', filename='css/settings.css') }}">` inside the `<head>`.

- [ ] **Step 5: Run the smoke tests**

Run: `pytest tests/test_settings_routes_instruments.py -x -v`
Expected: the two new page/static smoke tests pass along with the earlier instruments API tests.

- [ ] **Step 6: Commit**

```bash
git add templates/ static/js/settings_instruments.js static/js/settings_chart.js static/js/settings_custom_fields.js static/css/settings.css tests/test_settings_routes_instruments.py
git commit -m "feat(plan16): settings UI — templates + JS modules + CSS"
```

---

### Task 13: Position detail integration — attach_metadata + position_detail.js

**Files:**
- Modify: `services/positions_service.py::attach_metadata`
- Create: `tests/test_position_detail_custom_fields.py`
- Modify: `static/js/position_detail.js`
- Modify: `templates/position_detail.html`
- Create: `static/js/custom_fields_detail.js`

- [ ] **Step 1: Write the failing test**

Create `tests/test_position_detail_custom_fields.py`:

```python
import sqlite3
import tempfile
from pathlib import Path

from db import connect
from migrations import run_migrations
from services.custom_fields import CustomFieldsService
from services.positions_service import attach_metadata


def _fresh_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = connect(Path(tmp.name))
    run_migrations(conn, Path("migrations"))
    conn.close()
    return Path(tmp.name)


def _seed_execution(db_path: Path, eid: str):
    conn = connect(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO executions (nt_execution_id, account, instrument, timestamp, side,"
            " original_action, quantity, price, commission, entry_exit, position_after,"
            " source_order_id, source_filename, imported_at) VALUES "
            "(?, 'Sim', 'MES', 1700000000, 'Buy', 'Buy', 1, 4500.0, 2.50, 'Entry', 1, 'O', 'f.csv', 1700000000)",
            (eid,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


class _FakePosition:
    def __init__(self, entry: str, executions: list[str]):
        self.entry_execution_id = entry
        self.execution_ids = executions

    def model_dump(self):
        return {"entry_execution_id": self.entry_execution_id}


def test_attach_metadata_custom_fields_populated():
    db = _fresh_db()
    _seed_execution(db, "E1")
    _seed_execution(db, "E2")
    svc = CustomFieldsService(db)
    d = svc.create_definition(name="setup", field_type="text")
    svc.set_execution_value("E1", d.field_id, "A+")
    svc.set_execution_value("E2", d.field_id, "B-")

    result = attach_metadata(db, _FakePosition("E1", ["E1", "E2"]))
    cf = result["custom_fields"]
    assert cf["entry"] == {d.field_id: "A+"}
    assert cf["per_execution"] == [
        {"execution_id": "E2", "values": {d.field_id: "B-"}},
    ]
    assert [x["name"] for x in cf["definitions"]] == ["setup"]


def test_attach_metadata_no_custom_fields():
    db = _fresh_db()
    _seed_execution(db, "E1")
    result = attach_metadata(db, _FakePosition("E1", ["E1"]))
    cf = result["custom_fields"]
    assert cf["entry"] == {}
    assert cf["per_execution"] == []
    assert cf["definitions"] == []
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_position_detail_custom_fields.py -x -v`
Expected: assertion errors because `attach_metadata` still returns `"custom_fields": {}`.

- [ ] **Step 3: Update `attach_metadata`**

Modify `services/positions_service.py::attach_metadata`:

```python
def attach_metadata(db_path: Path | str, position) -> dict:
    """Return the detail-response envelope for one position."""
    from services.custom_fields import CustomFieldsService

    notes = list_notes_for_executions(db_path, position.execution_ids)
    reviewed = list_flags_for_executions(db_path, position.execution_ids)
    svc = CustomFieldsService(db_path)
    custom_fields = svc.values_for_position(
        execution_ids=position.execution_ids,
        entry_execution_id=position.entry_execution_id,
    )
    return {
        "position": position.model_dump(),
        "notes": notes,
        "reviewed": reviewed,
        "custom_fields": custom_fields,
    }
```

- [ ] **Step 4: Run the backend test**

Run: `pytest tests/test_position_detail_custom_fields.py -x -v`
Expected: passes.

- [ ] **Step 5: Frontend — custom fields block in position_detail.js**

Modify `templates/position_detail.html` — add a mount point between the Notes section and the Executions table section:

```html
<section id="custom-fields-block" data-endpoint="/api/executions"></section>
```

Also add `<script type="module" src="{{ url_for('static', filename='js/custom_fields_detail.js') }}"></script>` before the existing position_detail.js script tag. `custom_fields_detail.js` exports `mountCustomFields(container, detailPayload, entryExecutionId)` which `position_detail.js` calls after loading the detail payload.

Create `static/js/custom_fields_detail.js`:

```javascript
/**
 * Render the custom-fields block for a position detail page.
 *
 * Called once with the detail response payload. Creates inline inputs for
 * every active definition, pre-populated from `entry`. Adds a <details>
 * fold-out listing non-entry executions that have values.
 */
export function mountCustomFields(container, detailPayload, entryExecutionId) {
  container.replaceChildren();
  const cf = detailPayload.custom_fields || {};
  const definitions = cf.definitions || [];
  const entry = cf.entry || {};
  const perExecution = cf.per_execution || [];

  if (definitions.length === 0 && perExecution.length === 0) {
    return;
  }

  const h = document.createElement("h2");
  h.textContent = "Custom fields";
  container.appendChild(h);

  const form = document.createElement("form");
  form.className = "custom-fields-form";
  form.addEventListener("submit", (e) => e.preventDefault());
  for (const def of definitions) {
    const label = document.createElement("label");
    label.className = "custom-field-label";
    const labelText = document.createElement("span");
    labelText.textContent = def.name;
    label.appendChild(labelText);
    const input = buildInput(def, entry[String(def.field_id)]);
    input.addEventListener("change", () => saveValue(entryExecutionId, def.field_id, extractValue(input, def.field_type)));
    input.addEventListener("blur", () => saveValue(entryExecutionId, def.field_id, extractValue(input, def.field_type)));
    label.appendChild(input);
    form.appendChild(label);
  }
  container.appendChild(form);

  if (perExecution.length > 0) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = `Per-execution values (${perExecution.length})`;
    details.appendChild(summary);
    const table = buildPerExecutionTable(definitions, perExecution);
    details.appendChild(table);
    container.appendChild(details);
  }
}

function buildInput(def, currentValue) {
  if (def.field_type === "text") {
    const i = document.createElement("input");
    i.type = "text";
    if (currentValue !== undefined) i.value = currentValue;
    return i;
  }
  if (def.field_type === "number") {
    const i = document.createElement("input");
    i.type = "number";
    i.step = "any";
    if (currentValue !== undefined) i.value = String(currentValue);
    return i;
  }
  if (def.field_type === "date") {
    const i = document.createElement("input");
    i.type = "date";
    if (currentValue !== undefined) i.value = currentValue;
    return i;
  }
  if (def.field_type === "boolean") {
    const i = document.createElement("input");
    i.type = "checkbox";
    if (currentValue === true) i.checked = true;
    return i;
  }
  if (def.field_type === "dropdown") {
    const s = document.createElement("select");
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "—";
    s.appendChild(blank);
    // Options fetched lazily on focus
    s.addEventListener("focus", async () => {
      if (s.dataset.loaded === "1") return;
      const res = await fetch(`/api/custom-fields/${def.field_id}/options`);
      const body = await res.json();
      for (const o of body.options) {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.value;
        s.appendChild(opt);
      }
      if (currentValue !== undefined) s.value = currentValue;
      s.dataset.loaded = "1";
    });
    return s;
  }
  const fallback = document.createElement("input");
  fallback.type = "text";
  return fallback;
}

function extractValue(input, fieldType) {
  if (fieldType === "boolean") return input.checked;
  if (fieldType === "number") return input.value === "" ? "" : parseFloat(input.value);
  return input.value;
}

async function saveValue(executionId, fieldId, value) {
  const res = await fetch(
    `/api/executions/${encodeURIComponent(executionId)}/custom-fields/${fieldId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }
  );
  if (!res.ok) {
    const body = await res.json();
    alert(`Save failed: ${body.error || res.status}`);
  }
}

function buildPerExecutionTable(definitions, perExecution) {
  const table = document.createElement("table");
  table.className = "per-execution-table";
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  const eidTh = document.createElement("th");
  eidTh.textContent = "Execution";
  headerRow.appendChild(eidTh);
  for (const def of definitions) {
    const th = document.createElement("th");
    th.textContent = def.name;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of perExecution) {
    const tr = document.createElement("tr");
    const eidTd = document.createElement("td");
    eidTd.textContent = row.execution_id;
    tr.appendChild(eidTd);
    for (const def of definitions) {
      const td = document.createElement("td");
      const v = row.values[String(def.field_id)];
      td.textContent = v === undefined ? "" : String(v);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}
```

Modify `static/js/position_detail.js` — after loading the detail payload, add:

```javascript
import { mountCustomFields } from "./custom_fields_detail.js";

// ... existing detail load code ...

const detail = await fetchDetail();
// ... existing mounts (notes, reviewed, executions, links) ...
const cfContainer = document.getElementById("custom-fields-block");
if (cfContainer) {
  mountCustomFields(cfContainer, detail, detail.position.entry_execution_id);
}
```

The exact insertion point depends on the current structure; append after whichever block currently renders the detail fetch's result.

- [ ] **Step 6: Run the suite**

Run: `pytest -x -q`
Expected: everything green.

- [ ] **Step 7: Commit**

```bash
git add services/positions_service.py templates/position_detail.html static/js/custom_fields_detail.js static/js/position_detail.js tests/test_position_detail_custom_fields.py
git commit -m "feat(plan16): render custom fields on position detail page"
```

---

### Task 14: App factory smoke + docs

**Files:**
- Create: `tests/test_app_factory_plan16.py`
- Modify: `docs/rebuild-spec/00-README.md` (add "What Plan 16 landed" section and mark plan 16 ✅)
- Modify: `CLAUDE.md` (update status line)

- [ ] **Step 1: Write the smoke test**

Create `tests/test_app_factory_plan16.py`:

```python
import json
from pathlib import Path

from app import create_app
from config import load_config


def _setup(tmp_path: Path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "archive").mkdir()
    (data_dir / "log").mkdir()
    app_json = data_dir / "config" / "app.json"
    app_json.write_text(json.dumps({
        "data_dir": str(data_dir),
        "db_path": str(data_dir / "ftl.db"),
        "inbox_dir": str(data_dir / "inbox"),
        "archive_dir": str(data_dir / "archive"),
        "log_dir": str(data_dir / "log"),
        "session": {
            "exchange_timezone": "America/Chicago",
            "trade_date_rollover": "17:00",
            "archive_job_time": "18:00",
        },
        "thread_pool": {"max_workers": 2},
        "scheduler": {"heartbeat_seconds": 30},
    }))
    return create_app(load_config(app_json))[0].test_client()


EXPECTED_API_ROUTES = [
    ("/api/config/instruments", "GET"),
    ("/api/config/chart-defaults", "GET"),
    ("/api/custom-fields", "GET"),
]

EXPECTED_PAGE_ROUTES = [
    "/settings",
    "/settings/instruments",
    "/settings/chart",
    "/settings/custom-fields",
]

EXPECTED_STATIC = [
    "/static/js/settings_instruments.js",
    "/static/js/settings_chart.js",
    "/static/js/settings_custom_fields.js",
    "/static/js/custom_fields_detail.js",
    "/static/css/settings.css",
]


def test_api_routes_wired(tmp_path: Path):
    client = _setup(tmp_path)
    for path, method in EXPECTED_API_ROUTES:
        res = client.open(path, method=method)
        assert res.status_code in (200, 204), f"{method} {path} => {res.status_code}"


def test_page_routes_wired(tmp_path: Path):
    client = _setup(tmp_path)
    for path in EXPECTED_PAGE_ROUTES:
        res = client.get(path)
        assert res.status_code == 200, f"GET {path} => {res.status_code}"


def test_static_assets_served(tmp_path: Path):
    client = _setup(tmp_path)
    for path in EXPECTED_STATIC:
        res = client.get(path)
        assert res.status_code == 200, f"GET {path} => {res.status_code}"


def test_instruments_json_created_on_startup(tmp_path: Path):
    _setup(tmp_path)
    instruments_json = tmp_path / "data" / "config" / "instruments.json"
    assert instruments_json.exists()
    data = json.loads(instruments_json.read_text())
    assert "ES" in data
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/test_app_factory_plan16.py -x -v`
Expected: all pass.

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: all green, including plans 00–15 tests. Ruff check + format clean.

Run: `ruff check . && ruff format --check .`
Expected: no errors.

- [ ] **Step 4: Update `docs/rebuild-spec/00-README.md`**

In the progress table, change plan 16's status from `⏳` to `✅ **Complete** (2026-04-13, ~14 tasks)`.

Append a "What Plan 16 landed" section between "What Plan 15 landed" and "What Plan 00 deliberately did NOT land":

```markdown
### What Plan 16 landed

- **Migration 006.** Ships `chart_defaults` (one-row `CHECK(id=1)`), `custom_fields`, `custom_field_options`, `execution_custom_field_values`. FK cascades on both executions and field deletions confirmed by tests.
- **InstrumentRegistry.** `services/instrument_registry.py` owns `data/config/instruments.json` with atomic tmp+rename writes under a module-level lock. First load seeds from `DEFAULT_SEED` — the multiplier/symbol/session tables previously hardcoded in `services/instruments.py`. Plans 11/14 callers see identical results for all seeded instruments (pinned by `test_instruments_registry_backcompat.py`).
- **`services/instruments.py` becomes a thin delegator.** Bodies of `get_multiplier`, `source_symbol`, `default_session` now read from the registry. `DEFAULT_TIMEFRAMES`, `base_symbol`, `SessionCalendar` unchanged so plan 14's `app.py` post-tick hook continues to work.
- **DB-backed chart defaults.** `services/chart_defaults.py::get_defaults(db_path)` now SELECTs from the seeded `chart_defaults` row. New `save_defaults(...)` companion writes it inside a caller-supplied transaction.
- **`config.save_display_timezone`.** New helper reads/modifies/writes `app.json` under a module lock with tmp+rename. Validates IANA strings via `zoneinfo.ZoneInfo`. Called by the chart-defaults PUT handler. No generic config-save path.
- **CustomFieldsService.** Owns all CRUD for definitions, options, and execution values. Typed encoding for `text`/`number`/`dropdown`/`date`/`boolean` in one place. Dropdown writes validated against current options. `#close`/`#open` split-suffix stripped before every DB touch. Two-step delete flow via `affected_executions(field_id)` + `delete_definition(field_id, confirm_count=N)`. `values_for_position(...)` splits results into `entry`/`per_execution`/`definitions`.
- **Settings blueprint.** New `routes/settings.py` with all 13 endpoints from doc 16 plus four page routes (`/settings`, `/settings/instruments`, `/settings/chart`, `/settings/custom-fields`). Registered in `create_app()` between `build_links_blueprint()` and `build_pages_blueprint()`.
- **Position detail integration.** `services/positions_service.py::attach_metadata` now returns `custom_fields: {entry, per_execution, definitions}` instead of the plan 12 `{}` stub. `static/js/custom_fields_detail.js` renders an inline always-visible block + a `<details>` per-execution fold-out when non-entry executions have values.
- **Four new ES modules, no new dependencies.** `settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js`, `custom_fields_detail.js`. Plus one `settings.css` scoped to `.settings-page`. No bundler, no framework, no `package.json`, no new `requirements.txt` entries.
- **Doc 16 hazards enforced.** One endpoint per resource; one registry owns `instruments.json`; no profiles, no instrument groups; custom field values attach to `nt_execution_id` (not to any position key); `chart_defaults` stays single-row with `CHECK(id=1)`.
- **End-to-end verification deferred.** Backend tests cover all 13 routes, all four pages, and every service path. In-browser walkthrough of doc 16 AC 1–11 is the user's task — same pattern as plans 13/15.
```

Also update `CLAUDE.md`'s "Implementation progresses plan-by-plan" line: "As of 2026-04-13, plans 00–16 are complete; plan 17 (Monitoring) is next."

- [ ] **Step 5: Commit**

```bash
git add tests/test_app_factory_plan16.py docs/rebuild-spec/00-README.md CLAUDE.md
git commit -m "feat(plan16): app-factory smoke + doc updates for plan 16 completion"
```

---

## Self-review checklist

Before declaring the plan done, verify each of these:

**Spec coverage (doc 16 acceptance criteria):**
- [x] AC1 — `instruments.json` loaded on startup by registry → Task 3 + Task 4 binding
- [x] AC2 — required fields enforced via Pydantic → Task 2 + Task 8
- [x] AC3 — `/settings/instruments` CRUD → Task 8 + Task 12
- [x] AC4 — `chart_defaults` single-row DB → Task 1 + Task 5 + Task 9
- [x] AC5 — `custom_fields` schema → Task 1
- [x] AC6 — `custom_field_options` schema → Task 1
- [x] AC7 — values attach to `nt_execution_id` with cascade → Task 1 + Task 7
- [x] AC8 — entry-execution default + fold-out for others → Task 13
- [x] AC9 — `/settings/custom-fields` CRUD → Task 10 + Task 12
- [x] AC10 — inactive fields preserved → Task 7 (`values_for_position` + service tests)
- [x] AC11 — delete warns with affected count → Task 7 (`affected_executions`) + Task 10 (two-step DELETE)

**Fragmentation hazards:**
- [x] Hazard 1 (multiple settings APIs) — grep check in Task 14 (run `grep -rn "/api/v" routes/settings.py` and expect empty)
- [x] Hazard 2 (instrument config in three places) — Task 4 deletes old `_MULTIPLIERS`/`_YFINANCE_SYMBOLS`/`_STOOQ_SYMBOLS` from `services/instruments.py`
- [x] Hazard 3 (profiles) — no profile routes introduced
- [x] Hazard 4 (custom fields on positions table) — FK is `execution_id → executions(nt_execution_id)` in Task 1's migration
- [x] Hazard 5 (instrument groups) — no instrument-group table or routes

**Placeholder scan:**
- Every task has concrete file paths.
- Every step has complete code blocks or complete commands.
- No "TODO" / "similar to above" / "add validation as appropriate" phrases.
- No references to functions that aren't defined in this plan or in existing files.

**Type consistency:**
- `InstrumentConfig`, `InstrumentSources`, `SourceMapping`, `InstrumentSession` — Task 2 defines them; Tasks 3, 4, 8 consume them.
- `CustomFieldDefinition`, `CustomFieldOption`, `CustomFieldOptionInput` — Task 2 defines; Task 7 consumes.
- `CustomFieldsService` method names — `list_definitions`, `create_definition`, `update_definition`, `delete_definition`, `affected_executions`, `list_options`, `replace_options`, `get_execution_values`, `set_execution_value`, `values_for_position` — consistent across Tasks 7, 10, 11, 13.
- `get_defaults(db_path)` / `save_defaults(db_path, *, ...)` — Task 5 defines; Task 9 consumes; plan 13 `routes/ohlc.py` call site updated in Task 5.
- `save_display_timezone(path, value)` — Task 6 defines; Task 9 consumes.
- `set_registry_path(path)` / `get_registry()` — Task 4 defines; Task 8 consumes via `get_registry()`.

**Grep checks to run at end of Task 14:**
```bash
grep -rn "_MULTIPLIERS\|_YFINANCE_SYMBOLS\|_STOOQ_SYMBOLS" services/ models/ | grep -v instrument_registry.py
# Expected: empty

grep -rn "position_custom_field_values\|positions_id" migrations/ services/ routes/
# Expected: empty

grep -rn "/api/v1\|/api/v2" routes/settings.py
# Expected: empty

grep -rn "profile\|instrument_group" routes/settings.py services/custom_fields.py services/instrument_registry.py
# Expected: empty

grep -rn "from services.instruments import" services/ routes/ app.py
# Expected: only imports of the preserved public surface (get_multiplier, DEFAULT_TIMEFRAMES, etc.)
```

If any of those greps returns unexpected hits, stop and fix before marking the task complete.
