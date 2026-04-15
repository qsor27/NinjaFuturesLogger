# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Single-user Flask app for analyzing NinjaTrader futures exports. This is a **rebuild from spec** — the canonical source of truth is `docs/rebuild-spec/00-README.md` and the numbered feature docs it lists. When a question starts with "how should X work?", read the relevant spec doc before reading code.

Implementation progresses plan-by-plan under `docs/superpowers/plans/` in build order: 00 → 10 → 11 → 14 → 12 → 13 → 15 → 16 → 17. As of 2026-04-14, every plan (00–17) is complete.

## Commands

- **Run tests:** `pytest` (config in `pyproject.toml`, `testpaths = ["tests"]`)
- **Run a single test:** `pytest tests/test_positions_service.py::test_name`
- **Lint / format:** `ruff check .` and `ruff format .` (line-length 100, target py311)
- **Run the app locally:** `gunicorn -w 1 -b 0.0.0.0:8000 wsgi:app` (workers **must** stay at 1 — see below)
- **Docker (primary dev target):** `docker compose up -d --build`; `docker compose ps` must show exactly one service (`futurestradinglog`). Health: `curl http://localhost:8000/healthz`.
- **Bind mount:** `C:\Containers\NinjaFuturesLogger` on the host → `/app/data` in the container. Config lives at `data/config/app.json`. Dropping a CSV into `data/inbox/` triggers a real import via the watchdog.

## Architecture — load-bearing rules

These aren't style preferences; reversing any of them invalidates multiple feature docs. Re-read `docs/rebuild-spec/00-README.md` "Load-bearing architectural decisions" when in doubt.

1. **One Flask process, in-process background work.** `BackgroundServices` (in `background.py`) owns an APScheduler `BackgroundScheduler`, a bounded `ThreadPoolExecutor(max_workers=4)`, and a watchdog `Observer`. No Celery, no Redis, no broker. Gunicorn is pinned to 1 worker because this in-process state would otherwise be duplicated. `create_app()` in `app.py` returns `(Flask, BackgroundServices)`.

2. **Positions are a derived view, not a stored table.** `executions` is the only source of truth. `services/positions.py::build_positions` is a **pure function** — sort by `(timestamp, nt_execution_id)`, walk once, emit `Position` models. No `positions` table exists, no numeric position ID, no rebuild lifecycle. Position identity is the natural key `(account, instrument, entry_execution_id)`. Reversal fills are split in-memory into `#close`/`#open` sub-fills with proportional commission.

3. **Imports are idempotent by construction.** `executions` has `UNIQUE(nt_execution_id, account)` and every insert is `ON CONFLICT DO NOTHING`. `ImportPipeline.ingest_tick` tails each CSV using a byte cursor in `import_cursors`, consuming only complete newline-terminated rows. There is no file tracking, no "already imported?" check, no batch concept, no upload endpoint. Rollback operates on execution IDs (`POST /api/executions/rollback`), and FK cascades clean up notes/flags.

4. **Session-end archival, never per-tick.** APScheduler runs `archive_completed_sessions` once per day at `config.session.archive_job_time` (default 18:00 America/Chicago). Today's file is never touched. A 5-minute `import_safety_sweep` job re-scans the inbox as a safety net.

5. **OHLC is structurally isolated.** `fetch_range` in `services/ohlc/fetcher.py` is the **only** function that calls a source. Read routes (`/api/chart/{instrument}`) never fetch; on-demand fetches go through `POST /api/chart/{instrument}/fetch` which queues a job on `FetchJobRegistry` + the thread pool and returns 202 with a `job_id`. The `bars` table has **no foreign keys pointing at it**. yfinance (primary) and Stooq (fallback) implement the `OhlcSource` Protocol; each adapter lazy-imports its transport library and converts raw responses to `list[Bar]` — pandas/CSV never leak out. Per-source `CircuitBreaker` fast-trips on HTTP 429/5xx. Gap detection consults `services.instruments.default_session` so the CME overnight break never looks like missing data. When every source is down, imports, positions, stats, notes, and `/healthz` keep working; the chart shows a delayed-data banner.

