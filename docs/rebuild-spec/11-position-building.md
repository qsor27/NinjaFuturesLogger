# Feature 11 — Position Building

## Purpose

Group stored executions into logical positions for display and analysis. Positions are a **derived view** over the executions table — they are never stored. Every query that needs positions computes them from the executions currently in the database.

This is the most algorithmically sensitive part of the system; if the grouping function is wrong, every downstream feature is wrong. But the function itself is small (under 100 lines of Python) and has no persistence, no caching, no orchestration, and no rebuild lifecycle to reason about.

## Dependencies

- **Doc 02** — Read the glossary entries for execution, position, Action, Side, position side, quantity flow, direction reversal, Entry/Exit. The terminology must be precise.
- **Feature 10** — Executions arrive through the import pipeline. No import → no executions → no positions.
- **Feature 14** — Charts display OHLC data spanning a position's time range. Position time ranges are computed from the grouping function's output.

## What a position is

A **position** is the sequence of executions for one `(account, instrument)` that starts when the running signed quantity leaves zero and ends when it returns to zero.

- **Running quantity** is the signed sum of all fills seen so far, where Buy is positive and Sell is negative.
- **Flat** means running quantity equals zero and the account holds no exposure in that instrument.
- A position opens on the fill that takes running quantity from zero to non-zero.
- A position closes on the fill that takes running quantity from non-zero back to zero.
- If the last execution for a pair leaves running quantity non-zero, the last position is **open**: it has no exit time, no exit price, and no realized P&L. It still exists as a logical position, just without the closing fields filled in.

## Core rule: positions are derived, not stored

There is no `positions` table. There is no position rebuild, no rebuild pipeline, no rebuild scheduler, no position ID, no position foreign key, no junction table. Asking "what are my positions for this instrument?" runs the grouping function over the executions currently in the database and emits a list of position records in memory. The list lives for the duration of the request and is discarded.

This means:

- **Out-of-order imports are trivially safe.** The function always sorts executions by timestamp before grouping, so the order rows arrived in the DB is irrelevant.
- **There is no stale state.** The function's output is a pure function of the executions in the DB right now. Fix the executions → the next call produces correct positions. No invalidation, no cache-busting, no "why didn't the positions update?"
- **There is no materialization bug surface.** The old codebase had an entire class of bugs where the `positions` table disagreed with the `trades` table. That class is impossible here because there is no second table to disagree with the first one.
- **Position identity is computed.** A position is identified by `(account, instrument, entry_execution_id)` where `entry_execution_id` is the NinjaTrader ExecutionId of the first fill that took running quantity away from zero. This key is stable across function calls as long as the underlying executions don't change.

If performance ever becomes a concern, a memoization layer keyed by `(account, instrument, max(execution_time))` is the escape hatch — cache the function's output until a new execution arrives for that pair. This is a cache over a pure function, which is the only kind of cache that's safe to add without introducing a new bug class. **Don't add the cache until profiling shows you need it.**

## User stories

