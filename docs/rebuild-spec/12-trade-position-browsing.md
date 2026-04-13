# Feature 12 — Position & Execution Browsing

## Purpose

Let the trader browse their trading activity: list positions with filters, drill into one position to see its fills and chart, attach notes and review flags, and link related positions together as one trade idea.

Positions displayed here are **computed on demand** from the executions currently in the database (doc 11). There is no `positions` table, no position IDs issued by the database, and no rebuild lifecycle. Every request to this feature's endpoints runs `build_positions` over the relevant executions and emits the result.

## Dependencies

- **Feature 10** — Executions must be in the database for positions to exist.
- **Feature 11** — `build_positions` is the function that turns executions into the positions this feature displays. Position identity is `(account, instrument, entry_execution_id)`.
- **Feature 13** — The position detail page embeds the OHLC chart.
- **Feature 14** — If OHLC data is unavailable for a position's time range, the chart area shows a delayed-data banner but the rest of the detail page still renders (doc 14 graceful-degradation rule).
- **Feature 16** — Custom fields and instrument metadata.

## User stories

1. **As the trader**, I want to see a list of all my positions, newest first, filterable by account, instrument, side, date range, and outcome (winner/loser/scratch).
2. **As the trader**, I want to drill into one position and see: a summary header, an OHLC chart with my entry and exit marked, every execution that built the position, and any notes I've attached.
3. **As the trader**, I want to add free-form notes and mark a position as "reviewed."
4. **As the trader**, I want to link several positions together as one "trade idea" — for example, when I scaled across two accounts — and view the group with a combined P&L.
5. **As the trader**, I want pagination so thousands of positions don't break the page.
6. **As the trader**, I want to delete a position by deleting its underlying executions, with a confirmation.
7. **As the trader**, when a position's underlying executions change (late import, data fix, rollback), I want the next time I open the page to show the correct position — I don't want to hit a "rebuild" button first.
8. **As the trader**, I want the list to update reactively when filters change without a full page reload.

## Acceptance criteria

1. The list page (`/positions`) shows positions newest-first by default with pagination (50 per page, configurable).
2. Filters on the list: account, instrument, side (Long/Short/All), outcome (Winner/Loser/Scratch/All), date range. Filters compose with AND. URL query params reflect the filter state so the page is bookmarkable.
3. Each list row shows: entry date, instrument, side, quantity, entry price, exit price, dollars P&L, duration, account, reviewed flag, note indicator.
4. Clicking a row opens the detail page at `/positions/{account}/{instrument}/{entry_execution_id}`. The URL is the position's natural key (doc 11). **There is no numeric position_id anywhere in URLs, query params, or templates.**
5. The detail page shows: header (account, instrument, side, quantity, entry/exit times and prices, points P&L, dollars P&L, commission, duration, reviewed flag), OHLC chart (feature 13), execution list (chronological), custom field values (feature 16), linked-position group reference if any, notes panel.
6. The execution list shows, per row: `execution_id` (the NT ExecutionId, including `#close`/`#open` suffixes for split fills), time, side, quantity, price, commission, original action, an inline notes editor.
7. Notes are attached to **executions**, not to positions. A "position's notes" is the union of the notes on its executions, displayed in the position detail page for convenience. This matches the identity rule from doc 11: executions are stable under late imports, derived positions are not, so metadata lives where it won't orphan.
8. A per-position "reviewed" flag is stored on the execution that opened the position (`entry_execution_id`). The UI treats "position is reviewed" as "the entry execution's reviewed flag is set." If a late import changes which execution is the entry, the reviewed flag moves with the original execution, not the position — this is a known minor UX quirk and acceptable given the honesty of the underlying model.
9. The "reviewed" toggle is a single click; it PATCHes the execution row and updates the position view in place.
10. Linking positions: from any position detail page, the user can search for other positions by `(account, instrument, date range)` and add them to a link group. A new group is created on first link. The link group is keyed by a server-generated `link_group_id` and stores an ordered list of `(account, instrument, entry_execution_id)` tuples — one row per linked position in a `position_links(link_group_id, account, instrument, entry_execution_id, ordinal)` table.
11. The link group page (`/links/{link_group_id}`) shows all positions in the group with a combined P&L summary. If any member position has been orphaned by a late import (the `entry_execution_id` no longer corresponds to an opening fill), the group still renders and the orphaned member is shown with a "position no longer exists in its original form" notice plus a link to the execution it used to point at.
12. **Deleting a position deletes its executions.** Since positions are derived, there is no "delete the position" operation distinct from "delete the underlying executions." The delete button on the detail page lists the execution IDs that will be removed, requires confirmation, and then calls `POST /api/executions/rollback` (feature 10) with those IDs. Links, notes, and reviewed flags on the deleted executions are cascade-deleted by foreign key.
13. All list and detail data comes from JSON endpoints; templates render only a shell with init scripts.
14. **Every read on this feature recomputes positions.** The list endpoint runs `build_positions` for each `(account, instrument)` in scope, concatenates, sorts, filters, and paginates. The detail endpoint runs `build_positions` for one `(account, instrument)` and picks the position whose `entry_execution_id` matches the URL. Performance note: for a trader with up to ~50 `(account, instrument)` pairs and a few thousand executions each, a full list render is well under 500ms without caching (doc 11). An in-memory memoization layer keyed by `(account, instrument, max_execution_time)` is permitted if profiling shows it's needed, but starts disabled.

