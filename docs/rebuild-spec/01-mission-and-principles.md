# Mission & Architectural Principles

## Mission

FuturesTradingLog is a **single-user web application** for analyzing futures trading activity exported from NinjaTrader. It ingests execution CSVs, aggregates them into logical positions, enriches them with market context (OHLC charts), and provides browsing, statistics, validation, and review tools.

The user is a futures trader running NinjaTrader locally. The app runs locally too, in Docker, and is the trader's personal record-keeping and analysis tool. There is no multi-tenancy, no public deployment, no auth.

## Why this rebuild exists

The previous implementation accumulated fragmentation across every layer:

1. **Duplicate sources of truth** — position IDs and trade IDs were independently auto-incremented and routinely confused for each other.
2. **Scattered business logic** — "build a position" was implemented in three different services and partially duplicated in routes.
3. **Disconnected pipelines** — importing a CSV did not reliably trigger OHLC fetches; the chart page did not reliably know which position it was showing.
4. **Inconsistent data contracts** — services returned arbitrarily-shaped dicts; the frontend guessed field names.
5. **Frontend/backend coupling** — JS files reached into backend internals; templates contained hundreds of lines of inline business logic.
6. **Testing gaps** — modules were tangled enough that mocks diverged from production behavior, hiding real bugs.

The rebuild's job is to deliver the same features without these problems. **Cohesion is the primary non-functional requirement.** Every architectural decision must be evaluated against it.

## The Six Rules

These are non-negotiable. They take priority over convenience, parity with the old code, and personal preference.

### Rule 1 — Single source of truth per entity

Every domain entity has exactly one canonical representation in exactly one table. There are no parallel tables that store the same concept with different IDs. If two tables seem to want to hold the same data, one of them is wrong.

**Specifically:** the previous codebase had a `trades` table and a `positions` table with independent auto-increment IDs and an `_executions` junction table linking them. That's three places to look up "which trades belong to this position." The new model collapses this entirely: there is **one** table of executions (`executions`, keyed by NT ExecutionId), and positions are a derived view computed from it on demand (doc 11). There is no `positions` table, no junction table, no numeric position_id.

**How to apply:** executions use NT ExecutionId as the natural primary key. Positions are identified by the natural tuple `(account, instrument, entry_execution_id)`. User metadata (notes, reviewed flags, custom fields, link groups) attaches to execution IDs — never to derived entities — so late-arriving data that changes position boundaries never orphans user work. If you find yourself adding an auto-increment `id` column to a table holding derived data, stop and rethink.

### Rule 2 — Business logic lives in services, not routes

Routes do four things only: parse the request, call exactly one service method, format the response, return it. They contain no calculations, no DB queries, no conditional business logic.

A service method has one purpose, one entry point, and a documented contract. If a route needs three things done, it calls three methods or one orchestration method — never inlines steps.

**How to apply:** if a route file grows past ~200 lines, it's doing too much. If you're tempted to write `if` statements about domain state in a route, the logic belongs in a service.

### Rule 3 — Pipelines are explicit and traceable end-to-end

Every multi-step pipeline (import tick, OHLC fetch) has one named entry point, a documented sequence of steps, and a single result type. The pipeline records what it did so you can answer "what happened to file X" or "why does the chart for position Y have no data" without reading code.

**How to apply:** a pipeline's entry point function takes the input and returns the result. Synchronous fire-and-forget to the thread pool is permitted only for work whose failure is observable through another channel (e.g., the OHLC fetcher submits fetches to the thread pool, and the data-health dashboard shows whether the bars arrived). Silent side effects are forbidden.

### Rule 4 — Data contracts are typed and documented

Every service-to-service and service-to-route data exchange uses a defined type (dataclass, Pydantic model, or equivalent), not a bare dict. Every API response has a documented schema. The frontend never guesses field names.

**How to apply:** when you write a function that returns a dict, ask "what are the keys?" If the answer isn't in a type definition, write the type. If two services pass the same concept, they share the same type.

### Rule 5 — Frontend consumes APIs only

The frontend is a separate concern from the backend. Templates render a shell; JavaScript fetches data from documented JSON endpoints and renders it. Templates never embed business logic in inline `<script>` tags beyond initialization. The JS bundle does not know about Flask internals, Python module names, or database column names that aren't part of the API contract.

**How to apply:** if a template needs to know a derived value, expose it through the API. If JS code references a hidden form field with a Python-flavored name, the API is missing. Inline scripts in templates are limited to wiring (calling an init function with config); all logic lives in `static/js/` files.

### Rule 6 — Every service is testable in isolation

A service can be instantiated, exercised, and asserted against in a test without standing up the full app, hitting an external API, or constructing complex fixtures. Dependencies are injected (DB connection, cache, HTTP client), not imported as singletons.

**How to apply:** if a test needs to monkeypatch a module-level global to work, the service has hidden dependencies. Constructors take their dependencies; module-level state is reserved for true configuration constants.

## Non-goals

These are explicitly out of scope and must not be added during the rebuild:

- **Multi-user support, auth, or sessions.** The app is single-user. Any auth is provided by an external proxy if needed for deployment.
- **Real-time order routing or trade execution.** The app is read-only with respect to trading; it ingests history.
- **Mobile-first or responsive UI.** Desktop browser is the only target.
- **Generic CSV import.** Only the format produced by the preserved `ExecutionExporter.cs` (see doc 90) needs to be supported. No format auto-detection, no plugin system.
- **Backwards compatibility with the previous database.** The new schema is fresh. A migration tool may be written separately if the user wants to preserve historical data; it is not part of this spec.
- **Microservices, message queues, distributed tracing, external brokers.** A single Flask process with in-process APScheduler, a thread pool, and watchdog is the entire runtime. No Celery, no Redis, no RQ. See doc 03.

## When the rules conflict with parity

If achieving 1:1 feature parity would require violating one of the Six Rules, the rule wins. Document the deviation in the relevant feature doc's "Deviations from Old Behavior" section and proceed.
