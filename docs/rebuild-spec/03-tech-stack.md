# Tech Stack

The rebuild uses largely the same stack as the previous implementation, with one deliberate simplification: **Celery and Redis are removed.** The previous codebase used them to paper over cohesion problems (scattered background jobs, unclear ownership of async work) rather than for any need that actually existed on a single-user local machine. Keeping the rest of the stack lets the implementer focus all attention on cohesion; removing the queue layer collapses four services to one and eliminates a class of "why isn't this task running?" bugs.

## Languages & runtimes

- **Python 3.11+** — Backend, background workers, scripts.
- **JavaScript (ES2020+, no transpile step)** — Frontend. Vanilla JS. No build pipeline, no bundler, no framework.
- **C# / NinjaScript** — `ExecutionExporter.cs` only. Preserved verbatim from the existing codebase (see doc 90). Not modified during the rebuild.

## Backend

- **Flask** — HTTP server. Use the application factory pattern. Blueprints for feature grouping. No global app object. No `flask-restful`, no `flask-restx`, no big extension stack — Flask is small and obvious by design and the new app should stay that way.
- **SQLite** in WAL mode — Primary data store *and* the cache. Single file in the data volume. No separate DB server process. WAL mode gives concurrent reads alongside writes from the background worker thread. For OHLC candles specifically: an index on `(instrument, timeframe, timestamp)` returns a few thousand rows in ~1–5 ms, and the OS page cache keeps hot pages in RAM for free. No separate cache layer is needed or wanted.
- **APScheduler** — In-process scheduler, started by the Flask application factory. Owns all recurring work: gap-filling OHLC data, validation sweeps, cache warming (if any), log rotation hooks. Runs in a background thread of the web process. One place to look when asking "what runs on a schedule?"
- **`concurrent.futures.ThreadPoolExecutor`** — For fire-and-forget background work triggered by HTTP requests or the file watcher (post-import integrity diffs, OHLC fetches for newly-imported time ranges). Bounded pool, sized in config. Exceptions are logged with context; no silent swallowing.
- **`watchdog`** — File system observer for the NinjaTrader CSV drop directory. Runs in its own thread, started by the application factory. On a new file, it hands off to the import service synchronously (the import itself is fast); any slow follow-up work (OHLC fetch, chart pre-warm) is submitted to the thread pool.
- **yfinance** — Yahoo Finance OHLC data source. Wrapped in a single service so the HTTP dependency is mockable. The wrapper owns rate limiting (token bucket), retry/backoff, and a circuit breaker — yfinance is unofficial and fragile, so isolating its failure modes in one place is a hard requirement, not a nice-to-have.
- **Pydantic** — For typed data contracts between layers. **Mandatory, not "implementer's choice."** Rule 4 says data contracts are typed; allowing a dataclass escape hatch guarantees inconsistency the first time someone picks the other option. Pydantic everywhere, full stop.

## Frontend

- **Vanilla JS** — No React, no Vue, no Svelte. Each feature page is a small script that fetches from the JSON API and renders to the DOM.
- **Bootstrap 5** — CSS framework. Loaded from CDN or vendored, implementer's choice. Used for layout primitives, forms, and dark-mode theming.
- **TradingView Lightweight Charts** — The candlestick library for the position detail chart. Loaded as a single ES module. The chart wrapper is a single class in `static/js/PriceChart.js`-equivalent, not split across multiple files. (See doc 13.)
- **No CSS preprocessor.** Plain CSS files in `static/css/`.

## Tooling & dev environment

- **Docker Compose** — The deployment unit. Exactly **one service**: `web` (Flask + APScheduler + thread pool + file watcher, all in one process). SQLite file and logs live in named volumes. No worker service, no beat service, no broker service. If `docker compose ps` shows more than one container, something has gone wrong.
- **pytest** — Test framework. Tests live in `tests/`, mirroring the source layout. Every service has unit tests; pipelines have integration tests that use a real (temp-file) SQLite database, never mocks. Background-job tests call the job function directly — no queue to mock because there is no queue.
- **Ruff** — Linter and formatter for Python. Configured in `pyproject.toml`.
- **No type checker mandated** — but type hints are used everywhere on service interfaces (Rule 4). If the implementer wants to run mypy or pyright, they can; it's not a build gate.

## Concurrency model (read this carefully)

The web process has a small number of well-defined threads, all started by the application factory and owned by a single `BackgroundServices` object that the app holds a reference to:

