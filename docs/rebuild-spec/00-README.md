# FuturesTradingLog — Rebuild Specification

This directory is the **complete specification** for rebuilding the FuturesTradingLog application from scratch. It is the first file collection added to the new codebase and serves as the primary briefing for implementation.

## Who this is for

A fresh AI coding session starting with an empty repository. No prior conversation context is assumed. Every concept needed to build the app should be derivable from these documents alone.

## How to read this spec

Read the docs in numerical order. Each document is independently readable but the order matters for building mental model:

| # | Document | Purpose |
|---|----------|---------|
| 00 | README (this file) | Map of the spec and the load-bearing architectural decisions |
| 01 | Mission & Principles | What the app is, and the Six Rules that prevent fragmentation |
| 02 | Glossary | Domain vocabulary — read before any feature doc |
| 03 | Tech Stack | The technology choices and the concurrency model |
| 10 | Import Pipeline | NinjaTrader CSV → stored executions, via tailing reads |
| 11 | Position Building | The pure function that turns executions into positions |
| 12 | Trade & Position Browsing | List/detail UIs, notes, reviewed flags, link groups |
| 13 | Charting | OHLC chart with execution markers on the position detail page |
| 14 | OHLC Data Pipeline | Primary + fallback sources, circuit breakers, graceful degradation |
| 15 | Statistics & Reports | P&L, win rate, performance reports |
| 16 | Settings & Instruments | Multipliers, custom fields, per-source symbol mapping |
| 17 | Import Monitoring | Imports, validation, data health, system health dashboards |
| 90 | Preserved Assets | `ExecutionExporter.cs` and the CSV column contract — immutable |

## Load-bearing architectural decisions

These are the decisions that shape every feature doc. If any of them are reversed, multiple docs need rewriting. Read this section first, then return to it whenever a feature doc seems to be taking an unexpected approach — the answer to "why does doc N say it this way?" is almost always one of these.

1. **Single container, in-process background work.** The runtime is one Flask process containing an APScheduler thread, a watchdog observer thread, a bounded `ThreadPoolExecutor`, and request threads. There is no Celery, no Redis, no message broker. `docker compose ps` shows exactly one service. Full reasoning in doc 03.

2. **Positions are a derived view, not a stored table.** The `executions` table holds one row per NinjaTrader fill, keyed by NT ExecutionId. The `build_positions` function (doc 11) walks sorted executions and emits positions on demand. There is no `positions` table, no numeric position ID, no rebuild lifecycle, no rebuild trigger. Out-of-order imports are trivially safe because every read recomputes from scratch. Position identity is the natural key `(account, instrument, entry_execution_id)`.

3. **Imports are idempotent by construction.** `executions` has `UNIQUE(nt_execution_id, account)` and every insert is `ON CONFLICT DO NOTHING`. The importer tails the exporter's daily CSV file using a byte cursor stored in `import_cursors`, only consuming complete newline-terminated rows. Duplicates are structurally impossible, so there is no file-tracking state, no "did I import this already" check, and no batch concept. Rollback operates on execution IDs. Doc 10.

4. **Session-end archival, not per-tick archival.** CSV files stay in `data/inbox/` for the duration of their trading session. An APScheduler job runs once per day at a configurable exchange-local time (default 18:00 America/Chicago) and moves yesterday's files to `data/archive/` after one final safety-net read. Today's file is never touched. Doc 10.

5. **Primary + fallback OHLC sources with per-source circuit breakers.** yfinance is the primary; Stooq is the fallback. Both zero-auth. The two sources return completely different data formats (pandas DataFrame vs CSV, timezone-aware vs naive, different column names, different symbol conventions), which are normalized to a single `Bar` Pydantic model inside per-source adapters. Nothing outside an adapter ever sees raw source data. Doc 14.

6. **OHLC is isolated from the rest of the app.** When every OHLC source is down, imports still process, positions still compute, P&L still renders, notes still save, and monitoring still works. The chart area shows a delayed-data banner. No request handler anywhere blocks on a fetch. The `bars` table has no foreign keys pointing at it from anywhere else. Doc 14, user-facing in doc 13.

7. **User metadata attaches to execution IDs, never to derived entities.** Notes, reviewed flags, custom field values, and link group memberships all key off `nt_execution_id` (which is stable) or the position natural key (which is deterministic from executions). Late-arriving imports that change position boundaries never orphan user work. Doc 11, doc 12, doc 16.

