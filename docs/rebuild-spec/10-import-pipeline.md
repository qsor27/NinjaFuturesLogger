# Feature 10 — Import Pipeline

## Purpose

Detect new NinjaTrader execution rows written by `ExecutionExporter.cs`, parse them into stored executions, and make them available to every downstream feature. This is the single entry point for all data in the system.

The pipeline is designed around two properties that together eliminate the entire class of "import bugs" the previous codebase suffered from:

1. **Idempotency by construction.** NinjaTrader's `ExecutionId` is the natural primary key. Re-processing the same row (from the same file, a re-drop, a restart, overlapping snapshots, or a late-arriving fill) is always a no-op because the `UNIQUE` constraint rejects it at insert time. Nothing in the pipeline tracks "did I import this file already" because the question is irrelevant.
2. **Tailing instead of file-at-a-time.** The exporter holds the daily CSV open for the entire trading session and appends as fills arrive. The importer reads from a per-file byte cursor, consumes only up through the last complete newline, and advances the cursor. The file never has a "done" state during the session; it just keeps growing, and the importer keeps catching up.

## Dependencies

- **Doc 90** — The CSV format produced by `ExecutionExporter.cs` is the immutable input contract. Read it before reading this doc. (The column schema is immutable; write-path changes to the exporter are permitted — see doc 90 addendum.)
- **Feature 11** — Positions are derived on demand from executions. The importer does not trigger rebuilds (there is nothing to rebuild). It does run one integrity-diff pass per affected `(account, instrument)` after insert.
- **Feature 14** — After an import, the thread pool is given one fire-and-forget fetch per affected `(instrument, timeframe)` so the chart is ready when the user opens the position. The import pipeline does not wait for these.
- **Feature 17** — Every import tick writes to `import_runs` for the monitoring dashboard.

## User stories

1. **As the trader**, once I drop a new `NinjaTrader_Executions_YYYYMMDD.csv` file into the watched folder — or once NinjaTrader starts writing today's file — new rows become visible in the app within seconds, without any clicking.
2. **As the trader**, re-dropping the same file, restarting NinjaTrader, or having overlapping daily exports produces zero duplicate rows. The question "did I import this already?" never needs to be answered because duplicates are impossible.
3. **As the trader**, mid-session imports are fine. Partial data in the file just means fewer rows — the next read picks up the rest. I never see half-parsed rows or truncated trades.
4. **As the trader**, when an import hits a malformed row, that row goes into a rejects log with enough context to debug, and the rest of the file continues to import.
5. **As the trader**, I can see every import tick in the monitoring dashboard: which file, how many rows were read, how many were new, how many were skipped as duplicates, how many were rejected, how long it took.
6. **As the trader**, files from completed sessions eventually move to an archive directory — but **only after the session that produced them is definitively over**, not after each read.
7. **As the trader**, if I realize I imported something I shouldn't have, I can roll back individual executions by `ExecutionId` from the monitoring UI. Rollback does not depend on "which file did this row come from."

## Acceptance criteria

1. The `executions` table has `UNIQUE(nt_execution_id, account)` as a hard constraint. Every insert uses `INSERT ... ON CONFLICT DO NOTHING`. The pipeline never asks the DB "does this row already exist" before inserting — the constraint is the check.
2. A `watchdog` observer thread (doc 03) watches `data/inbox/` for `on_created` and `on_modified` events on `NinjaTrader_Executions_*.csv` files. Each event triggers an `ingest_tick` call for the affected path.
3. An `ingest_tick(path)` call acquires a per-path lock, opens the file read-only with shared-read access, seeks to the cursor stored in `import_cursors`, reads until the last `\n`, parses the new lines, inserts the rows, advances the cursor, and commits. All in one transaction.
4. The importer **only processes complete lines.** Any trailing partial line (bytes after the last `\n`) is ignored on the current tick and picked up on the next tick after the exporter flushes more data.
5. Each tick writes an `import_runs` row with: `tick_id`, `filename`, `started_at`, `finished_at`, `cursor_before`, `cursor_after`, `lines_read`, `rows_parsed`, `rows_inserted`, `rows_skipped_duplicate`, `rows_rejected`, `status` (`ok` | `partial` | `failed`), `error` (nullable).
6. Rejected rows (parse errors, type errors, out-of-range values) are written to `import_rejects` with: `tick_id`, `line_number`, `raw_line`, `reason`. They are **not retried** automatically — a rejected row is a data bug that needs human review, not a transient fault. Feature 17 surfaces the count.
7. After inserting new rows, the importer runs `build_positions` (doc 11) for each affected `(account, instrument)`, diffs the resulting `IntegrityIssue` list against the stored `integrity_issues` table, inserts new issues, and auto-resolves issues no longer present (with `resolved_by = 'system'`). Explicitly-ignored issues are untouched.
8. After the integrity diff, the importer submits one `fetch_range` task per affected `(instrument, timeframe)` to the thread pool (doc 14). These are fire-and-forget; the importer does not wait.
9. An APScheduler job runs daily at configurable local exchange time (default **18:00 America/Chicago** for CME futures) and archives any file in `data/inbox/` whose filename-date is strictly less than the current session's trade date. The job takes one final `ingest_tick` on the file as its last step before moving it, to guarantee no late writes are orphaned. Archived files move to `data/archive/YYYY-MM-DD/`. The `import_cursors` row for the archived file is deleted.
10. Manual "scan now" from the UI does nothing more than call `ingest_tick` on every matching file in `data/inbox/`. It does not bypass the cursor or re-read archived files.
11. Rollback operates on `ExecutionId`, not on files. `POST /api/executions/rollback` with a list of execution IDs deletes those rows from `executions` and runs the integrity diff for affected `(account, instrument)` pairs. The file archive is untouched.

