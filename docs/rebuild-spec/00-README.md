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
| [12 — Browsing](../superpowers/plans/2026-04-13-12-browsing.md) | `/positions` list and detail, `execution_notes`, `execution_flags`, link groups, JSON APIs, shell templates + vanilla JS | ✅ **Complete** (2026-04-13) |
| [13 — Charting](../superpowers/plans/2026-04-13-13-charting.md) | `PriceChart.js`, embed in detail page, markers, timeframe selector, fetch-now CTA, delayed-data banner | ✅ **Complete** (2026-04-13, browser AC walkthrough pending) |
| [15 — Statistics](../superpowers/plans/2026-04-13-15-statistics.md) | `StatisticsService`, all `/api/stats/*`, `/statistics` and `/reports` pages | ✅ **Complete** (2026-04-13, 16 commits, 451 tests, browser AC walkthrough pending) |
| [16 — Settings & Custom Fields](../superpowers/plans/2026-04-13-16-settings-instruments.md) | `instruments.json` registry, `chart_defaults`, `custom_fields` + values, `/settings/*` pages | ✅ **Complete** (2026-04-14, ~14 tasks, 557 tests) |
| [17 — Monitoring](../superpowers/plans/2026-04-14-17-import-monitoring.md) | `/imports`, `/validation`, `/data-health`, `/system/health` pages and APIs | ✅ **Complete** (2026-04-14) |

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

### What Plan 12 landed

- **Migration 005.** Ships `execution_notes`, `execution_flags`, `link_groups`, and `position_links`. Notes and flags FK cascade on `executions(nt_execution_id)` via plan 10's unique index — rollback cleans them up automatically. `position_links` uses the natural three-column position key and CASCADEs on its parent `link_groups`.
- **Typed models.** `models/browsing.py` adds `LinkGroup`, `LinkGroupDetail`, `LinkMember`, `Outcome` (`winner`/`loser`/`scratch`/`open`), `PageMeta` (with derived `total_pages`/`has_next`/`has_prev`), and `PositionListPage`. All `StrictModel` subclasses, exported from `models/__init__.py`.
- **Notes and flags services.** `services/notes.py` and `services/flags.py` own the SQL for their tables. Both strip `#close`/`#open` suffixes from incoming execution IDs via `notes.strip_split_suffix` — synthesized reversal sub-fills inherit their parent's metadata and never get their own rows.
- **Outcome classifier.** `services/outcomes.py::classify_outcome` implements doc 15's Winner/Loser/Scratch definitions verbatim and also handles the open-position case. Plan 15's statistics will reuse this helper.
- **Pure filter+paginate helpers.** `services/position_filters.py::apply_filters` and `paginate` are pure functions on `list[Position]` — no DB access, no mutation. Filters compose with AND.
- **Positions service extensions.** `services/positions_service.py` adds `list_positions_page` (load → build → sort newest-first → filter → paginate), `get_filter_options` (SELECT DISTINCT over `executions`), and `attach_metadata` (position + notes + reviewed + empty `custom_fields` for plan 16).
- **Links service.** `services/links.py` ships `create_group` / `get_group` / `list_groups` / `rename_group` / `add_members` / `remove_member` / `delete_group`, with validation that members are non-empty and unique per group.
- **API surface.** Extended `/api/positions` now returns the `{positions, page}` envelope and supports `account`, `instrument`, `side`, `outcome`, `entry_time_min`, `entry_time_max`, `page`, `page_size` query params. New endpoints: `GET /api/positions/filters`, `GET /api/positions/{account}/{instrument}/{eid}/executions`, `PATCH /api/executions/{id}/note`, `PATCH /api/executions/{id}/reviewed`, `POST/GET/PATCH/DELETE /api/links` family, `GET /api/links/{id}`. The detail endpoint now returns `{position, notes, reviewed, custom_fields}`.
- **Shell pages + static JS.** Three server-rendered shell templates (`positions_list.html`, `position_detail.html`, `link_group.html`) extending a revamped `base.html` with minimal CSS. Vanilla ES-module JS in `static/js/` (`api.js`, `positions_list.js`, `position_detail.js`, `link_group.js`) reads `data-*` attributes, calls the JSON API, and renders with `textContent` for user strings. No bundler, no framework, no inline script logic in templates — Rule 5 holds.
- **Deletion via rollback.** The detail page's delete button collects the un-suffixed execution IDs from `Position.execution_ids` and calls `POST /api/executions/rollback` from plan 10. Cascade on `execution_notes` and `execution_flags` cleans up automatically. There is no separate delete endpoint.
- **End-to-end verified in Docker.** Dropping a CSV into the inbox causes positions to appear in `/positions`, filter correctly by winner/loser/outcome, drill into the detail page with notes and reviewed flag editing, and delete via rollback.
- **No numeric position IDs, no positions table, no rebuild lifecycle.** Per Rule 1.