1. **As the trader**, when I open the positions page, I expect to see every position reflected by my current executions — I do not click "rebuild."
2. **As the trader**, I expect each position to correspond to one logical trade idea: flat → exposure → flat, with all fills in between accounted for.
3. **As the trader**, I expect a position's entry and exit prices to be the volume-weighted averages of its entry and exit fills, and its size to be the maximum absolute exposure during the position (for display), with quantity computed from the opening fills.
4. **As the trader**, when the data contradicts itself (e.g., a fill would drive running quantity below zero when I was flat, or the exporter's `Position` column disagrees with the computed running quantity), I expect the issue to be surfaced loudly as an **integrity issue** on the monitoring dashboard (feature 17) instead of being silently smoothed over.
5. **As the trader**, I expect the same set of executions to always produce the same positions, regardless of the order in which they were imported or how many times the page is refreshed.

## Acceptance criteria

1. `build_positions(executions: list[Execution]) -> (list[Position], list[IntegrityIssue])` is a **pure function** in one module. No DB access, no I/O, no globals, no mutable class state.
2. The function sorts its input by `(timestamp, execution_id)` before grouping; caller is not required to pre-sort.
3. The function produces one `Position` per quantity-flow cycle (zero → non-zero → zero), plus at most one open position at the end (running quantity still non-zero).
4. The function handles **direction-reversing executions** — a single raw fill that crosses zero in one step (long 3, then sell 5) — by splitting the fill into two synthetic sub-fills: one that brings running quantity to zero (closing the current position) and one that takes it from zero to the new quantity (opening the next position). Both sub-fills reference the same source `execution_id` with suffixes (`{execution_id}#close`, `{execution_id}#open`). The sub-fills inherit the parent's price and timestamp; per-contract commission is split proportionally by quantity. **Sub-fills are in-memory constructs only.** They are produced by `build_positions` during the walk, consumed by the same call to build the two adjacent positions, and discarded when the function returns. They are **never inserted into the `executions` table**, they are **never queryable via SQL**, and the only place their suffixed IDs can appear on disk is in `integrity_issues.execution_id`. Reversing fills are expected to be rare in practice (they are the output of NinjaTrader's reversing-order button); the spec handles them correctly but does not optimize for them.
5. Each `Position` record in the returned list has:
   - `account`, `instrument`
   - `entry_execution_id` — the NT ExecutionId of the opening fill (natural identity key)
   - `side` — `Long` or `Short`
   - `entry_time`, `exit_time` (None if open)
   - `quantity` — sum of entry-fill quantities
   - `entry_price` — volume-weighted average of entry-fill prices
   - `exit_price` — volume-weighted average of exit-fill prices (None if open)
   - `points_pnl`, `dollars_pnl` (None if open)
   - `commission` — sum of all fills' commission (entry + exit)
   - `duration_minutes` (None if open)
   - `execution_ids` — ordered list of NT ExecutionIds participating in this position, including the `#close`/`#open` suffixes for any split fills
6. Open positions (running quantity did not return to zero by the last execution) are included in the returned list with the open fields set to None. They are still positions.
7. The function cross-checks itself against the exporter's `Position` column: for each execution, the running quantity it computes should match what the CSV's `Position` column says NT saw. Any disagreement becomes an `IntegrityIssue` with severity=high. The function still returns positions built from its own computation — the check flags the mismatch, it does not change the math.
8. An `IntegrityIssue` record has: `account`, `instrument`, `execution_id` (the fill that caused the issue), `severity`, `type`, `description`, `detected_at`. Integrity issues are keyed by execution_id, never by position — executions are stable, derived positions are not.
9. Integrity issues are persisted in an `integrity_issues` table. On each call to `build_positions` from a route handler that writes (i.e., after an import), the importer diffs the new issue set against the stored set for that `(account, instrument)`: new issues are inserted, issues no longer present are auto-resolved (`resolved_at = now`, `resolved_by = 'system'`). Issues the user explicitly marked as ignored stay ignored regardless.
10. The user can mark an issue as resolved or ignored from the monitoring UI (feature 17). This sets `resolved_at` and `resolved_by` on the stored row; it does not affect the function's output on the next call.

## Algorithm

```python
def build_positions(executions: list[Execution]) -> tuple[list[Position], list[IntegrityIssue]]:
    executions = sorted(executions, key=lambda e: (e.timestamp, e.execution_id))

    running_qty = 0
    current_fills: list[Fill] = []
    positions: list[Position] = []
    issues: list[IntegrityIssue] = []

    for ex in executions:
        signed = ex.quantity if ex.side == Side.BUY else -ex.quantity
        new_qty = running_qty + signed

        # Direction-reversing fill: splits into close + open sub-fills.
        if running_qty != 0 and new_qty != 0 and sign(new_qty) != sign(running_qty):
            close_qty = abs(running_qty)
            open_qty  = abs(new_qty)
            sub_close = synthesize_fill(ex, signed=-running_qty, id_suffix="#close")
            sub_open  = synthesize_fill(ex, signed=new_qty,      id_suffix="#open")

            current_fills.append(sub_close)
            positions.append(make_position(current_fills, open=False))
            current_fills = [sub_open]
            running_qty = new_qty
            continue

        current_fills.append(ex)
        running_qty = new_qty

        # Flat: running qty returned to zero. Position closes on this fill.
        if running_qty == 0:
            positions.append(make_position(current_fills, open=False))
            current_fills = []

    # Any fills left over are an open position.
    if current_fills:
        positions.append(make_position(current_fills, open=True))

    issues += cross_check_against_source_position_column(executions, positions)
    return positions, issues
```