8. **Pydantic everywhere at type boundaries, SQLite as the only data store.** Every service-to-service contract is a Pydantic model. Every persistent datum lives in the one SQLite database. No Redis, no separate cache layer, no in-memory state that survives restart. The OS page cache on top of SQLite is the hot-data cache. Doc 03.

## How to use this spec when implementing

1. **Read doc 01 first.** The Six Rules are non-negotiable. Every implementation decision must satisfy them. Re-read them whenever you're tempted to take a shortcut.
2. **Build features in dependency order.** 10 → 11 → 14 → 12 → 13 → 15 → 16 → 17. Each feature doc lists its dependencies at the top.
3. **Treat acceptance criteria as tests.** Each feature doc has numbered acceptance criteria. They are the definition of done.
4. **Treat fragmentation hazards as hard rules.** Each feature doc has a "Fragmentation Hazards" section describing specific failure modes from the previous codebase. Do not recreate them.
5. **The CSV column contract in doc 90 is immutable.** `ExecutionExporter.cs` is preserved as-is except for the narrow write-path exceptions listed in doc 90's addendum (shared-read access, explicit flush, `\n` line endings, removal of the "move on open" logic). The new importer consumes its output unchanged.

## What this spec is NOT

- Not a step-by-step implementation plan. That comes after the spec is approved.
- Not a copy of the old code's API. Implementation is free to choose better names, paths, and structures as long as the Six Rules and acceptance criteria are met.
- Not a UI mockup. Visual design is left to the implementer; the spec defines what the UI must let the user do.
- Not a migration guide. The new schema is fresh. If the user wants to preserve historical data from the old database, that is a separate one-off tool, not part of this spec.

## Implementation progress

Implementation is split into **phased plans**, one per spec feature, written and executed in the build order from the table above. Plans live in `docs/superpowers/plans/` and are written with `superpowers:writing-plans` and executed with `superpowers:executing-plans`. The working agreement is **one plan at a time**: write a plan → execute it to green → write the next. Earlier plans teach later plans; writing all nine ahead of code produces drift.

| Plan | Covers | Status |
|---|---|---|
| [00 — Foundation](../superpowers/plans/2026-04-13-00-foundation.md) | Repo skeleton, app factory, `BackgroundServices` (APScheduler + ThreadPoolExecutor + watchdog), SQLite/WAL + migrations, Pydantic `StrictModel`, `compute_session_date`, JSON logging, `/healthz`, Dockerfile, compose | ✅ **Complete** (2026-04-13, 13 commits, 22 tests) |
| [10 — Import Pipeline](../superpowers/plans/2026-04-13-10-import-pipeline.md) | `executions` schema, CSV parser, `ingest_tick`, watchdog handler, `import_runs`/`import_rejects`/`import_cursors`, session archival job, rollback API | ✅ **Complete** (2026-04-13) |
| [11 — Position Building](../superpowers/plans/2026-04-13-11-position-building.md) | `build_positions` pure function, reversal splitter, `IntegrityValidator`, `integrity_issues` diff, hooked into import tick | ✅ **Complete** (2026-04-13) |
| [14 — OHLC Pipeline](../superpowers/plans/2026-04-13-14-ohlc-pipeline.md) | `Bar` model, `OhlcSource` protocol, yfinance + Stooq adapters, circuit breaker, fetcher, gap detection, `bars` table, scheduled refresh jobs, fetch job API | ✅ **Complete** (2026-04-13) |
| 12 — Browsing | `/positions` list and detail, `execution_notes`, `execution_flags`, link groups, JSON APIs, shell templates + vanilla JS | ⏳ **Next** |
| 13 — Charting | `PriceChart.js`, embed in detail page, markers, timeframe selector, fetch-now CTA, delayed-data banner | ⏳ |
| 15 — Statistics | `StatisticsService`, all `/api/stats/*`, `/statistics` and `/reports` pages | ⏳ |
| 16 — Settings & Custom Fields | `instruments.json` registry, `chart_defaults`, `custom_fields` + values, `/settings/*` pages | ⏳ |
| 17 — Monitoring | `/imports`, `/validation`, `/data-health`, `/system/health` pages and APIs | ⏳ |

### What Plan 00 landed

