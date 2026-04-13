# Feature 17 — Import Monitoring, Validation & Data Health

## Purpose

Provide the operator-facing dashboards that let the trader see what the system has been doing: import history, validation issues, OHLC data completeness, background service health. This is the "is the system OK?" feature group.

Everything here is a read surface over tables and in-process state that other features produce. This feature owns no business logic — it renders what's already there.

## Dependencies

- **Feature 10** — `import_runs`, `import_rejects`, and `import_cursors` are the data sources for the imports view.
- **Feature 11** — `integrity_issues` is the data source for the validation view.
- **Feature 14** — The `bars` table, the source registry's circuit-breaker state, and the session calendar are the data sources for the data-health view.
- **Doc 03** — The `BackgroundServices` handle exposes APScheduler job state, thread pool pending/active counts, and the watchdog observer thread's liveness for the system-health view.

## User stories

1. **As the trader**, I want to see every import tick that has run, with filename, counts (new rows, duplicates, rejects), cursor progress, and duration.
2. **As the trader**, when a tick rejected rows, I want to drill into the raw rejected lines and reasons.
3. **As the trader**, I want to see currently open integrity issues, sorted by severity, with a link to the affected execution.
4. **As the trader**, I want to mark an integrity issue as resolved or ignored, with a note.
5. **As the trader**, I want a data-completeness view showing each instrument × timeframe combination with its current coverage and any missing ranges.
6. **As the trader**, I want to manually trigger a fetch for a specific instrument/timeframe/range when I see a gap I care about.
7. **As the trader**, I want to see per-source OHLC status: which source provided recent bars, circuit breaker state, last failure reason. Because "is Yahoo down right now?" is a real question.
8. **As the trader**, I want to see background service status: APScheduler jobs with last-run timestamps, thread pool utilization, watchdog observer liveness. Because "is anything running?" is the other real question.

## Acceptance criteria

### Imports view

1. Page `/imports` shows a paginated list of import ticks (`import_runs`), newest first, 50 per page.
2. Each row: `tick_id`, `filename`, `started_at`, duration (finished_at − started_at), status, `rows_inserted`, `rows_skipped_duplicate`, `rows_rejected`, cursor progress (`cursor_before → cursor_after`).
3. Default filter: last 7 days. Filterable by filename, status, and date range.
4. Clicking a row opens `/imports/{tick_id}` showing the full tick row, plus all associated `import_rejects` (raw line, line number, reason).
5. Top of the page shows a summary band: "Active inbox files" (from `import_cursors`) with each file's current cursor position and file size, so the operator can see at a glance "we're 12,847 bytes into today's file, file size is 12,847 bytes, fully caught up" or "file size is 15,000, cursor is 12,847, next tick will process 2,153 new bytes."
6. **Rollback action** lives on this page's detail view: a "Roll back this tick" button deletes the executions inserted by this tick's `tick_id`, via the feature-10 rollback endpoint keyed by execution IDs. Confirm dialog shows which execution IDs will be deleted.
7. **"Scan now" button** on the index page calls `POST /api/imports/scan`, which runs `ingest_tick` on every file currently in inbox. Idempotent; safe to click repeatedly.

### Validation view

1. Page `/validation` shows currently open integrity issues from the `integrity_issues` table, sorted by severity then `detected_at` desc.
2. Each row: severity, type, account, instrument, `execution_id` (with a link to the position detail page that contains that execution, via feature 12), short description, `detected_at`, age.
3. Filter by status (open / resolved / ignored), severity, account, instrument.
4. Per-issue actions: **Resolve** (with optional note, sets `resolved_at` + `resolved_by = 'user'`), **Ignore** (with mandatory note explaining why).
5. The page makes clear that integrity issues auto-resolve when the underlying data stops producing them: a banner explains "issues are re-evaluated on every import; any that no longer hold are marked system-resolved automatically. Ignored issues stay ignored until you unignore them." This is the user-facing face of the rule in feature 11.
6. **There is no "run validation now" button** because validation is not a batch job — it's a diff that runs at the end of every import tick. If the user wants to force re-evaluation, they click "Scan now" on the imports page, which re-runs the tick and re-runs the diff.