`make_position(fills, open)`:

- `side` = Long if `fills[0]` is a Buy, else Short
- `entry_execution_id` = `fills[0].execution_id` (with the `#open` suffix if the fill was synthesized)
- `entry_time` = `fills[0].timestamp`, `exit_time` = `fills[-1].timestamp` if not open else None
- Split fills into entry-fills and exit-fills:
  - Long position → Buys are entries, Sells are exits
  - Short position → Sells are entries, Buys are exits
- `entry_price` = volume-weighted average of entry-fills' prices
- `exit_price` = volume-weighted average of exit-fills' prices (None if open)
- `quantity` = sum of entry-fills' quantities (the size opened)
- `points_pnl` = `(exit_price - entry_price) * (quantity if Long else -quantity)`, None if open
- `dollars_pnl` = `points_pnl * multiplier(instrument)`, None if open
- `commission` = sum of all fills' commission
- `execution_ids` = ordered list of each fill's id (including `#close`/`#open` suffixes)

## Integrity issues schema

Integrity issues are the **only** persistent output of position building. Positions themselves are never stored; issues are, because the user interacts with them (resolve, ignore, note) and those interactions must survive across requests.

```sql
CREATE TABLE integrity_issues (
  issue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  account         TEXT NOT NULL,
  instrument      TEXT NOT NULL,
  execution_id    TEXT NOT NULL,                                         -- NT ExecutionId (may carry #close/#open suffix)
  severity        TEXT NOT NULL CHECK(severity IN ('low','medium','high')),
  type            TEXT NOT NULL,                                         -- e.g. 'position_column_mismatch', 'impossible_quantity'
  description     TEXT NOT NULL,
  detected_at     INTEGER NOT NULL,                                      -- unix seconds, first time this issue was seen
  last_seen_at    INTEGER NOT NULL,                                      -- unix seconds, most recent integrity diff that still produced it
  resolved_at     INTEGER,                                               -- null while open
  resolved_by     TEXT CHECK(resolved_by IN ('system','user') OR resolved_by IS NULL),
  resolution_note TEXT,                                                  -- user-provided when resolved_by='user'
  ignored         INTEGER NOT NULL DEFAULT 0,                            -- boolean; ignored issues stay ignored across diffs
  ignore_note     TEXT,                                                  -- mandatory when ignored=1
  UNIQUE (account, instrument, execution_id, type)
);

CREATE INDEX idx_integrity_open
  ON integrity_issues(account, instrument, severity)
  WHERE resolved_at IS NULL AND ignored = 0;
```

Notes:

- **The `UNIQUE` constraint** `(account, instrument, execution_id, type)` is what makes the diff stable: re-running `build_positions` for the same data always upserts onto the same row rather than creating duplicates. `detected_at` is set on first insert; `last_seen_at` is bumped on every diff that still produces the issue.
- **`resolved_at IS NULL AND ignored = 0`** is the "open issue" predicate used by the monitoring view (doc 17). The partial index serves that query in constant time.
- **No foreign key to `executions`.** Integrity issues about an execution should survive the execution being deleted via rollback — the open question there is whether to cascade or leave as a forensic record. Current spec: no cascade (forensic). Feature 17 surfaces issues whose execution no longer exists with a "source execution deleted" indicator. If this becomes noise, a cascade can be added; it's a reversible schema change.

## Where the function lives

```
services/positions.py       # build_positions, make_position, sign, synthesize_fill
services/integrity.py       # cross_check_against_source_position_column, IntegrityValidator
```

Two files. No `services/position_engine.py`, no `position_algorithms_v2.py`, no `enhanced_position_service.py`. If you find yourself wanting a third file for positions, something is wrong.

Callers:

- **Feature 12 (browsing)** — list page calls `build_positions` once per `(account, instrument)` being displayed; detail page looks up one position by `entry_execution_id` from the result.
- **Feature 15 (statistics)** — aggregates over the function's output.
- **Feature 10 (import)** — after an import completes, runs `build_positions` once per `(account, instrument)` that received new rows, solely to diff integrity issues. It does not store the positions themselves.