1. **Flask request threads** — whatever the WSGI server (gunicorn/waitress) provides. Handle HTTP.
2. **APScheduler thread** — fires scheduled jobs. One.
3. **Watchdog observer thread** — watches the CSV drop directory. One.
4. **ThreadPoolExecutor workers** — bounded pool (default 4) for ad-hoc async work submitted from request handlers or the file watcher.

Rules:

- **SQLite writes must be serialized per-connection.** Each thread that writes gets its own connection; WAL handles concurrent readers. No connection is shared across threads.
- **No thread talks to another thread except through SQLite or the thread pool's futures.** No shared mutable state, no in-memory queues between threads.
- **The application factory returns `(app, background_services)`.** Tests can construct the app without starting background services; production startup calls `background_services.start()` after the app is built. Graceful shutdown calls `background_services.stop()`.
- **Jobs are idempotent.** If APScheduler fires a gap-fill twice because of a restart, the second run is a no-op. This is the same discipline Celery would have forced, minus Celery.

This concurrency model is simple enough to hold in your head. That is the point.

## Container runtime

The `web` container runs Flask behind gunicorn (or waitress on Windows hosts) as PID 1. Inside that single Python process, the application factory starts the APScheduler thread, the watchdog observer thread, and the ThreadPoolExecutor. One container, one process, several threads.

- **Graceful shutdown.** SIGTERM from Docker must reach the WSGI server, which must call `background_services.stop()` before exiting. APScheduler finishes its current job, watchdog stops observing, the thread pool drains with a bounded timeout. Gunicorn's `--graceful-timeout` plus a signal handler registered in the app factory cover this. Ungraceful shutdowns are recoverable because jobs are idempotent, but the graceful path is the expected one.

- **Blast radius.** One process means one restart domain. A wedged OHLC fetch cannot take down HTTP *unless* a request handler blocks on a future without a timeout, or the thread pool is unbounded. Both are forbidden: request handlers never `.result()` on a background future, and the pool size is fixed in config. The yfinance wrapper's circuit breaker is what keeps a misbehaving upstream from saturating the pool.

- **Healthcheck.** Compose `healthcheck` hits `GET /healthz`, which verifies: (a) SQLite is reachable and WAL is healthy, (b) APScheduler's last tick is within the expected interval, (c) the watchdog observer thread is alive, (d) the thread pool is not saturated. This is the container-native replacement for "is Beat running?" — all four checks are cheap in-process introspection.

- **Logging.** Single process → single stdout stream → `docker logs web` is the one place to look. JSON-structured log lines include a `component` field (`http`, `scheduler`, `watcher`, `pool`, `yfinance`) so they can be filtered without needing separate log streams per subsystem.

- **Volumes.** Named volume for `data/` (SQLite, archived CSVs, logs, config). Bind mount or named volume for the NinjaTrader CSV drop directory watched by watchdog. Nothing else is persistent.

## Storage layout (suggested, implementer may refine)

```
data/
  trading_log.db         # the SQLite database
  archive/               # processed CSV files
  config/
    instruments.json     # multipliers, tick sizes, symbol mapping
  logs/                  # rotating app logs
```

## What's explicitly NOT in the stack

- **No Celery, no Redis, no RQ, no message broker of any kind.** Background work is in-process. Reasoning: single-user, single-machine, no need for cross-process queuing. The previous codebase used Celery+Redis and the operational overhead (three extra services, broker/worker version mismatches, Beat not running, tasks silently queued to wrong queues) produced more bugs than it ever solved. See commit 78e95c6 for a representative example.
- **No ORM.** SQLAlchemy is not used. Raw SQL with parameterized queries through `sqlite3.Connection`. Reasoning: the schema is small and stable; an ORM adds indirection without payoff and tends to encourage Rule-2 violations.
- **No separate cache layer.** SQLite + OS page cache is the cache. If a query is slow, add an index or a materialized summary table — don't reach for Redis.
- **No GraphQL.** REST/JSON only.
- **No frontend framework.** The previous codebase had unused `core/ComponentBase.js` / `ComponentRegistry.js` scaffolding for a custom component system that was never adopted. Don't recreate it.
- **No microservices, no service discovery.**
- **No cloud dependencies.** The app runs on a single machine.
- **No analytics, no telemetry, no error tracking SaaS.** Logs go to stdout and a rotating file.

## Versioning policy

Pin all Python dependencies in `requirements.txt` with exact versions. Pin the JS CDN URLs to specific versions. Pin the Docker base image by digest, not tag. Reproducible builds matter more than auto-updates for a single-user local app.