### What Plan 13 landed

- **Two new read-only GET routes.** `/api/chart/{instrument}/timeframes-available` (returns canonical-order counts per timeframe plus the configured default) and `/api/positions/{account}/{instrument}/{entry_execution_id}/markers` (returns one marker per real execution row in the position, suffix-stripped, natural-key path). Both routes are read-only — neither calls `fetch_range`. Plan 13 load-bearing rule 2.
- **`services/chart_defaults.py` Plan 16 seam.** Module-level constants `DEFAULT_TIMEFRAME = "1m"` and `VOLUME_VISIBLE_DEFAULT = True` plus `get_defaults()` returning a fresh dict on each call. Plan 16 will replace the body of `get_defaults()` with a `chart_defaults` table SELECT without touching callers.
- **`services/markers.py::build_markers`.** Pure function: `list[Execution] -> list[Marker]`, one Marker per execution, input order preserved. No DB, no mutation, no sort, no filter, no suffix handling — the route is responsible for passing only deduped real rows.
- **`Marker` Pydantic StrictModel.** Five fields (`time`, `price`, `side`, `quantity`, `label`) with `Side = Literal["Buy", "Sell"]`. Exported from `models/__init__.py`. The label is the un-suffixed `nt_execution_id` so the chart-arrow ↔ table-row link can match by label.
- **Vendored TradingView Lightweight Charts v4.2.3.** `static/vendor/lightweight-charts.standalone.production.js` (163,684 bytes, SHA-256 `c7dda807d662a95b3d257119ed315cec669e3bdf5aaece75c480a39307f23540`). The only third-party JavaScript in the entire codebase. Loaded as a plain `<script src>` from `templates/position_detail.html`; no bundler, no Node, no `package.json`, no CDN at runtime, no new entries in `requirements.txt`. Pinned at v4 because v4 still exposes `addCandlestickSeries()` / `addHistogramSeries()` directly; v5 collapses both into a single `addSeries(...)` factory and would require code changes.
- **`static/js/PriceChart.js` — the one chart implementation.** Pure helpers at the top (`timeframeSeconds`, `computeFetchRange`, `computeVisibleRange`, `pickInitialTimeframe`, `buildMarkersFromApi`, `buildPriceLines`, `summarizeFetchResult`, `nextPollDelay`, `formatOhlcOverlay` — all DOM-/fetch-/library-free), then constants, then one `PriceChart` class that owns the lightweight-charts instance, controls header, ResizeObserver, AbortController, fetch-job poller, no-data CTA, delayed-data banner, loading indicator, error+retry UI, and the document-level custom-event bus. ~700 lines, single file, single class. `find static/ -name '*chart*' -o -name '*Chart*' | grep -i js | grep -v vendor` lists only `PriceChart.js`. AC 22 holds.
- **Two custom events for arrow ↔ table linking.** `executions-table:row-clicked` (dispatched by `position_detail.js` when a `<tr>` is clicked → `PriceChart` re-centers the visible range and gold-flashes the matching marker for ~2s) and `chart:execution-clicked` (dispatched by `PriceChart` when the canvas is clicked near a marker → `position_detail.js` scrolls the matching row into view and highlights it). Both keyed by un-suffixed `nt_execution_id`.
- **Polling parameters.** `POLL_INTERVAL_MS = 2000`, `POLL_TIMEOUT_MS = 120000` (60 polls max). Adopted from doc 14's recommended values.
- **`tests/test_app_factory_plan13.py` smoke test.** Spins up `create_app(...)` and asserts both new routes are wired, `/static/vendor/lightweight-charts.standalone.production.js` is served and contains `LightweightCharts`, and `/static/js/PriceChart.js` is served and contains `export class PriceChart`.
- **377 backend tests pass.** 22 new tests (Tasks 1, 2, 3, 4, 5, 10) on top of Plans 00/10/11/12/14. Ruff `check` and `format --check` both clean.