## API surface

There are no `/api/positions/rebuild*` endpoints because nothing rebuilds.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/positions` | List positions for the given filters (account, instrument, date range). Computed on demand. |
| GET | `/api/positions/{account}/{instrument}/{entry_execution_id}` | Get one position by its natural key. |
| GET | `/api/integrity-issues` | List unresolved integrity issues. |
| POST | `/api/integrity-issues/{id}/resolve` | Mark resolved. |
| POST | `/api/integrity-issues/{id}/ignore` | Mark ignored. |

## Fragmentation hazards

1. **Adding a `positions` table "for performance."** The cost of full re-computation for typical volumes (a few thousand executions per pair) is single-digit milliseconds. **Rule:** no positions table. If a specific page is slow, add an in-memory cache at the service layer keyed by `(account, instrument, max(execution_time))`. Never persist derived position data.

2. **Multiple competing "position services."** The old codebase had `position_service.py`, `position_engine.py`, `position_algorithms.py`, `enhanced_position_service_v2.py`, three `position_overlap_*` modules, `position_execution_integrity_service.py`, and `reconciliation_service.py` — eight modules with overlapping concerns. **Rule:** one `build_positions` function and one `IntegrityValidator` class. That is the entire surface area for position logic.

3. **Action stored as ambiguous string.** The old schema stored `side_of_market` as a text column holding the raw four-valued action (`Buy`, `Sell`, `BuyToCover`, `SellShort`) and the builder interpreted it inconsistently. **Rule:** at parse time, split into two fields on the execution: `original_action` (string, the raw CSV value, forensic only) and `side` (enum, `Buy` or `Sell`, the only value used for math). The position's `side` enum is `Long` or `Short`, computed by the builder.

4. **Reversals treated inconsistently.** The old builder sometimes interpreted a reversing fill as an error, sometimes silently split it, sometimes dropped data. **Rule:** reversing fills are legitimate (NinjaTrader reversing orders produce them). The builder deterministically splits them into synthetic close + open sub-fills with `#close`/`#open` suffixes. No integrity issue is raised unless the cross-check against the exporter's `Position` column disagrees.

5. **Validation logic in routes.** The old `/positions/api/validation/...` endpoints contained ad-hoc validation logic. **Rule:** all validation lives in `IntegrityValidator`. Routes only read `integrity_issues` and call resolve/ignore.

6. **Stale position IDs leaked outside the function.** If anything outside `services/positions.py` ever takes a position ID and stores it as a foreign key, position identity becomes load-bearing and merge/split from late-arriving executions starts producing orphans. **Rule:** user notes, tags, annotations, and custom fields attach to **execution IDs**, never to positions. If the UI shows position-level annotations, it derives them by joining note→execution→position at read time.

## Deviations from old behavior

- **No `positions` table exists.** The old codebase materialized positions with their own auto-increment IDs and a `position_executions` junction table. Both are gone. Every position-shaped artifact in the old schema — `positions`, `position_executions`, `position_overlap_*`, the "position metadata" tables — is removed.
- **No rebuild lifecycle.** No "rebuild all," no "rebuild scope," no nightly rebuild job. Imports don't trigger rebuilds because there's nothing to rebuild; they trigger a one-shot integrity diff against the stored issues table.
- **No overlap detection.** The old codebase had a separate pass that found positions with overlapping time ranges. Overlaps are structurally impossible here — `build_positions` walks a sorted timeline and emits non-overlapping segments by construction.
- **No manual position editing.** Positions are always derived. If the data is wrong, fix the executions.

## Open questions for the implementer

- **Memoization cache — is it needed?** Build and measure first. If the positions list page renders in under 200ms for a representative history, skip the cache. If it's slow, add a simple dict keyed by `(account, instrument, max_execution_time)` with an LRU bound. Do not add anything more sophisticated without profiling evidence.
- **What exactly happens to an "ignored" integrity issue when the underlying data changes?** Current spec says ignored issues stay ignored until the user explicitly unignores them. Alternative: auto-resolve even ignored issues when the condition no longer holds, on the theory that "ignored" meant "ignored for now." The first is more conservative; pick one and document it in feature 17.
