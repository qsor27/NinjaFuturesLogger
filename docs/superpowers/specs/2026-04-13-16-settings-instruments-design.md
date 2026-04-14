# Plan 16 design — Settings, Instruments & Custom Fields

**Spec doc:** `docs/rebuild-spec/16-settings-instruments.md`
**Depends on:** plans 10, 11, 12, 13, 14, 15 (all complete as of 2026-04-13)
**Build order:** 00 → 10 → 11 → 14 → 12 → 13 → 15 → **16** → 17

## Purpose

Replace the hardcoded stubs in `services/instruments.py` and `services/chart_defaults.py` with a JSON-backed instrument registry and a DB-backed chart-defaults row. Add user-defined custom fields keyed to `nt_execution_id` with full CRUD. Render custom fields on the plan 12 position detail page. Everything behind `/settings/*`.

The spec is extensive and internally consistent; this design records the decisions made on top of it and the task shape the writing-plans skill should turn into a plan file.

## Architecture

Two new services plus one migration, bodies swapped in two existing "seam" modules.

### New modules

- `migrations/006_settings_custom_fields.sql` — `chart_defaults` (with seed row `id=1`), `custom_fields`, `custom_field_options`, `execution_custom_field_values`, exactly the DDL from doc 16. Migration 006 runs after plan 12's `005_browsing.sql`. Plan 10's `UNIQUE INDEX idx_executions_nt_execution_id` is already in place, so the FK on `execution_custom_field_values.execution_id → executions(nt_execution_id)` is valid at migration time (this ordering is load-bearing — doc 16 "Hard schema prerequisite").
- `services/instrument_registry.py` — owns `data/config/instruments.json`. Public API: `load()`, `get(symbol)`, `list()`, `put(symbol, InstrumentConfig)`, `delete(symbol)`. Atomic write (`instruments.json.tmp` + `os.replace`) guarded by a module-level `threading.Lock`. First load seeds the file from `DEFAULT_SEED` (the multiplier/symbol/session tables currently hardcoded in `services/instruments.py`) if the file is missing or empty.
- `services/custom_fields.py::CustomFieldsService` — owns all CRUD for `custom_fields`, `custom_field_options`, and `execution_custom_field_values`. Methods: `list_definitions`, `create_definition`, `update_definition`, `delete_definition(id, confirm_count)`, `list_options`, `replace_options`, `get_execution_values(execution_id)`, `set_execution_value(execution_id, field_id, value)`, `values_for_position(account, instrument, entry_execution_id)`. Every mutator calls `notes.strip_split_suffix` before touching the DB so synthesized `#close`/`#open` sub-fills inherit the parent execution's values.
- `models/settings.py` — Pydantic StrictModels: `InstrumentSources`, `InstrumentSession`, `InstrumentConfig`, `ChartDefaults`, `CustomFieldDefinition`, `CustomFieldOption`, `CustomFieldValue`. All exported from `models/__init__.py`.
- `routes/settings.py` — new Flask blueprint. Registers 13 API endpoints and 4 shell-template page routes. Registered in `create_app()` alongside existing blueprints.
- `static/js/settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js` — one vanilla ES module per settings page. No bundler, no framework.
- `templates/settings_index.html`, `templates/settings_instruments.html`, `templates/settings_chart.html`, `templates/settings_custom_fields.html` — shell templates extending `base.html`.

### Existing modules rewritten in place (same public API, new bodies)