## Data model additions

```sql
CREATE TABLE import_cursors (
  filename        TEXT PRIMARY KEY,  -- basename only, e.g. 'NinjaTrader_Executions_20260413.csv'
  byte_offset     INTEGER NOT NULL,
  last_tick_at    INTEGER NOT NULL,
  last_modified   INTEGER NOT NULL   -- file mtime from the last tick, for diagnostics
);

CREATE TABLE import_runs (
  tick_id               INTEGER PRIMARY KEY AUTOINCREMENT,
  filename              TEXT NOT NULL,
  started_at            INTEGER NOT NULL,
  finished_at           INTEGER NOT NULL,
  cursor_before         INTEGER NOT NULL,
  cursor_after          INTEGER NOT NULL,
  lines_read            INTEGER NOT NULL,
  rows_parsed           INTEGER NOT NULL,
  rows_inserted         INTEGER NOT NULL,
  rows_skipped_duplicate INTEGER NOT NULL,
  rows_rejected         INTEGER NOT NULL,
  status                TEXT NOT NULL CHECK(status IN ('ok','partial','failed')),
  error                 TEXT
);
CREATE INDEX idx_import_runs_filename_started ON import_runs(filename, started_at DESC);

CREATE TABLE import_rejects (
  reject_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  tick_id      INTEGER NOT NULL REFERENCES import_runs(tick_id),
  line_number  INTEGER NOT NULL,
  raw_line     TEXT NOT NULL,
  reason       TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);
```

And the `executions` table itself — the central store of raw fills that everything else derives from:

```sql
CREATE TABLE executions (
  nt_execution_id     TEXT NOT NULL,                                       -- NinjaTrader Execution.ExecutionId
  account             TEXT NOT NULL,                                       -- NinjaTrader Account.Name
  instrument          TEXT NOT NULL,                                       -- verbatim from CSV, e.g. 'MNQ SEP25'
  timestamp           INTEGER NOT NULL,                                    -- unix seconds, UTC
  side                TEXT NOT NULL CHECK(side IN ('Buy','Sell')),         -- normalized 2-value enum
  original_action     TEXT NOT NULL,                                       -- raw CSV Action: Buy|Sell|BuyToCover|SellShort
  quantity            INTEGER NOT NULL CHECK(quantity > 0),
  price               REAL NOT NULL,
  commission          REAL NOT NULL DEFAULT 0,
  entry_exit          TEXT NOT NULL CHECK(entry_exit IN ('Entry','Exit')), -- from CSV E/X column
  position_after      TEXT,                                                -- verbatim CSV Position column: '3 L','2 S','-'
  source_order_id     TEXT,                                                -- NinjaTrader Order.OrderId, forensic
  source_filename     TEXT NOT NULL,                                       -- filename this row was read from
  imported_at         INTEGER NOT NULL,                                    -- unix seconds, when this row hit the DB
  PRIMARY KEY (nt_execution_id, account)
);

-- nt_execution_id must be globally unique on its own so that user-metadata
-- tables (execution_notes, execution_flags, execution_custom_field_values)
-- can foreign-key to it without having to carry `account`. The composite
-- PRIMARY KEY above is still the idempotency guarantee for imports; this
-- UNIQUE index is the stronger identity guarantee that downstream FKs rely on.
CREATE UNIQUE INDEX idx_executions_nt_execution_id ON executions(nt_execution_id);

CREATE INDEX idx_executions_account_instrument_time
  ON executions(account, instrument, timestamp);
CREATE INDEX idx_executions_timestamp
  ON executions(timestamp);
```

