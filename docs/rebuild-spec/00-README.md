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

## Status

This spec describes a 1:1 feature-parity rebuild of the existing application, with **cohesion** as the primary non-functional goal. It is meant to be fine-tuned by the project owner before implementation begins.

The current revision incorporates the major architectural decisions listed above. These changes are reflected consistently across every feature doc. If a feature doc appears to contradict a decision in this README, the feature doc is wrong and should be corrected — the README is the canonical summary.