## Data model additions

```sql
CREATE TABLE execution_notes (
  execution_id TEXT PRIMARY KEY,               -- NT ExecutionId, including #close/#open if applicable
  note         TEXT NOT NULL,
  updated_at   INTEGER NOT NULL,
  FOREIGN KEY (execution_id) REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);

CREATE TABLE execution_flags (
  execution_id TEXT PRIMARY KEY,
  reviewed     INTEGER NOT NULL DEFAULT 0,     -- boolean
  reviewed_at  INTEGER,
  FOREIGN KEY (execution_id) REFERENCES executions(nt_execution_id) ON DELETE CASCADE
);

CREATE TABLE link_groups (
  link_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
  label         TEXT,
  created_at    INTEGER NOT NULL
);

CREATE TABLE position_links (
  link_group_id      INTEGER NOT NULL REFERENCES link_groups(link_group_id) ON DELETE CASCADE,
  account            TEXT NOT NULL,
  instrument         TEXT NOT NULL,
  entry_execution_id TEXT NOT NULL,
  ordinal            INTEGER NOT NULL,
  PRIMARY KEY (link_group_id, account, instrument, entry_execution_id)
);
```

Notes on the schema:

- `execution_notes` and `execution_flags` are keyed by `nt_execution_id`, which is stable. Late imports that change position boundaries never orphan these rows. The FKs target `executions(nt_execution_id)`, which is promoted to a unique column by `idx_executions_nt_execution_id` in doc 10's schema — without that unique index, referencing the column alone (instead of the full `(nt_execution_id, account)` composite PK) would be invalid SQL.
- **User metadata only attaches to real executions, never to synthetic sub-fills.** The `#close`/`#open` suffixed IDs produced by the position-builder's reversal splitter (doc 11) exist only in `integrity_issues` and in display — they are not rows in `executions` and cannot be the target of notes, reviewed flags, or custom field values. If the UI is showing a split fill, the note/flag/custom-field editor writes against the parent `nt_execution_id` (the un-suffixed ID); the display may attribute the resulting metadata to both halves of the split.
- `position_links` stores the natural position key as three columns. When a position is orphaned by a late import (no build_positions output matches the stored entry_execution_id), the row still exists and the group page renders it with a "no longer resolvable" indicator.
- `FOREIGN KEY ON DELETE CASCADE` on execution-keyed tables means rolling back an execution via feature 10 automatically clears its notes and reviewed flag.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/positions` | Paginated list with filters via query params. Computed on demand. |
| GET | `/api/positions/{account}/{instrument}/{entry_execution_id}` | One position with full detail. |
| GET | `/api/positions/{account}/{instrument}/{entry_execution_id}/executions` | Chronological execution list for the position. |
| GET | `/api/positions/filters` | Available filter values (accounts, instruments) from the `executions` table. |
| PATCH | `/api/executions/{execution_id}/note` | Upsert note on one execution. |
| PATCH | `/api/executions/{execution_id}/reviewed` | Set reviewed flag on one execution. |
| POST | `/api/links` | Create a link group. Body: `{label?, members: [{account,instrument,entry_execution_id}, ...]}`. Returns `link_group_id`. |
| PATCH | `/api/links/{link_group_id}` | Rename, add/remove members. |
| DELETE | `/api/links/{link_group_id}` | Delete the group. |
| GET | `/api/links` | List all groups. |
| GET | `/api/links/{link_group_id}` | Group detail with combined stats. |

Deletion of a position is not a separate endpoint. The detail page's delete button calls `POST /api/executions/rollback` (feature 10) with the execution IDs the position contains.

## UI structure

- `/positions` — List page. Server renders an empty shell plus a filter form. JS fetches `/api/positions?...` and renders rows. Filter changes update the URL and refetch.
- `/positions/{account}/{instrument}/{entry_execution_id}` — Detail page. Server renders a shell with the three identifier fragments in data attributes. JS fetches everything else, including the chart bars.
- `/links/{link_group_id}` — Link group page. Same shell pattern; reuses the position renderer for each member.

All three pages follow Rule 5 (templates are shells). Every dynamic piece of data comes from a JSON endpoint.

## Fragmentation hazards

1. **Multiple browse pages with overlapping concerns.** The old codebase had `/`, `/trades`, `/positions/`, `/trades/detail/{id}`, `/trade/{id}`, `/positions/{id}` — six routes for "show me my activity." **Rule:** one list page and one detail page. No separate trades view. Executions are visible inside a position; they do not have their own top-level page.

2. **Numeric position IDs leaking out of the database into URLs.** The old schema's auto-increment `position_id` appeared in URLs, HTML element IDs, and foreign keys throughout the codebase. With positions now derived, a numeric position_id is a lie — it would change on every rebuild. **Rule:** every URL, query param, template variable, and API response uses `(account, instrument, entry_execution_id)` as the position identifier. No numeric position_id exists anywhere.

3. **Inline business logic in templates.** The old `templates/index.html` had ~120 LOC of inline JS for selection, deletion, and linking. **Rule:** templates contain a shell and an init script that calls a function from a `static/js/` file. All logic lives in JS files.

4. **Editing core fields from the UI.** The old code had a `/update-core-fields` route that let the user change entry/exit prices. **Rule:** the user can only edit user-supplied metadata (notes, reviewed flag, custom fields). To change a price, fix the source CSV and re-import.

5. **Synchronous rebuild triggers on delete.** The old delete handlers triggered position rebuilds inline. **Rule:** positions don't rebuild — they're derived. Deleting a position means deleting executions via the rollback endpoint, which runs the integrity diff but does not rebuild anything because there's no table to rebuild.

6. **Link groups as a separate concept with parallel UI.** The old "linked trades" feature had its own table, routes, and templates with their own renderers. **Rule:** link groups are a thin grouping layer that reuses the position renderer. The link group page embeds position cards by calling the same function used on `/positions`.

7. **Notes attached to position IDs.** In the old schema, notes were foreign-keyed to `positions.id`. When a rebuild changed position boundaries, notes orphaned silently. **Rule:** notes attach to `execution_id`. Always.

## Deviations from old behavior

- The old `/trades` and trade-detail pages are removed. Users browse positions; executions are visible only inside a position.
- Manual editing of position prices is removed. Source-of-truth data is executions; metadata is editable but derived fields are not.
- The "execution review" page (old `executions/review.html` for fixing side classifications) is removed. Integrity issues surface via feature 17; correction is re-import after fixing the CSV.
- Numeric position IDs are removed from the entire application. URLs, APIs, templates, and foreign keys all use the natural key.
- Notes migrate from position-level storage to execution-level storage. For a user coming from the old app, "my notes on position X" become "notes on the executions that made up position X" — the union is displayed on the position detail page unchanged from the user's perspective, but the underlying ownership is on the stable entity.

## Open questions for the implementer

- **Cross-account link label inference.** When the user links positions from two accounts, the group page probably wants a default label like "MNQ 2026-04-13 scaled entry." Leaving label generation to the user is fine for v1; an auto-suggest can be added later.
- **Position memoization cache.** Feature 11 says "add it only if profiling shows it's needed." This feature is the most likely place to need it (list page with many pairs). Measure first. If a cache is added, it lives in `services/positions.py`, not in `routes/`.
- **Outcome filter semantics.** Canonical Winner/Loser/Scratch definitions live in feature 15's Definitions section. The list-page filter uses those definitions verbatim — no new thresholds defined here.