Notes on the schema:

- **Composite primary key `(nt_execution_id, account)`** is the idempotency guarantee. Every insert is `ON CONFLICT DO NOTHING`. The `account` component is defensive: in principle NT execution IDs are globally unique, but keying by `(execution_id, account)` protects against cross-account ID collisions if a user imports data from multiple NT installations.
- **`UNIQUE INDEX idx_executions_nt_execution_id`** promotes `nt_execution_id` to a standalone unique column so that user-metadata tables (notes, flags, custom field values — see docs 12 and 16) can foreign-key it directly without dragging `account` through every relation. In the rare cross-NT-installation ID-collision scenario, the import would be blocked by this unique index before the composite PK was reached; that is the correct behavior — the operator needs to see the collision rather than silently split ownership across two rows.
- **No surrogate `id` column.** The composite key is the identifier everywhere — in foreign keys from `execution_notes`, `execution_flags`, `execution_custom_field_values`, and `integrity_issues`, and in position-builder output. Rule 1 forbids auto-increment IDs on entities that already have a natural key.
- **`side` is the normalized math value; `original_action` preserves the raw CSV string for forensic display.** The builder and every downstream calculation read `side`; UI that wants to show "BuyToCover" reads `original_action`. See doc 02 glossary.
- **`position_after` is preserved verbatim.** The builder cross-checks its own running quantity against this column to produce integrity issues (doc 11). It is never parsed for math — it is a string for comparison only.
- **`source_filename` and `imported_at` are forensic.** They are not the source of truth for reconciliation (that's `import_runs`), but they make ad-hoc queries like "which file did this execution come from" cheap.

## Tick algorithm

```python
def ingest_tick(path: Path) -> TickResult:
    with per_path_lock(path):
        cursor = load_cursor(path.name) or 0
        size = path.stat().st_size

        if size < cursor:
            # File shrank — exporter rewrote or truncated.
            # Reset cursor to 0; duplicates are harmless because of UNIQUE.
            log.warning("file shrank, resetting cursor", path=path.name, old=cursor, new=size)
            cursor = 0

        if size == cursor:
            return TickResult(status="ok", lines_read=0)

        with open(path, "rb") as f:
            f.seek(cursor)
            chunk = f.read(size - cursor)

        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            # No complete line yet; wait for more.
            return TickResult(status="partial", lines_read=0)

        complete = chunk[: last_newline + 1]
        new_cursor = cursor + len(complete)
        lines = complete.decode("utf-8").splitlines()

        # Drop the CSV header if this is the first tick on this file.
        if cursor == 0 and lines and lines[0].startswith("Instrument"):
            lines = lines[1:]

        parsed: list[Execution] = []
        rejects: list[RejectRecord] = []
        for i, line in enumerate(lines):
            try:
                parsed.append(parse_execution_row(line))
            except ParseError as e:
                rejects.append(RejectRecord(line_number=i, raw_line=line, reason=str(e)))

        with db.transaction():
            tick_id = db.insert_import_run_start(filename=path.name, cursor_before=cursor)
            inserted, skipped = db.bulk_insert_executions_ignore_conflict(parsed)
            db.insert_rejects(tick_id, rejects)
            db.save_cursor(path.name, new_cursor, file_mtime=int(path.stat().st_mtime))
            db.insert_import_run_finish(
                tick_id,
                cursor_after=new_cursor,
                lines_read=len(lines),
                rows_parsed=len(parsed),
                rows_inserted=inserted,
                rows_skipped_duplicate=skipped,
                rows_rejected=len(rejects),
                status="ok",
            )

    # Outside the DB transaction and the per-path lock:
    affected = {(e.account, e.instrument) for e in parsed}
    for account, instrument in affected:
        run_integrity_diff(account, instrument)       # doc 11
        submit_ohlc_fetch_for_executions(instrument, parsed)  # doc 14

    return TickResult(status="ok", ...)
```

A few points on this that aren't obvious from the code:

- **The per-path lock** prevents two `on_modified` events firing in rapid succession from racing each other on the same file. Watchdog is event-per-change on Windows and can fire many times per second during an active import. The lock serializes ticks per file; different files can still be ticked in parallel, but that's rare in practice (one active file per session).
- **File shrinkage is handled.** If the exporter truncates (unusual — normally it appends only) the cursor resets. `UNIQUE` absorbs the duplicates.
- **The header row is dropped only on the first tick of a file** (when cursor was 0). Subsequent ticks never see the header because the cursor is past it.
- **Integrity diff and OHLC fetch are scheduled *after* the transaction commits and *after* the path lock releases.** They must not hold the DB transaction open or block other ticks. They run in the background thread pool (doc 03).
- **There is no "file is done" signal from the tick path.** The file is only "done" when the session-end archiver looks at it (see below).

## Session-end archival

This is the *only* place in the pipeline that uses wall-clock time for anything. Every other decision is driven by file contents and byte offsets.

APScheduler job (doc 03), runs daily at the configured exchange-local time:

```python
def archive_completed_sessions():
    now = datetime.now(config.exchange_tz)
    current_trade_date = resolve_current_trade_date(now)  # e.g., CME: 17:00 local rollover

    for path in Path("data/inbox").glob("NinjaTrader_Executions_*.csv"):
        file_date = parse_date_from_filename(path.name)
        if file_date is None:
            continue  # unknown filename pattern; leave alone
        if file_date >= current_trade_date:
            continue  # today's file; still active, leave alone

        # Final catch-up read in case a late modification slipped past watchdog.
        ingest_tick(path)

        dest_dir = Path("data/archive") / file_date.isoformat()
        dest_dir.mkdir(parents=True, exist_ok=True)
        path.rename(dest_dir / path.name)

        with db.transaction():
            db.delete_import_cursor(path.name)
```

Rules:

- **Only files with a strictly earlier trade date than the current one are eligible.** Today's file is never touched.
- **The final `ingest_tick` is the safety net.** If watchdog missed an event at end-of-session, this catches it before archival makes further reads impossible.
- **The cursor row is deleted as part of archival.** If the file is ever re-dropped into inbox later (disaster recovery), it re-imports from scratch; duplicates are absorbed by `UNIQUE`.
- **The exchange timezone and rollover time are configurable.** Default is `America/Chicago` with `17:00` close, matching CME equity index futures. A trader using other markets edits config.

## Configuration

```json
{
  "inbox_dir": "data/inbox",
  "archive_dir": "data/archive",
  "session": {
    "exchange_timezone": "America/Chicago",
    "trade_date_rollover": "17:00",
    "archive_job_time": "18:00"
  }
}
```

`archive_job_time` is slightly after `trade_date_rollover` so the new session has definitely started before we touch yesterday's file.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/imports/runs` | Paginated list of import ticks (newest first). Feature 17 consumes this. |
| GET | `/api/imports/runs/{tick_id}` | One tick, full detail including rejects. |
| GET | `/api/imports/cursors` | Current cursor state for every file in inbox. For diagnostics. |
| POST | `/api/imports/scan` | Manually trigger `ingest_tick` for every file in inbox. Idempotent. |
| GET | `/api/imports/rejects` | Paginated list of rejected rows, filterable by filename/date. |
| POST | `/api/executions/rollback` | Body: `{ execution_ids: [...] }`. Deletes those rows; runs integrity diff for affected pairs. |

Note: there are no `/api/imports/batch/*` endpoints because there are no batches. The unit of work is a tick, and ticks are cheap and frequent, not heavyweight "import jobs."

## Fragmentation hazards

1. **Multiple "import services" with overlapping responsibilities.** The old codebase had `import_service.py`, `ninjatrader_import_service.py`, `unified_csv_import_service.py`, `csv_watcher_service.py`, `file_watcher.py`, and `daily_import_scheduler.py` — six modules for one feature, with unclear hierarchy and partial duplication. **Rule:** one `ImportPipeline` module exposing `ingest_tick(path)` and `archive_completed_sessions()`. The watchdog observer is a 20-line wrapper that calls `ingest_tick`. The APScheduler job is a 5-line wrapper that calls `archive_completed_sessions`. Neither wrapper contains logic.

2. **Thinking in files instead of executions.** The old codebase tracked "which files have been imported" via filename lists, hash comparisons, processed-file directories, and a polling loop that asked "is this file new?" Every one of these was a bug source. **Rule:** files are not the unit of truth. Executions are. The importer tracks a byte cursor per file (for read efficiency only) and lets `UNIQUE(nt_execution_id, account)` handle deduplication. If any code outside `ingest_tick` asks "have I processed this file before?", it's wrong.

3. **Archiving per-file on success.** The old codebase moved files to an `exported` directory immediately after a successful read. Combined with mid-session reads, this moved files out from under the exporter and caused sharing violations. **Rule:** archival is time-based, triggered by session rollover, not event-based. Today's file stays in inbox until tomorrow's rollover time.

4. **Format auto-detection.** The old codebase tried to detect "is this NinjaTrader format or TradeLog format?" and had branching logic for both. **Rule:** if a file doesn't match `NinjaTrader_Executions_*.csv` with the column schema in doc 90, the parser raises per-row reject errors and those rows go into `import_rejects`. No format guessing, no second parser.

5. **Business logic in route handlers.** The old `routes/main.py` contained ~65 lines of CSV processing inline. **Rule:** routes call `ImportPipeline.ingest_tick(file)` or read from `import_runs`. Period.

6. **Silent duplicate handling.** The old code used `INSERT OR IGNORE` without surfacing the skipped-duplicate count. **Rule:** the tick result separates `rows_inserted` from `rows_skipped_duplicate`. Duplicates are normal (expected every tick, in fact, since overlapping reads re-present already-inserted rows), but they must be *counted* so anomalies are visible.

7. **Waiting for "downstream completion" before returning from the tick.** The old pipeline would sometimes wait for position rebuilds and OHLC fetches inside the import transaction, making ticks minutes long and blocking subsequent ticks. **Rule:** the tick transaction contains only the cursor update, the execution inserts, the rejects, and the `import_runs` rows. Integrity diff and OHLC fetch are submitted to the thread pool *after* the transaction commits.

8. **Web-upload as a parallel ingestion path.** The old code had `csv_management.py` with `POST /upload` that bypassed the watcher entirely and had its own partial copy of the import logic. **Rule:** the only way to get data into the system is to write a file into `data/inbox/`. If the user wants to add a file from elsewhere, they `cp` it into inbox. Manual "scan" re-runs `ingest_tick` over inbox — no upload endpoint, no parallel code path.

## Deviations from old behavior

- **No batch concept.** The old model had "import batches" with a lifecycle (`in_progress`, `succeeded`, `failed`, `rolled_back`) and a 1-to-many relationship from batch to executions. The new model has `import_runs` which are per-tick audit records, and rollback operates on execution IDs directly. A single file now has many ticks (one per watchdog event) rather than one batch.
- **No per-file archival on success.** Files only move to archive at session end (next day's rollover time) after a final safety-net tick.
- **No rebuild triggering.** Positions are derived (doc 11). The importer does one integrity diff per affected `(account, instrument)` after a successful tick, and that's the only "downstream work" it does synchronously.
- **Web upload is removed.** Inbox is the only ingestion path.
- **Daily-import-scheduler is removed.** There is no "import at 8am" job. Watchdog + scheduled safety sweeps (every N minutes, calling `ingest_tick` on today's file in case watchdog missed an event) cover continuous ingestion.

## Open questions for the implementer

- **Safety-sweep cadence.** Should there be a "call `ingest_tick` on today's file every 5 minutes just in case watchdog missed something" APScheduler job, or is watchdog alone reliable enough? Watchdog on Windows has historical reliability issues with `on_modified` firing for append-mode writes; a belt-and-suspenders sweep every 5 minutes is cheap and removes the concern. Recommendation: yes, add it.
- **Cursor reset tool.** Operational need: "re-read a file from scratch." The answer is `DELETE FROM import_cursors WHERE filename=?` followed by a manual scan — or a `POST /api/imports/cursors/{filename}/reset` endpoint. Either is fine; pick one and document it in feature 17.
- **Cross-NT-installation execution ID collisions.** In practice NT ExecutionIds are globally unique strings, but if a user runs two separate NT installations feeding the same inbox, collisions are theoretically possible. The `(nt_execution_id, account)` composite key in the UNIQUE index defends against this, but only if the `account` column is populated accurately. Reconfirm in the exporter that `Account.Name` is what goes into the CSV.
