# FuturesTradingLog

A single-user web application for analyzing futures trading activity exported from NinjaTrader.

**This repository is a rebuild.** It starts from a complete specification and no prior code. If you are an AI assistant or a human developer opening this repo for the first time, your entry point is:

> **[`docs/rebuild-spec/00-README.md`](docs/rebuild-spec/00-README.md)**

That document is the map. It lists every other spec doc in the order you should read them, and it summarizes the load-bearing architectural decisions that shape every feature.

## Before you write any code

1. Read `docs/rebuild-spec/00-README.md` end-to-end.
2. Read `docs/rebuild-spec/01-mission-and-principles.md`. The Six Rules are non-negotiable.
3. Read `docs/rebuild-spec/02-glossary.md`. The domain vocabulary is precise and some terms (Side vs. Position side, Action vs. Side, Execution vs. Position) are easy to confuse.
4. Then read the feature docs in the order listed in `00-README.md`'s build-order section: 10 → 11 → 14 → 12 → 13 → 15 → 16 → 17.

Do not read or copy from any prior FuturesTradingLog codebase. If you need to answer "what did the old app do here?", the answer belongs in a feature doc's acceptance criteria or fragmentation-hazards section — not in old source files. If a spec doc is unclear, raise the ambiguity with the project owner rather than inferring from legacy code.

## Repository layout at first commit

```
/
├── README.md                       # this file
├── docs/
│   └── rebuild-spec/               # the complete specification (13 docs)
└── ninjascript/
    └── ExecutionExporter.cs        # preserved verbatim from the prior project
                                    # (see docs/rebuild-spec/90-preserved-assets.md
                                    # for the narrow write-path exceptions)
```

Everything else — application code, tests, Docker config, migrations — is created during implementation, guided by the spec.

## Architectural ground rules (summary only — the spec is canonical)

- **One Flask process.** APScheduler + `ThreadPoolExecutor` + `watchdog` all run inside it. No Celery, no Redis, no message broker. `docker compose ps` shows exactly one service.
- **Positions are a derived view, not a stored table.** Executions are stored (keyed by NinjaTrader `ExecutionId`); positions are computed from them on every read.
- **Imports are idempotent by construction.** The `executions` table has `UNIQUE(nt_execution_id, account)` and every insert is `ON CONFLICT DO NOTHING`.
- **OHLC is isolated.** When every OHLC source is down, imports, positions, stats, notes, and monitoring all keep working. The chart area shows a delayed-data banner.
- **User metadata attaches to execution IDs, never to derived entities.** Notes, reviewed flags, custom fields, and link groups all key off `nt_execution_id` or the position natural key.
- **Pydantic everywhere at type boundaries. SQLite is the only data store.**

Full reasoning for each of these is in `docs/rebuild-spec/00-README.md` under "Load-bearing architectural decisions."

## Status

Pre-implementation. The spec is complete and internally consistent. Implementation planning begins from this commit.
