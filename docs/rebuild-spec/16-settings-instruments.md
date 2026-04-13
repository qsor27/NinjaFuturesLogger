# Feature 16 — Settings, Instruments & Custom Fields

## Purpose

Manage user-configurable values: instrument metadata (multipliers, tick sizes, symbol mapping), chart defaults, and user-defined custom fields that can be attached to positions.

## Dependencies

- **Feature 14** — The OHLC pipeline reads instrument symbol mapping from this feature.
- **Feature 11** — Position dollar P&L uses multipliers from this feature.
- **Feature 12** — Position detail page renders custom field values from this feature.

**Hard schema prerequisite:** Feature 10 must create `UNIQUE INDEX idx_executions_nt_execution_id ON executions(nt_execution_id)` **before** this feature's tables are created. The `execution_custom_field_values.execution_id → executions(nt_execution_id)` foreign key in this doc is only valid when `nt_execution_id` has a unique index of its own, because the `executions` table's primary key is composite (`nt_execution_id`, `account`). If the index is missing, the CREATE TABLE in this feature will fail at migration time. This ordering is load-bearing — do not reorder the migrations.

## User stories

1. **As the trader**, I want to configure each instrument I trade: display name, Yahoo Finance symbol, dollar multiplier per point, tick size.
2. **As the trader**, I want chart defaults — preferred timeframe and default volume on/off — that apply when I open any position chart. (The chart viewport is not configurable; it is always centered on the position's entry time and fits as many candles as the chart width allows — see feature 13.)
3. **As the trader**, I want to define custom fields I can fill in on positions — e.g., "setup type" (dropdown), "confidence" (number 1-5), "trade plan link" (text). These fields should appear on the position detail page for me to edit.
4. **As the trader**, when I add or change instrument config, I expect the change to take effect immediately for new fetches and for stat recomputation.

## Acceptance criteria

1. Instrument config is stored in `data/config/instruments.json` (single JSON file, hand-editable as a fallback). On app startup and on any update, an `InstrumentRegistry` service loads it into memory.
2. Each instrument entry has: `display_name`, `multiplier` (float), `tick_size` (float), a `sources` object with per-source symbol mappings (see doc 14 for the full shape — `yfinance` and `stooq` keys with continuous/contract templates), and a `session` object with exchange timezone and open/close times.
3. The settings UI (`/settings/instruments`) lists all instruments and lets the user create, edit, and delete them. Saves write the JSON file via the registry.
4. Chart defaults are stored in a single `chart_defaults` row in the database (one row, fixed key). Fields: `default_timeframe`, `volume_visible_default`. Edited from `/settings/chart`.
5. Custom field definitions are stored in a `custom_fields` table: `id`, `name` (unique), `field_type` (enum: text, number, dropdown, date, boolean), `is_active` (boolean), `display_order`.
6. Dropdown fields have associated `custom_field_options` rows: `id`, `field_id` (FK), `value`, `display_order`.
7. Custom field values are attached to **executions**, not to positions, for the same reason notes and reviewed flags are (doc 12): execution IDs are stable under late imports, derived position boundaries are not. Stored in `execution_custom_field_values` with a foreign key to `executions(nt_execution_id) ON DELETE CASCADE` and a composite primary key `(execution_id, field_id)`. See the schema section below.
8. The position detail page (feature 12) shows custom field values for the position's **entry execution** by default, with a fold-out to show values on other executions in the position. Editing a field from the position detail page writes to the entry execution's row.
9. Custom fields are managed via `/settings/custom-fields` (CRUD UI) and rendered on the position detail page (feature 12).
10. Inactive custom fields are not shown on position detail but their existing values are preserved.
11. Deleting a custom field deletes its values (with confirmation; the user is warned about how many executions are affected).

## Data model

Instrument config lives in `data/config/instruments.json` (see doc 14 for the full shape). Everything else is in SQLite:

```sql
-- Single-row table; id is constrained to 1 so there can never be a second row.
CREATE TABLE chart_defaults (
  id                       INTEGER PRIMARY KEY CHECK(id = 1),
  default_timeframe        TEXT NOT NULL DEFAULT '5m'
    CHECK(default_timeframe IN ('1m','5m','15m','1h','4h','1d')),
  volume_visible_default   INTEGER NOT NULL DEFAULT 1,                  -- boolean
  updated_at               INTEGER NOT NULL
);
-- Seed row inserted on first startup:
-- INSERT INTO chart_defaults (id, updated_at) VALUES (1, strftime('%s','now'));

CREATE TABLE custom_fields (
  field_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT NOT NULL UNIQUE,
  field_type     TEXT NOT NULL
    CHECK(field_type IN ('text','number','dropdown','date','boolean')),
  is_active      INTEGER NOT NULL DEFAULT 1,                            -- boolean
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
  execution_id   TEXT NOT NULL,                                         -- NT ExecutionId
  field_id       INTEGER NOT NULL
    REFERENCES custom_fields(field_id) ON DELETE CASCADE,
  value          TEXT NOT NULL,                                         -- JSON-stringified typed value
  updated_at     INTEGER NOT NULL,
  PRIMARY KEY (execution_id, field_id),
  FOREIGN KEY (execution_id)
    REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);
CREATE INDEX idx_execution_custom_field_values_field
  ON execution_custom_field_values(field_id);
```

Notes:

- **`chart_defaults` is a one-row table, not a key-value settings store.** The `CHECK(id = 1)` guarantees at the storage layer that there can never be a second row. The old codebase had a generic `settings` table with string keys; that pattern encourages ad-hoc additions and was a documented fragmentation hazard. One row, known columns, schema migrations for new fields.
- **Typed values are JSON-stringified in a single `value TEXT` column** rather than sharding into per-type columns. The `field_type` on `custom_fields` tells the reader how to decode. Dropdown values store the option's text value (not its `option_id`), so that renaming an option in `custom_field_options` does not orphan stored values — the tradeoff is that deleting an option leaves its existing values in place as "free text" until the user explicitly clears them, which matches the user's expectation (their data stays theirs).
- **`execution_custom_field_values.execution_id` is a plain TEXT foreign key into `executions(nt_execution_id)`**, not into a dedicated join surface. This is the identity rule from doc 11: user metadata attaches to stable execution IDs. `ON DELETE CASCADE` means rollback via feature 10 clears custom field values automatically. The FK relies on the `UNIQUE INDEX idx_executions_nt_execution_id` defined in doc 10's schema — without it, referencing `nt_execution_id` alone would be invalid because the composite primary key covers `(nt_execution_id, account)`.
- **Synthetic sub-fill IDs (`{execution_id}#close`, `{execution_id}#open`) are not valid `execution_id` values here.** The reversal splitter in doc 11 produces those suffixed IDs for display and for `integrity_issues` only; they are never rows in the `executions` table, so they cannot be the target of a custom field value either. Editors on the position detail page that show a split fill must write to the parent `nt_execution_id`, matching the rule documented in doc 12 for notes and reviewed flags.
- **No `position_custom_field_values` table.** See fragmentation hazard 4 below.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config/instruments` | Full instrument config |
| PUT | `/api/config/instruments/{symbol}` | Create or update one instrument |
| DELETE | `/api/config/instruments/{symbol}` | Remove an instrument |
| GET | `/api/config/chart-defaults` | Chart defaults |
| PUT | `/api/config/chart-defaults` | Update chart defaults |
| GET | `/api/custom-fields` | List custom field definitions |
| POST | `/api/custom-fields` | Create one |
| PUT | `/api/custom-fields/{id}` | Update one |
| DELETE | `/api/custom-fields/{id}` | Delete one (cascades to values) |
| GET | `/api/custom-fields/{id}/options` | Dropdown options for a field |
| PUT | `/api/custom-fields/{id}/options` | Replace options for a field |
| GET | `/api/executions/{execution_id}/custom-fields` | Get all custom field values for one execution |
| PUT | `/api/executions/{execution_id}/custom-fields/{field_id}` | Set one value |
| GET | `/api/positions/{account}/{instrument}/{entry_execution_id}/custom-fields` | Convenience view: custom field values across the position's executions, computed by looking up each execution's values |

UI pages: `/settings`, `/settings/instruments`, `/settings/chart`, `/settings/custom-fields`.

## Fragmentation hazards

1. **Multiple settings APIs.** The old codebase had `/api/v1/settings/chart`, `/api/v2/settings/categorized`, `POST /settings/chart` (form), and `POST /api/v2/settings/validate` — four endpoints for "save chart settings." **Rule:** one endpoint per resource. No `/v1` and `/v2` parallel APIs; if a redesign is needed later, redesign in place.

2. **Instrument config in three places.** The old code had `instrument_management_service.py`, `symbol_service.py`, and a separate `instrument_groups` table, plus hardcoded mappings in some import services. **Rule:** one JSON file, one registry service, one settings page.

3. **"Profiles" feature.** The old code had a profiles system (`routes/profiles.py`) for user accounts and saved settings exports/imports. The new spec drops profiles entirely — single user, single config file. If the user wants to export their config, they copy `data/config/instruments.json` and the database file. No app code for export/import.

4. **Custom fields coupled to a positions table.** The old code had a `position_custom_field_values` table foreign-keyed to `positions.id`. Since there is no `positions` table in the new schema, that coupling is impossible. **Rule:** custom field values attach to `nt_execution_id`. One `CustomFieldsService` owns all CRUD. A position-level view exists only as a convenience that reads values from the position's executions — it is not a separate storage layer.

5. **"Instrument groups."** The old code had instrument groups for the user to define collections of symbols. This is removed unless the user explicitly wants it; in the rebuild it's not in the spec.

## Deviations from old behavior

- The profiles system is removed.
- Instrument groups are removed.
- The two parallel settings APIs collapse to one per resource.
- Settings live in a single JSON file plus a single `chart_defaults` table row, not in a generic `settings` key-value table.
- Custom field values move from position-keyed storage to execution-keyed storage. For a user coming from the old app, values that were "on position X" become "on the entry execution of position X," with the position detail page displaying them in exactly the same place. The change is invisible in the UI but prevents the orphaning that happened every time positions rebuilt.
- Instrument config gains a per-source `sources` block and a `session` block (see doc 14), replacing the single `yahoo_continuous` / `yahoo_contract_template` fields.
