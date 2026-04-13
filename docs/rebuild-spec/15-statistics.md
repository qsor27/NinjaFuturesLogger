# Feature 15 — Statistics & Reports

## Purpose

Aggregate position data into the statistics a trader cares about — P&L by day/week/month, win rate, performance by instrument, execution quality metrics — and present them as dashboards and exportable reports.

## Dependencies

- **Feature 11** — Positions are a derived view over the `executions` table (doc 11). Statistics iterate positions by running `build_positions` once per `(account, instrument)` in scope and aggregating the results in Python. There is no `positions` table to query.
- **Feature 16** — Multipliers (used in dollars P&L) come from instrument config.

## User stories

1. **As the trader**, I want a statistics dashboard that summarizes my recent performance: total P&L, win rate, number of trades, average win, average loss, profit factor, by day/week/month.
2. **As the trader**, I want to see P&L broken down by instrument so I know which contracts are profitable.
3. **As the trader**, I want to see P&L broken down by side (long vs short) and by hour of day so I can spot patterns.
4. **As the trader**, I want a "performance" report page that shows daily P&L on a calendar and a cumulative equity curve.
5. **As the trader**, I want execution-quality metrics: average hold time per position, average position size, fill quality (price vs intended).
6. **As the trader**, I want all stats to be filterable by account and date range.
7. **As the trader**, I want stats computed live (not scheduled) so they always reflect the current state of the database.

## Acceptance criteria

1. There is one `StatisticsService` with documented methods, each returning a typed result.
2. All inputs are positions (closed, with `dollars_pnl != null`). Open positions are excluded from P&L stats. Open positions count toward "currently open" displays only.
3. The dashboard endpoint returns: total positions, total P&L, win count, loss count, scratch count, win rate %, average win, average loss, profit factor (gross_profit / gross_loss), largest win, largest loss, longest winning streak, longest losing streak. All scoped by the filter (account, date range).
4. Per-instrument breakdown returns: instrument, position count, total P&L, win rate, average P&L per position.
5. Per-day/week/month breakdown returns time bucket, position count, total P&L. Date bucketing uses the trading session date (see glossary), not calendar date.
6. Per-hour-of-day breakdown returns hour 0..23 (in trader's local timezone, configurable), position count, total P&L. Useful for execution-quality analysis.
7. Per-side breakdown returns Long/Short, position count, total P&L, win rate.
8. Execution-quality metrics: average hold time minutes, median hold time, average position size in contracts, P&L distribution histogram (by 10 buckets).
9. The dashboard page (`/statistics`) renders charts via the same JS chart helpers used in feature 13. Aggregations come from API endpoints; the JS does no math beyond display formatting.
10. The reports page (`/reports`) shows: monthly P&L calendar heat map, cumulative equity curve, instrument breakdown table, performance summary card.
11. There is no caching layer for statistics. They are computed on demand by calling `build_positions` once per `(account, instrument)` in scope and aggregating in Python. The app is single-user and the execution count is small enough (tens of thousands) that this is well under 500ms for any typical filter. If profiling ever proves otherwise, the memoization cache described in doc 11 applies first — stats do not get their own cache.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stats/summary` | Headline stats for the dashboard. Query: `account?`, `from?`, `to?`. |
| GET | `/api/stats/by-instrument` | Per-instrument breakdown. |
| GET | `/api/stats/by-day` | Per-day buckets for a date range. |
| GET | `/api/stats/by-week` | Per-week buckets. |
| GET | `/api/stats/by-month` | Per-month buckets. |
| GET | `/api/stats/by-hour` | Per-hour-of-day buckets. |
| GET | `/api/stats/by-side` | Long/Short breakdown. |
| GET | `/api/stats/equity-curve` | Cumulative P&L over time for charting. |
| GET | `/api/stats/distribution` | P&L histogram. |

UI pages: `/statistics` (dashboard), `/reports` (reports hub).

## Fragmentation hazards

1. **Multiple stats services.** The old codebase had `statistics_calculation_service.py` (with `StandardizedStatisticsCalculator` and `DashboardStatisticsIntegration` classes), `performance_service.py`, and routes (`statistics.py`, `performance.py`, `reports.py`, `execution_analysis.py`) that each computed pieces themselves. **Rule:** one `StatisticsService` class with explicit methods. Routes call methods; they do no SQL of their own.

2. **Inconsistent date bucketing.** The old code mixed calendar dates and session dates depending on the route. **Rule:** all bucketing uses session date (see glossary). The session date is computed from the position's entry timestamp by a helper in the time-utils module, used everywhere.

3. **Hidden cache layers.** The old code cached some stats in Redis with TTLs that were sometimes longer than the import interval, leading to stale dashboards. **Rule:** stats are not cached at the stats layer. If caching is ever needed, it happens once at the position layer (doc 11 memoization) and stats inherit it transparently — there is never a separate stats cache.

4. **Computation in the frontend.** The old dashboard JS did some win-rate calculations from raw position arrays. **Rule:** the frontend renders precomputed numbers; no math.

5. **Duplicate "win rate" definitions.** The old code had three different definitions of win rate depending on which page you looked at (some included scratch, some excluded). **Rule:** one definition: win rate = wins / (wins + losses), excluding scratches. Documented in `StatisticsService` docstrings and in this spec.

## Definitions

Outcome thresholds use the position's **commission** as the scratch band, so a trade that only covered its own fees is not counted as a win. These definitions are canonical — the position list filter in feature 12 and the monitoring counts in feature 17 both reference them.

- **Winner**: closed position with `dollars_pnl > commission`.
- **Loser**: closed position with `dollars_pnl < -commission`.
- **Scratch**: closed position with `|dollars_pnl| <= commission`.
- **Win rate**: `count(winners) / (count(winners) + count(losers))`. Scratches are excluded from both numerator and denominator. Returns null when there are zero winners and zero losers.
- **Profit factor**: `sum(winners.dollars_pnl) / abs(sum(losers.dollars_pnl))`. Undefined (return null) if no losers.
- **Average win**: `sum(winners.dollars_pnl) / count(winners)`.
- **Average loss**: `sum(losers.dollars_pnl) / count(losers)` (negative number).
- **Equity curve**: cumulative sum of `dollars_pnl` over closed positions ordered by `exit_time`.
- **Session date**: the trading-session calendar date (see glossary). Computed by `services/time_utils.py::compute_session_date(ts_utc)`, which applies the 16:00 America/Chicago rollover. All date bucketing in this feature uses this function — never the raw calendar date of `entry_time.date()`.

## Deviations from old behavior

- The four old reports pages (`/reports`, `/reports/performance`, `/reports/execution-quality`, `/reports/timing-analysis`) collapse to one `/reports` hub with sections. Each section uses the same `StatisticsService`.
- The "execution analysis" route's separate per-hour data endpoints are replaced by `/api/stats/by-hour`.
- The "monthly summary" page is folded into the reports hub as a section.