- `services/instruments.py` — the whole module is rewritten to delegate to `InstrumentRegistry`. Public names preserved exactly: `base_symbol`, `get_multiplier`, `DEFAULT_TIMEFRAMES`, `source_symbol`, `SessionCalendar`, `default_session`. The hardcoded `_MULTIPLIERS` / `_YFINANCE_SYMBOLS` / `_STOOQ_SYMBOLS` / `_DEFAULT_CME_SESSION` tables move into `instrument_registry.DEFAULT_SEED` (consumed only by `seed_if_missing`). Plan 11 (`services/positions.py`), plan 14 (`services/ohlc/yfinance_source.py`, `stooq_source.py`, `gap_detection.py`) and plan 14's post-tick hook in `app.py` are untouched.
- `services/chart_defaults.py` — `get_defaults()` body swapped to a `SELECT` against `chart_defaults`. Module-level `DEFAULT_TIMEFRAME` and `VOLUME_VISIBLE_DEFAULT` constants stay as defensive fallbacks if the row is somehow missing. Fresh-dict-per-call invariant preserved. A new `save_defaults(default_timeframe, volume_visible_default)` companion writes the `chart_defaults` row inside a caller-supplied transaction.
- `config.py` — gains a new `save_display_timezone(path, value)` helper that performs a read-modify-write of `data/config/app.json` under a module-level `threading.Lock` with atomic tmp+`os.replace`. Validates the new value by constructing `zoneinfo.ZoneInfo(value)` before writing. Existing `load_config` is untouched. No partial-update route for other Config fields — this helper exists solely for the chart-defaults PUT handler's `display_timezone` case.
- `services/positions_service.py::attach_metadata` — `custom_fields: []` stub is replaced with a call to `CustomFieldsService.values_for_position(...)`. Returns `{entry, per_execution, definitions}` (shape below).
- `routes/positions.py` — the existing position detail endpoint automatically picks up the new `custom_fields` shape through `attach_metadata`. No new positions route. One existing endpoint family grows: `/api/executions/{id}/custom-fields` GET and `/api/executions/{id}/custom-fields/{field_id}` PUT live on the settings blueprint, not on positions.

## Data model

### `instruments.json` shape

Loaded as `dict[str, InstrumentConfig]` keyed by canonical NT symbol:

```json
{
  "ES": {
    "display_name": "E-mini S&P 500",
    "multiplier": 50.0,
    "tick_size": 0.25,
    "sources": {
      "yfinance": { "continuous": "ES=F", "contract_template": null },
      "stooq":    { "continuous": "es.f",  "contract_template": null }
    },
    "session": {
      "timezone": "America/Chicago",
      "open": "17:00",
      "close": "16:00",
      "daily_break_start": "16:00",
      "daily_break_end": "17:00"
    }
  }
}
```