6. **User metadata keys off stable IDs.** Notes (`execution_notes`), reviewed flags (`execution_flags`), and link group membership (`position_links`) attach to `nt_execution_id` (stable across imports) or the position natural key (deterministic from executions). `notes.strip_split_suffix` removes `#close`/`#open` suffixes so synthesized reversal sub-fills inherit their parent's metadata.

7. **Pydantic at every type boundary, SQLite as the only store.** `models.base.StrictModel` (Pydantic v2, `extra="forbid"`, `strict=True`) is the base for every service-to-service contract. `db.connect(path)` opens WAL + `foreign_keys=ON` + `synchronous=NORMAL` + `busy_timeout=5000`, one connection per thread. Migrations in `migrations/*.sql` are applied in lexicographic order inside an atomic transaction and recorded in `schema_migrations`.

## Post-tick hook chain

`ImportPipeline.post_tick_hooks` is ordered. `app.py` registers two hooks at startup:
1. **Integrity hook** — calls `run_integrity_diff(db, account, instrument)` per affected pair, upserting `integrity_issues` and auto-resolving stale ones.
2. **OHLC hook** — for each affected `(account, instrument)` and every `DEFAULT_TIMEFRAMES` value, submits a `fetch_range` job to the pool. **Imports never wait on OHLC.**

Plus two scheduled refresh jobs: `ohlc_refresh_recent` (every 15 min, last 6h) and `ohlc_refresh_week` (every 4h, last 7d) for instruments that traded in the last 7 days.

## Frontend conventions (plans 12 & 13)

- No bundler, no framework, no `package.json`, no Node, no npm. Vanilla ES modules under `static/js/`.
- Server-rendered shell templates extend `base.html`; JS reads `data-*` attributes, calls the JSON API, renders with `textContent`.
- **The only third-party JS is TradingView Lightweight Charts v4.2.3**, vendored at `static/vendor/lightweight-charts.standalone.production.js` and loaded via plain `<script src>`. Pinned at v4 because v5 replaces `addCandlestickSeries()`/`addHistogramSeries()` with a single `addSeries(...)` factory.
- **Exactly one chart implementation:** `static/js/PriceChart.js`. Pure helpers live at the top of the file (DOM-/fetch-/library-free, exported for future test runners) and one `PriceChart` class owns the rest.
- Chart ↔ executions-table linking uses two custom events, both keyed by un-suffixed `nt_execution_id`: `executions-table:row-clicked` and `chart:execution-clicked`.

## Plan 16 seams (stubbed now, replaced later)

These modules exist as the seam for plan 16 — extend them rather than creating parallel configuration:
- `services/instruments.py` — `get_multiplier`, `DEFAULT_TIMEFRAMES`, `source_symbol`, `default_session`. Plan 16 replaces the dict bodies with a JSON/DB-backed registry.
- `services/chart_defaults.py` — `get_defaults()` returns a fresh dict each call. Plan 16 will swap the body for a `chart_defaults` table SELECT without touching callers.

## Working agreement

- **Solo workflow on `master`:** feature work commits directly to master; no PRs, no feature branches.
- **One plan at a time:** write a plan in `docs/superpowers/plans/` → execute to green → write the next. Earlier plans teach later plans.
- **Acceptance criteria in feature docs are the definition of done.** "Fragmentation Hazards" sections describe specific failure modes from the previous codebase — do not recreate them.
- **Do not read or copy from any prior FuturesTradingLog codebase.** If a spec is unclear, ask — don't infer from legacy code. `ninjascript/ExecutionExporter.cs` is preserved verbatim and its CSV column contract (doc 90) is immutable.
- **Windows + Docker bind mount gotcha:** watchdog requires `PollingObserver` on Windows because inotify-style events don't propagate across the bind mount. Don't "fix" this back to the default observer.
- **Scheduled / background agent output lives under `docs/agent-runs/`.** Files in that directory are written by scheduled or handoff Claude sessions (via `/schedule` triggers, background workers, or manual handoff prompts). Interactive sessions **must not** read, reference, include in commits, or act on files under `docs/agent-runs/` unless the user explicitly names a specific file there. Treat the directory as out-of-band scratch space, not part of the working set.