- **Concurrency container.** `BackgroundServices` owns a `BackgroundScheduler`, a bounded `ThreadPoolExecutor(max_workers=4)`, and a `watchdog.Observer`. `start()`/`stop()` are idempotent; the app factory returns `(Flask, BackgroundServices)` per doc 03.
- **SQLite layer.** `db.connect(path)` opens WAL + `foreign_keys=ON` + `synchronous=NORMAL` + `busy_timeout=5000`, one connection per thread. `migrations.run_migrations(conn, dir)` applies `migrations/*.sql` in lexicographic order inside an atomic `BEGIN;…;COMMIT;` script, recorded in `schema_migrations`.
- **Typed contracts.** `models.base.StrictModel` is the Pydantic v2 base every typed contract uses (`extra="forbid"`, `strict=True`).
- **Session math.** `services.time_utils.compute_session_date(ts_utc) -> date` implements the 16:00 America/Chicago rollover; tested across DST transitions. Features 10, 15, 17 import it.
- **Healthz.** `GET /healthz` returns 200 when SQLite reads succeed, the scheduler is running, the watchdog observer is alive, and the thread pool is not saturated; 503 otherwise. This is wired into the Docker healthcheck.
- **One container.** `docker compose up -d` brings up exactly one service (`futurestradinglog`) that reaches `Up (healthy)` inside ~20s. `docker compose ps` shows one row — the invariant from doc 03 holds.

### What Plan 10 landed

- **Executions table.** `migrations/002_executions.sql` ships `executions`, `import_cursors`, `import_runs`, `import_rejects`. Composite PK `(nt_execution_id, account)` plus `UNIQUE INDEX idx_executions_nt_execution_id` gives plan 12/16 user-metadata tables a clean single-column FK target.
- **CSV parser.** `services/csv_parser.parse_execution_row` consumes the 15-column format from doc 90, normalizes Action → Side (`Buy`/`BuyToCover` → `Buy`; `Sell`/`SellShort` → `Sell`), and raises `ParseError` per row with a reason suitable for `import_rejects.reason`.
- **ImportPipeline.** `services/import_pipeline.ImportPipeline` owns `ingest_tick(path)`, `scan_inbox(dir)`, `archive_completed_sessions(...)`, and `rollback(ids)`. A per-path `threading.Lock` registry serializes ticks on one file while leaving different files parallel. The tick transaction contains only cursor/executions/rejects/import_runs writes; integrity diff and OHLC fetch are post-tick hooks that plans 11 and 14 will register.
- **Watchdog handler.** `services/import_watchdog.TickHandler` replaces the Plan 00 `_NoopHandler`. `BackgroundServices.start(handler=…)` now accepts an injected handler and still defaults to `_NoopHandler` for the foundation tests.
- **Scheduled jobs.** The app factory registers two jobs on the existing APScheduler: a 5-minute safety sweep that calls `scan_inbox`, and a daily archival job at `config.session.archive_job_time` that moves yesterday's files to `data/archive/YYYY-MM-DD/` after one final safety-net tick.
- **API surface.** `/api/imports/runs`, `/api/imports/runs/{id}`, `/api/imports/cursors`, `/api/imports/rejects`, `POST /api/imports/scan`, `POST /api/executions/rollback`.
- **End-to-end verified in Docker.** Dropping a valid CSV into the container's inbox volume causes a row to appear in `executions` within ~1 second without any manual action; `/api/imports/runs` reflects the tick.
- **No batches, no file tracking, no upload endpoint.** Per doc 10 fragmentation hazards 1–8.

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

### What Plan 00 deliberately did NOT land

These belong to later plans:

- No `executions`, `bars`, `import_runs`, `integrity_issues`, or any feature-specific table — only `schema_migrations`.
- No real watchdog handler — `_NoopHandler` is a placeholder that plan 10 will replace.
- No `instruments.json` — plan 16's surface. Plans 10/11/14 may stub a constants module until then.
- No static JS, no templates beyond `base.html`, no business logic, no routes beyond `/healthz`.

## Status

This spec describes a 1:1 feature-parity rebuild of the existing application, with **cohesion** as the primary non-functional goal. It is meant to be fine-tuned by the project owner before implementation begins.

The current revision incorporates the major architectural decisions listed above. These changes are reflected consistently across every feature doc. If a feature doc appears to contradict a decision in this README, the feature doc is wrong and should be corrected — the README is the canonical summary.