### Data health view

1. Page `/data-health` shows a matrix: rows = instruments (only those with any execution in the last 90 days), columns = the canonical timeframes (`1m`, `5m`, `15m`, `1h`, `4h`, `1d`). Each cell has a status: **complete**, **partial**, **missing**, **session-closed**.
2. Status is computed live from one SQL query per row/column pair against the `bars` table, combined with the instrument's session calendar from `instruments.json` (doc 14). No pre-computed completeness table.
3. **"Complete"** means every expected bar slot within the instrument's session hours for the configured lookback window (default 7 days) has a row.
4. **"Partial"** means some bars exist but there are gaps within session hours.
5. **"Missing"** means no bars exist at all in the lookback window.
6. **"Session-closed"** is a degenerate state: the lookback window lies entirely outside the instrument's session (e.g., weekend), so "missing" would be misleading.
7. Color codes: green (complete), yellow (partial), red (missing), gray (session-closed).
8. Clicking a cell opens a detail view showing the specific missing sub-ranges (from `gap_detection.find_gaps`) and a **"Fetch missing"** button that calls `POST /api/chart/{instrument}/fetch` (doc 14) with the gap range. The fetch runs in the background thread pool; the button returns a job ID and the page polls `/api/ohlc/jobs/{job_id}`.
9. **Per-source status band** at the top of the page: one row per configured source (`yfinance`, `stooq`, …) showing: name, circuit breaker state (closed/open/half-open), last successful fetch, last failure with error message, next retry time if open. Pulled from `GET /api/ohlc/sources`.
10. When at least one source is in the `open` state, a banner at the top of the page says "OHLC source \<name\> is currently unavailable (since \<time\>, reason: \<error\>). Falling back to \<next source\>. The rest of the app continues to work normally." This is the user-facing expression of the graceful-degradation rule in doc 14.
11. **No aggregate "API quota" widget.** Neither yfinance nor Stooq has a meaningful quota concept for our usage; the old "Yahoo calls used today / remaining" counter was theater. Removed.

### System health view

1. Page `/system/health` shows in-process background service state. There is **no Redis row, no Celery row, no worker count row** — there is no Redis and no Celery in the new architecture.
2. Sections:
   - **APScheduler** — table of scheduled jobs: job name, trigger (cron expression or interval), last-run time, last-run status, next-run time, average duration (last 20 runs).
   - **Thread pool** — current `ThreadPoolExecutor` state: max workers, active workers, pending futures, total submitted since process start.
   - **Watchdog observer** — observer thread liveness (alive / dead), watched path, events seen in the last hour.
   - **Uptime** — process start time, elapsed uptime, Python version, commit SHA if available.