### What Plan 15 landed

- **One `StatisticsService`, no SQL in routes.** `services/statistics.py::StatisticsService` owns every database read for stats. Routes in `routes/stats.py` parse the query string into a `StatsFilter` (`account?`, `from?`, `to?`), call one service method, and `jsonify(result.model_dump())`. Doc 15 hazard 1 enforced structurally.
- **Pure aggregation helpers.** `services/statistics_aggregations.py` holds `compute_summary`, `bucket_by_session_date` (day/week/month with continuous fill — empty buckets in the requested range are zero-filled), `bucket_by_hour` (24 always-continuous buckets in the configured display timezone), `cumulative_equity` (one point per closed position, ordered by `exit_time`), `pnl_histogram` (10 evenly-spaced buckets between min..max with a degenerate fallback for single-value input), `split_by_side`, `per_instrument`, and `_longest_streaks`. Every helper is pure: takes data, returns data, no I/O, no globals, no clock. 28 unit tests cover empty input, single value, mixed, alternating/run streaks, scratch skip, exit-time ordering, hold-time median odd/even, ISO week/month formatting, session-date rollover, and Tokyo vs Chicago hour bucketing.
- **Three-bucket loader.** `_load_closed_positions(filter)` returns `(closed_with_pnl, closed_missing_multiplier, open)`. All aggregations operate on `closed_with_pnl`; the summary endpoint reports `open_positions` and `skipped_no_multiplier` so the dashboard can warn about misconfigured instruments. The middle bucket is currently always empty (the `get_multiplier` stub returns `1.0` for unknown symbols) but exists for forward-compat with Plan 16's registry.
- **Canonical win-rate.** `wins / (wins + losses)`, scratches excluded, returns `None` when both are zero. Defined exactly once in `compute_summary`. `_side_stats` and `per_instrument` both delegate to it — doc 15 hazard 5 enforced.
- **Session-date bucketing everywhere.** `_session_date_of(p)` wraps `compute_session_date(datetime.fromtimestamp(p.entry_time, tz=UTC))` and is the only date-bucketing primitive. The 16:00 America/Chicago rollover is verified by tests (a position at 21:30 UTC = 16:30 CDT lands in the next day's session). Doc 15 hazard 2 enforced.
- **`display_timezone` Config field.** `config.py` adds `display_timezone: str | None = None`. `StatisticsService.by_hour(filter)` reads `config.display_timezone or config.session.exchange_timezone` so a Tokyo-based trader trading CME can separate the rollover timezone from the display timezone. Plan 16 will expose this in the settings UI.
- **Nine `/api/stats/*` GET endpoints.** `summary`, `by-instrument`, `by-day`, `by-week`, `by-month`, `by-hour`, `by-side`, `equity-curve`, `distribution`. All accept the same three optional query params; all return Pydantic StrictModel responses (`model_dump()`d to JSON). Invalid date strings → 400 with `{"error": "..."}`. Unknown account → 200 with empty results, not an error.
- **Calendar cell click → `/positions?session_date=YYYY-MM-DD`.** Plan 12's `PositionFilter` gained an additive `session_date: date | None` field and `routes/positions.py::_parse_filter_from_query` now parses `session_date` from the query string. The predicate compares `compute_session_date(...)` to the filter value, so reversal trades opened after 16:00 Chicago time correctly land on the *next* session date. Decision 6 / Option B from the design spec — keeps the rollover rule in `services/time_utils.py` instead of reimplementing it in JS.
- **Two pages, one shared filter bar.** `/statistics` is the at-a-glance bento dashboard (summary, side, equity, instrument table, by-day, by-hour); `/reports` is the deep-dive (calendar heatmap, larger equity curve, by-week, by-month, distribution). Both server-rendered shell templates extending Plan 12's `base.html`, both load the existing Plan 13 vendored TradingView Lightweight Charts via plain `<script src>`, both bootstrap a single ES module that reads URL filter state, fetches its endpoints in parallel via `Promise.all`, and renders sections with `textContent` (no frontend math beyond `toLocaleString`/`toFixed` formatting — doc 15 hazard 4).
- **Modern fintech dark + purple visual.** `static/css/stats.css` (~250 lines) defines the bento grid, sticky filter bar, summary card with 28px big-number, instrument table, and the calendar heatmap with 4 win shades + 3 loss shades using `linear-gradient(135deg, ...)` cells. Scoped to `.stats-page` / `.reports-page` body classes so it doesn't touch Plan 12 styling. The `{% block extra_styles %}` hook on `templates/base.html` is the seam.
- **Five new ES modules, zero new dependencies.** `static/js/stats_filter.js` (URL state + `renderFilterBar` with `popstate` listener), `static/js/stats_charts.js` (`mountLineChart` + `mountHistogramChart` wrap the v4 `addLineSeries`/`addHistogramSeries` API; `mountCalendarHeatmap` is hand-rolled CSS Grid with Sunday-first headers and click-to-navigate cells), `static/js/statistics.js` (dashboard module), `static/js/reports.js` (reports module). No bundler, no Node, no `package.json`, no second chart library. Decision 1 from the design spec.
- **No caching, no migrations, no new dependencies.** Stats are computed live on every request per AC 11. Zero entries in `migrations/`. Zero entries added to `requirements.txt`. The OS page cache on top of SQLite is the only "cache" anywhere on the path.
- **Test coverage.** 451 backend tests pass (391 from prior plans + 60 new from Plan 15). New test files: `test_config_display_timezone.py` (3), `test_models_statistics.py` (10), `test_statistics_aggregations.py` (28), `test_statistics_service.py` (13), `test_routes_stats.py` (12), `test_position_filters_session_date.py` (4), `test_app_factory_plan15.py` (4). Ruff check + format clean.

### What Plan 15 deliberately did NOT land

- **No `chart_defaults` table or settings page** — Plan 16's surface.
- **No second JS chart library** — reuses Plan 13's vendored Lightweight Charts; the calendar heatmap is hand-rolled CSS Grid.
- **No JS unit-test runner** — pure helpers in `stats_filter.js` and `stats_charts.js` are factored to module top so a future plan can add one without rewriting.
- **No statistics caching layer** — AC 11 explicit; doc 11 memoization is the fallback if profiling ever proves it's needed.
- **No new endpoint families beyond `/api/stats/*`** — no chart sharing, no PDF export, no email reports, no SSE.
- **Browser AC walkthrough deferred.** Backend tests verify all 9 routes, both pages, and 5 static assets are wired. The in-browser walkthrough of doc 15 AC 1–11 (filter persistence in URL, calendar cell click navigation, hour bucket timezone shift after editing `display_timezone`, bento layout in real viewport, real-time re-fetch on Apply) is the user's task. Same pattern as Plan 13.

### What Plan 13 deliberately did NOT land

These belong to later plans or are explicit non-goals:

- **No `chart_defaults` table, no migration, no settings page.** Plan 16 owns the database-backed config and the settings UI. Plan 13 ships only the Python seam.
- **No standalone `/charts/{instrument}` page or chart gallery.** Removed by doc 13 deviation 1; charts only exist embedded in position detail.
- **No new OHLC fetcher, no new circuit-breaker config, no chart-route writes to `bars`.** Plan 14 owns the entire OHLC surface; Plan 13 calls Plan 14's existing endpoints unchanged.
- **No JS unit-test runner.** Pure helpers in `PriceChart.js` are factored to the top and exported so a future plan can add a runner without rewriting. Plan 13's frontend verification is the in-browser AC 1–22 walkthrough in Task 12.
- **No new dependencies in `requirements.txt`.** The vendor file is the only new external code.
- **No `routes/chart.py` or new blueprint.** Both new routes register on existing `ohlc` and `positions` blueprints.
- **No second `<div id="chart">` mount point.** Plan 12's existing `<div id="chart-root">` is reused; the placeholder text is removed and nothing else about the detail-page DOM changes.
- **No removal of existing `position_detail.js` behavior.** The chart mounts alongside the existing detail/notes/reviewed/executions/links/delete behavior, not in place of it.
- **Browser AC walkthrough deferred.** Backend tests verify the routes are wired and the static assets are served, but the in-browser walkthrough of AC 1–22 (chart rendering, marker placement, timeframe switching, fetch-now CTA, delayed-data banner, arrow↔row linking) was not run in this session. The user will perform it before declaring the plan fully shipped.

### What Plan 16 landed

- **Migration 006.** Ships `chart_defaults` (one-row `CHECK(id=1)`), `custom_fields`, `custom_field_options`, `execution_custom_field_values`. FK cascades on both executions and field deletions confirmed by tests.
- **InstrumentRegistry.** `services/instrument_registry.py` owns `data/config/instruments.json` with atomic tmp+rename writes under a module-level lock. First load seeds from `DEFAULT_SEED` — the multiplier/symbol/session tables previously hardcoded in `services/instruments.py`. Plans 11/14 callers see identical results for all seeded instruments (pinned by `test_instruments_registry_backcompat.py`).
- **`services/instruments.py` becomes a thin delegator.** Bodies of `get_multiplier`, `source_symbol`, `default_session` now read from the registry. `DEFAULT_TIMEFRAMES`, `base_symbol`, `SessionCalendar` unchanged so plan 14's `app.py` post-tick hook continues to work.
- **DB-backed chart defaults.** `services/chart_defaults.py::get_defaults(db_path)` now SELECTs from the seeded `chart_defaults` row. New `save_defaults(...)` companion writes it inside a transaction. `DEFAULT_TIMEFRAME` bumped from `"1m"` to `"5m"` to match the spec seed row.
- **`config.save_display_timezone`.** New helper reads/modifies/writes `app.json` under a module lock with tmp+rename. Validates IANA strings via `zoneinfo.ZoneInfo`. Called by the chart-defaults PUT handler. No generic config-save path.
- **CustomFieldsService.** Owns all CRUD for definitions, options, and execution values. Typed encoding for `text`/`number`/`dropdown`/`date`/`boolean` in one place. Dropdown writes validated against current options. `#close`/`#open` split-suffix stripped before every DB touch. Two-step delete flow via `affected_executions(field_id)` + `delete_definition(field_id, confirm_count=N)`. `values_for_position(...)` splits results into `entry`/`per_execution`/`definitions`.
- **Settings blueprint.** New `routes/settings.py` with all 13 endpoints from doc 16 plus four page routes (`/settings`, `/settings/instruments`, `/settings/chart`, `/settings/custom-fields`). Registered in `create_app()` between `build_links_blueprint()` and `build_pages_blueprint()`. `FTL_CONFIG_PATH` now lives on `app.config` so the PUT handler can write to `app.json`.
- **Position detail integration.** `services/positions_service.py::attach_metadata` now returns `custom_fields: {entry, per_execution, definitions}` instead of the plan 12 `{}` stub. `static/js/custom_fields_detail.js` renders an inline always-visible block + a `<details>` per-execution fold-out when non-entry executions have values.
- **Four new ES modules, no new dependencies.** `settings_instruments.js`, `settings_chart.js`, `settings_custom_fields.js`, `custom_fields_detail.js`. Plus one `settings.css` scoped to `.settings-page`. No bundler, no framework, no `package.json`, no new `requirements.txt` entries.
- **Doc 16 hazards enforced.** One endpoint per resource; one registry owns `instruments.json`; no profiles, no instrument groups; custom field values attach to `nt_execution_id` (not to any position key); `chart_defaults` stays single-row with `CHECK(id=1)`.
- **End-to-end verification deferred.** Backend tests cover all 13 routes, all four pages, and every service path. In-browser walkthrough of doc 16 AC 1–11 is the user's task — same pattern as plans 13/15.

### What Plan 17 landed

- **Four monitoring pages.** `/imports`, `/validation`, `/data-health`, `/system/health` — each a shell template extending `base.html` mounting a single vanilla ES module under `static/js/`. Four nav links added.
- **Filter surface expansion on existing endpoints.** `GET /api/imports/runs` gains `start_ts`/`end_ts`/`filename`/`status` params and a `total` count. `GET /api/integrity-issues` gains `status` (open/resolved/ignored/all), `severity`, `account`, `instrument` filters — default `status=open` preserves plan 11 behavior.
- **New tick→executions endpoint.** `GET /api/imports/runs/{tick_id}/executions` returns the NT execution IDs inserted by a specific tick via a `source_filename + imported_at` window, feeding the detail-page rollback button.
- **BackgroundServices introspection.** APScheduler EVENT_JOB_SUBMITTED/EXECUTED/ERROR listeners record a 20-entry ring buffer per job_id with start time, duration, status, and error. `system_health_snapshot()` rolls job metadata, thread pool state, watchdog liveness, and process uptime into one dict. `run_job_now(job_id)` submits a scheduled job's function to the thread pool on demand without altering its schedule.
- **`routes/monitoring.py` blueprint.** `GET /api/data-health/completeness` builds a live instrument × timeframe matrix (complete/partial/missing/session_closed) from `bars` + `find_gaps` + the instrument's `default_session`, with a 90-day instrument cutoff and 7-day default lookback. `GET /api/data-health/missing/{instrument}/{timeframe}` drills into one cell's gaps. `GET /api/system/health` exposes the BackgroundServices snapshot. `POST /api/system/run-job/{job_id}` is the force-run hook. Blueprint is registered in `create_app()` after `build_stats_blueprint()`.
- **No new DB tables.** Every dashboard is a read surface over tables and in-process state already produced by plans 10/11/14/00. No alerts table, no completeness table, no parallel monitoring service.
- **Doc 17 hazards enforced.** Exactly four pages. Only `BackgroundServices` (no parallel runtime). No alerts table. One fetch action (`POST /api/chart/{instrument}/fetch`). One validation UI. No quota widgets — just circuit breaker state. No external-service health checks.
- **End-to-end browser walkthrough deferred.** Backend tests cover all five monitoring endpoints, the four page routes, and job history, but the in-browser AC walkthrough (cursor band live-updating, rollback button, auto-refresh, etc.) is the user's task — same pattern as plans 13/15/16.

### What Plan 00 deliberately did NOT land

These belong to later plans:

- No `executions`, `bars`, `import_runs`, `integrity_issues`, or any feature-specific table — only `schema_migrations`.
- No real watchdog handler — `_NoopHandler` is a placeholder that plan 10 will replace.
- No `instruments.json` — plan 16's surface. Plans 10/11/14 may stub a constants module until then.
- No static JS, no templates beyond `base.html`, no business logic, no routes beyond `/healthz`.

## Status

This spec describes a 1:1 feature-parity rebuild of the existing application, with **cohesion** as the primary non-functional goal. It is meant to be fine-tuned by the project owner before implementation begins.

The current revision incorporates the major architectural decisions listed above. These changes are reflected consistently across every feature doc. If a feature doc appears to contradict a decision in this README, the feature doc is wrong and should be corrected — the README is the canonical summary.