Pydantic models:
- `InstrumentSources` — `yfinance: SourceMapping`, `stooq: SourceMapping` (both required but inner fields optional)
- `SourceMapping` — `continuous: str | None`, `contract_template: str | None`
- `InstrumentSession` — `timezone: str`, `open: str`, `close: str`, `daily_break_start: str`, `daily_break_end: str` (last two may be empty strings to disable, per plan 14's `SessionCalendar`)
- `InstrumentConfig` — `display_name: str`, `multiplier: float`, `tick_size: float`, `sources: InstrumentSources`, `session: InstrumentSession`

`DEFAULT_SEED` is generated from the existing plan 11/14 hardcoded tables. Instruments in `_MULTIPLIERS` but missing from a symbol map get `sources.yfinance.continuous = null` and `sources.stooq.continuous = null` — the plan 14 adapters already return `None` for that case so there's no regression.

### SQLite tables (migration 006)

Exactly the DDL from doc 16 — no deviations:

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

### Value encoding for `execution_custom_field_values.value`

One `TEXT` column, decoded by the owning `custom_fields.field_type`:

| `field_type` | Stored as | Example |
|---|---|---|
| `text`     | raw string (not JSON-wrapped) | `"A+ setup"` |
| `number`   | `json.dumps(float)` | `"4.0"` |
| `dropdown` | the option's text `value`, not its `option_id` | `"Breakout"` |
| `date`     | ISO-8601 date string | `"2026-04-13"` |
| `boolean`  | `"true"` / `"false"` | `"true"` |

Encoders and decoders live on `CustomFieldsService`. The encoder validates against `custom_fields.field_type` at write time and rejects mismatches with HTTP 400. Dropdown writes are validated against the current `custom_field_options` set for that field. Deleting an option later does NOT retroactively invalidate stored values — the user's data stays theirs (doc 16 data-model notes).

## API surface

Exactly the 13 endpoints from doc 16:

### Instruments (backed by `InstrumentRegistry`)

- `GET /api/config/instruments` → `{instruments: {symbol: InstrumentConfig}}`
- `PUT /api/config/instruments/{symbol}` body `InstrumentConfig` → 200 `{instrument: ...}`, 400 on validation failure
- `DELETE /api/config/instruments/{symbol}` → 204, 404 if unknown

### Chart defaults (DB-backed, plus `display_timezone` via `Config`)

- `GET /api/config/chart-defaults` → `{default_timeframe, volume_visible_default, display_timezone}`
- `PUT /api/config/chart-defaults` same shape → 200. Validates `default_timeframe ∈ {1m,5m,15m,1h,4h,1d}` and `display_timezone` via `zoneinfo.ZoneInfo(...)` (rejecting invalid IANA strings with 400). `default_timeframe` and `volume_visible_default` write to the `chart_defaults` row via `chart_defaults.save_defaults(...)`. `display_timezone` writes to `data/config/app.json` via a new `config.save_display_timezone(path, value)` helper that does a read-modify-write of the JSON file under a module-level `threading.Lock` with atomic tmp+rename. No schema change to `chart_defaults` table. The handler writes DB first, then the JSON file; on JSON write failure the DB change is rolled back via a wrapping transaction committed only after the file write succeeds.

### Custom field definitions

- `GET /api/custom-fields` → `{fields: [...]}` (includes inactive; UI filters)
- `POST /api/custom-fields` → creates definition (409 on name collision)
- `PUT /api/custom-fields/{id}` → update name/type/is_active/display_order. Rejects `field_type` changes once any values exist (400 with `{affected_executions: N}`).
- `DELETE /api/custom-fields/{id}?confirm_count=N` — two-step delete. Without `confirm_count`, returns 409 with `{affected_executions: N}` so the UI can show the warning. With matching `confirm_count`, cascades.
- `GET /api/custom-fields/{id}/options` → `{options: [...]}`
- `PUT /api/custom-fields/{id}/options` body `{options: [{value, display_order}, ...]}` → replace-in-place. Unchanged values keep their `option_id` (match by `value` text) so `display_order` edits don't churn FKs.

### Custom field values

- `GET /api/executions/{execution_id}/custom-fields` → `{values: {field_id: decoded_value}}`
- `PUT /api/executions/{execution_id}/custom-fields/{field_id}` body `{value}` → 200. Empty/null `value` deletes the row. 400 if the execution doesn't exist (after suffix-stripping), if `field_id` is inactive/unknown, or if the value fails type validation.
- `GET /api/positions/{account}/{instrument}/{entry_execution_id}/custom-fields` → `{entry, per_execution, definitions}` convenience read. Computed from the position's executions. No new storage.

### UI pages

- `/settings` — index linking to the three sub-pages. ~30 lines of template, no JS.
- `/settings/instruments` — table of instruments, add/edit modal, delete with confirmation. `settings_instruments.js`.
- `/settings/chart` — form for `default_timeframe`, `volume_visible_default`, `display_timezone`. `settings_chart.js`.
- `/settings/custom-fields` — list of definitions, inline create/edit, options editor for dropdown type, delete with affected-count warning. `settings_custom_fields.js`.

All four extend `base.html`. Vanilla ES modules only; no third-party JS beyond the plan 13 vendored Lightweight Charts (unused on these pages).

## Plan 12 position detail integration

### Backend

`services/positions_service.py::attach_metadata` returns:

```python
{
    "position": Position,
    "notes": {execution_id: text},
    "reviewed": {execution_id: bool},
    "custom_fields": {
        "entry": {field_id: decoded_value, ...},
        "per_execution": [
            {"execution_id": "...", "values": {field_id: decoded_value, ...}},
            ...
        ],
        "definitions": [CustomFieldDefinition, ...],  # active only, sorted by display_order
    },
}
```

`per_execution` contains one entry per non-entry execution that has any value (empty list if none). `definitions` includes only active definitions. Inactive definitions with stored values appear in `per_execution[*].values` and in `entry` but are filtered out of `definitions` — the frontend shows their stored values read-only with a "(inactive)" label.

### Frontend

`static/js/position_detail.js` renders a new `#custom-fields` block between Notes and the Executions table:

- Always-visible labeled inputs for each active definition, pre-populated from `entry`. Inputs typed by `field_type`: `text → <input type="text">`, `number → <input type="number" step="any">`, `date → <input type="date">`, `boolean → <input type="checkbox">`, `dropdown → <select>`. Blur-to-save via `PUT /api/executions/{entry_execution_id}/custom-fields/{field_id}` with optimistic update and error toast on failure.
- `<details>` fold-out labeled `Per-execution values (N)` where N is `per_execution.length`. Hidden entirely if `per_execution` is empty. When expanded, renders a compact table with one column per active field and one row per execution with values. Blur-to-save to the non-entry execution.
- Custom fields do NOT participate in the plan 13 `executions-table:row-clicked` / `chart:execution-clicked` bus. They are independent of the chart ↔ table link.

No changes to `PositionFilter` — custom-field filtering is explicitly out of scope for plan 16.

## Testing & acceptance

### Test files

- `tests/test_migration_006.py` — fresh DB, apply all migrations, assert the four tables exist, `chart_defaults` has exactly one row with `id=1`, `CHECK(id=1)` rejects a second insert, the `execution_custom_field_values → executions` FK enforces cascade delete.
- `tests/test_instrument_registry.py` — missing file seeds from `DEFAULT_SEED`, round-trip put/get/delete, atomic write via mocked `os.replace`, concurrent writers serialize via lock (no torn JSON), schema validation rejects bad payloads.
- `tests/test_instruments_registry_backcompat.py` — after the body swap, `get_multiplier("ES") == 50.0`, `source_symbol("MES", "yfinance") == "MES=F"`, `default_session("NQ")` returns the CME session. Plan 11/14 callers unaffected.
- `tests/test_chart_defaults.py` (existing plan 13 file) — extended with cases for DB-backed reads and `display_timezone` Config round-trip through `PUT /api/config/chart-defaults`.
- `tests/test_custom_fields_service.py` — create/update/delete definitions; dropdown option replace-in-place preserves `option_id` for unchanged values; value encoding/decoding for all five `field_type`s; write rejects type mismatches; write to a `#close`-suffixed execution_id lands on the parent row; two-step delete flow; deleting a field cascades values; inactive field preserves stored values.
- `tests/test_custom_fields_routes.py` — the 9 custom-field endpoints end-to-end through `create_app()`.
- `tests/test_settings_routes.py` — instrument CRUD writes `instruments.json` under a tmp `data_dir`, chart-defaults round-trip including `display_timezone` IANA validation, UI shell pages return 200.
- `tests/test_position_detail_custom_fields.py` — `attach_metadata` returns the expected `{entry, per_execution, definitions}` shape; `per_execution` includes only non-entry executions with values; inactive definitions with stored values are excluded from `definitions` but included in `per_execution[*].values`.
- `tests/test_app_factory_plan16.py` — spins up `create_app(...)`, asserts all 13 new API routes and 4 page routes registered, asserts `/static/js/settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js` are served.

### Acceptance criteria → tests

| AC | Covered by |
|---|---|
| 1. instruments.json loaded by registry | `test_instrument_registry.py::test_load_seeds_if_missing` |
| 2. required instrument fields | `test_instrument_registry.py::test_put_rejects_missing_fields` |
| 3. settings UI CRUD writes JSON | `test_settings_routes.py::test_instruments_put_writes_json` |
| 4. chart_defaults single row | `test_migration_006.py::test_chart_defaults_single_row_check` |
| 5. custom_fields schema | `test_migration_006.py` + `test_custom_fields_service.py` |
| 6. custom_field_options schema | `test_migration_006.py` + `test_custom_fields_service.py::test_replace_options` |
| 7. values attach to executions with cascade | `test_migration_006.py::test_cascade_on_execution_delete` |
| 8. entry execution default + fold-out | `test_position_detail_custom_fields.py` |
| 9. /settings/custom-fields CRUD | `test_custom_fields_routes.py` |
| 10. inactive fields preserved | `test_custom_fields_service.py::test_inactive_preserves_values` |
| 11. delete warns with count | `test_custom_fields_service.py::test_delete_two_step` |

### Docker end-to-end verification (deferred to user-run, same pattern as plans 13/15)

- Edit an instrument in `/settings/instruments`, drop a CSV for that instrument into the inbox, verify the correct multiplier in `/api/positions` `dollars_pnl`.
- Define a dropdown custom field "Setup", tag a position from its detail page, reload and verify persistence.
- Change `display_timezone` on `/settings/chart`, verify `/api/stats/by-hour` rebuckets.
- Rollback the execution via the delete button, verify the custom field value row is gone (cascade).

## Fragmentation hazards enforced structurally

- **Hazard 1 (multiple settings APIs)** — one endpoint per resource; no `/v1`/`/v2` parallel paths. Grep check in the plan.
- **Hazard 2 (instrument config in three places)** — only `InstrumentRegistry` touches `instruments.json`; `services/instruments.py` is a thin delegator. Grep for `_MULTIPLIERS`/`_YFINANCE_SYMBOLS`/`_STOOQ_SYMBOLS` should only match `instrument_registry.DEFAULT_SEED`.
- **Hazard 3 (profiles)** — no profile system, no export/import routes. Plan 16 ships no routes matching `profile`.
- **Hazard 4 (custom fields on positions table)** — no `position_custom_field_values` table; FK is `execution_id → executions(nt_execution_id)`.
- **Hazard 5 (instrument groups)** — no instrument groups table, no routes.

## Deliberately out of scope for plan 16

- **Filtering positions by custom field value** — would need a separate design for typed value comparisons; not in doc 16's ACs.
- **Custom field chart ↔ table linking** — custom fields do not dispatch or listen on the plan 13 custom event bus.
- **Bulk edit of custom field values** — one execution at a time; bulk tagging is not in the spec.
- **Instrument groups / "watchlists"** — doc 16 fragmentation hazard 5 explicitly removes this.
- **Import/export of settings** — doc 16 fragmentation hazard 3 explicitly removes profiles/export-import.
- **Schema migration for `display_timezone` into `chart_defaults`** — kept in `Config`/`app.json` to avoid mixing storage sources for user preferences; spec's 2-column schema preserved.

## Task shape for writing-plans

Expected task count: ~14. Rough order (writing-plans will refine):

1. Migration 006 + `test_migration_006.py`
2. `models/settings.py` Pydantic StrictModels + round-trip tests
3. `services/instrument_registry.py` + `test_instrument_registry.py`
4. Rewrite `services/instruments.py` bodies to delegate + `test_instruments_registry_backcompat.py`
5. Rewrite `services/chart_defaults.py::get_defaults()` body + extend `test_chart_defaults.py`
6. `services/custom_fields.py::CustomFieldsService` + `test_custom_fields_service.py`
7. `routes/settings.py` blueprint: instrument endpoints + `test_settings_routes.py` (instruments slice)
8. `routes/settings.py`: chart-defaults endpoint + `chart_defaults.save_defaults` + `config.save_display_timezone` helper + test slice
9. `routes/settings.py`: custom-fields definition + options endpoints + `test_custom_fields_routes.py` (definitions slice)
10. `routes/settings.py`: custom-field value endpoints (execution + position convenience) + test slice
11. `templates/settings_*.html` + `/settings/*` page routes + `static/js/settings_*.js` modules
12. Wire `attach_metadata` to `CustomFieldsService` + update `position_detail.js` + `test_position_detail_custom_fields.py`
13. `test_app_factory_plan16.py` smoke
14. `docs/rebuild-spec/00-README.md` "What Plan 16 landed" section

## Open questions for writing-plans

None. Every decision above was made in the brainstorming session with explicit user approval per section.