3. Per-row action on APScheduler jobs: **"Run now"** — submits the job to the scheduler for immediate execution, returns a job run ID, and the page polls until completion. Works for all APScheduler jobs: session archival, scheduled OHLC refresh, safety-sweep ticks, etc.
4. **"Healthz check"** button at the top runs the same checks as the `/healthz` endpoint (doc 03) and shows the result inline: SQLite reachable, APScheduler ticking, watchdog alive, thread pool not saturated. For one-click confidence that the container is behaving.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/imports/runs` | Paginated tick list (already in feature 10). |
| GET | `/api/imports/runs/{tick_id}` | Tick detail with rejects. |
| GET | `/api/imports/cursors` | Current cursor state per file in inbox. |
| POST | `/api/imports/scan` | Run `ingest_tick` on every file in inbox. |
| POST | `/api/executions/rollback` | Delete executions by ID list (already in feature 10). |
| GET | `/api/integrity-issues` | Open integrity issues (already in feature 11). |
| POST | `/api/integrity-issues/{id}/resolve` | Resolve with note. |
| POST | `/api/integrity-issues/{id}/ignore` | Ignore with note. |
| GET | `/api/data-health/completeness` | Matrix of instrument × timeframe coverage. |
| GET | `/api/data-health/missing/{instrument}/{timeframe}` | Missing-range detail for one cell. |
| POST | `/api/chart/{instrument}/fetch` | Trigger fetch (already in feature 14). |
| GET | `/api/ohlc/sources` | Per-source circuit state (already in feature 14). |
| GET | `/api/system/health` | APScheduler + thread pool + watchdog snapshot. |
| POST | `/api/system/run-job/{job_id}` | Force-run an APScheduler job. |
| GET | `/healthz` | Liveness probe (already in doc 03). |

## Fragmentation hazards

1. **Multiple monitoring dashboards with overlapping data.** The old codebase had `/monitoring`, `/monitoring/data-completeness`, `/api/monitoring/health-summary`, `/api/v1/health/data-freshness`, `/api/background-services/status`, plus `/import-logs/` and `/validation/` with their own views. **Rule:** four pages total — `/imports`, `/validation`, `/data-health`, `/system/health`. Each reads from the underlying tables and services directly. No intermediate "monitoring service" aggregates them.

2. **Background services as a parallel implementation.** The old codebase had `background_services.py` with its own threading loop plus Celery running in parallel. **Rule:** the `BackgroundServices` object owned by the application factory (doc 03) is the only background runtime. The system-health view reflects its state. There is no other background runtime to report on.

3. **"Data alerts" as a separate concept.** The old `/api/monitoring/alerts` endpoint surfaced alerts from yet another service. **Rule:** no alerts table, no alerts service. The data-health page computes its banners live from the `bars` table, the source circuit state, and the integrity issues table. Alerts are a view, not a state.

4. **"Repair gap" as different from "fill gap."** The old code had `/api/monitoring/repair-gap` AND `/api/monitoring/data-coverage/{instrument}` with overlapping behavior. **Rule:** one action (OHLC fetch for a specific range), one endpoint (`POST /api/chart/{instrument}/fetch`), one pipeline (doc 14). The phrase "gap fill" and "repair" do not appear in the new UI — the action is "fetch missing bars" and the underlying call is just a fetch.

5. **Validation and integrity as separate UIs.** The old code had `/validation/` (with 15 endpoints), `/positions/api/validation/...` (parallel), and `/validation_cleanup/`. **Rule:** one validation UI page, reading from `integrity_issues`. No "cleanup" page — resolving issues is cleanup.

6. **"Yahoo quota" widgets that don't reflect reality.** The old dashboard had a counter for "Yahoo calls used today" that came from a homegrown tracker, was often wrong, and suggested to the user that there was a known quota to respect (there isn't one — Yahoo silently throttles without publishing a number). **Rule:** no quota widgets. Source health is expressed as circuit breaker state, which is a real signal.

7. **"System health" that depends on external services.** The old `/api/system/health` checked Redis, Celery worker count, and broker connectivity. **Rule:** the new system-health view only reports in-process state (APScheduler, thread pool, watchdog, SQLite). There is nothing external to check because there are no external services.

## Deviations from old behavior

- The four-or-five old monitoring pages collapse to four well-bounded pages, each with a single read source.
- The "data sync history" feature (a separate Redis-backed log of every Missing Candle Retrieval run) is removed; `import_runs` + per-source fetch logs in application logs are sufficient.
- Discord/email notification services are removed from the spec. If alerting becomes a need later, it can subscribe to the `integrity_issues` and `ohlc_sources` endpoints.
- The "retry failed batch" button is gone because there are no batches. The equivalent operation is "click Scan now on the imports page" — ticks are idempotent and cheap, so re-running is the retry.
- Celery worker count, broker status, beat schedule status are all gone. APScheduler + thread pool + watchdog replace all three.

## Open questions for the implementer

- **Per-user resolution notes on integrity issues.** The spec says the resolve/ignore actions accept notes, but doesn't say where they're displayed. Suggest: on the issue row when filtered to "resolved" or "ignored," show the note inline. One column, no modal needed.
- **Lookback window for data health.** Default is 7 days — is that the right tradeoff between "shows recent problems" and "page load time"? 7 days × N instruments × 6 timeframes is ~42·N cells; each cell is one bounded query, so even 20 instruments finishes in under 500ms. 7 days is fine; consider making it configurable on the page.
- **Auto-refresh cadence for the system-health page.** If the operator leaves it open, should it poll every 10s? Suggestion: yes, behind a toggle. The underlying endpoint is cheap.
