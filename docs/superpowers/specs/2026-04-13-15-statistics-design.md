# Plan 15 — Statistics & Reports — Design Spec

> **Handoff doc for a fresh implementation session.** This captures the design decisions made during the Plan 15 brainstorming session on 2026-04-13. It is the input to `superpowers:writing-plans` for Plan 15. Read this in conjunction with `docs/rebuild-spec/15-statistics.md`, which is the canonical feature spec; this design doc only resolves the open decisions doc 15 left to the implementer.

## Context

Plan 15 implements feature 15 (Statistics & Reports). It is the second-to-last feature plan in the rebuild — only Plans 16 (Settings) and 17 (Monitoring) remain. Plans 00, 10, 11, 12, 13, and 14 have shipped.

The feature delivers:
- A `StatisticsService` with one method per stats endpoint
- 9 read-only `GET /api/stats/*` endpoints
- 2 server-rendered HTML pages: `/statistics` (at-a-glance dashboard) and `/reports` (deep-dive)
- Live computation, no caching, no scheduled jobs

This plan adds zero migrations, zero new dependencies, no new third-party JavaScript, and reuses Plan 13's vendored TradingView Lightweight Charts library for line and histogram charts. The monthly calendar heatmap is hand-rolled CSS Grid.

## Decisions made during brainstorming

Five design questions doc 15 left open were resolved on 2026-04-13:

### Decision 1 — Charting strategy (Q1)

**Reuse Plan 13's vendored TradingView Lightweight Charts everywhere it fits, hand-roll the calendar heatmap as plain CSS Grid.** No second chart library, no new vendor file. Lightweight Charts handles the equity curve (`addLineSeries`), the by-day / by-week / by-month / by-hour bar charts (`addHistogramSeries`), and the P&L distribution histogram. The monthly calendar heatmap is roughly 50 lines of CSS Grid + hand-coded `<div>` cells.

**Why:** preserves Plan 13's "exactly one chart implementation" rule, adds zero dependencies, and the calendar heatmap is genuinely simple as a grid. A future plan can swap Lightweight Charts for a more dashboard-focused library if needed; until then, no second library enters the codebase.

**How to apply:** all chart rendering goes through a thin wrapper module `static/js/stats_charts.js` that exports three functions: `mountLineChart`, `mountHistogramChart`, and `mountCalendarHeatmap`. The first two delegate to the existing `window.LightweightCharts` global; the third is the hand-rolled CSS Grid renderer.

### Decision 2 — Filter UI scope and persistence (Q2)

**Top-of-page filter bar; state lives in URL query params** (`?account=Sim&from=2026-01-01&to=2026-04-13`).

**Why:** bookmarkable, shareable, survives reload, supports browser back/forward, and aligns with Plan 12's `/positions` page which already uses URL query params for its filters. Costs ~20 extra lines vs. an in-memory state object.

**How to apply:** a single shared module `static/js/stats_filter.js` exports `parseFilterFromUrl()`, `writeFilterToUrl(filter)`, and `renderFilterBar(container, filter, onApply)`. Both `statistics.js` and `reports.js` import it. Filter changes call `history.pushState`, then trigger a re-fetch. A `popstate` listener re-reads the URL and re-fetches when the user uses browser back/forward.

### Decision 3 — Positions with null `dollars_pnl` from a missing multiplier (Q3)

**Skip them from every aggregation, but expose a `skipped_no_multiplier` count in the `/api/stats/summary` response so the dashboard can warn the user.**

**Why:** open positions are excluded from P&L stats by AC 2; the closed-but-missing-multiplier case wasn't explicitly addressed by the doc. Silently dropping them loses signal. Reporting them as a count is honest, surfaces a misconfigured instrument, and once Plan 16 ships the multiplier registry the count naturally drops to zero.

**How to apply:** the `_load_closed_positions(filter)` helper inside `StatisticsService` returns three buckets (`closed_with_pnl`, `closed_missing_multiplier`, `open`). All aggregations operate on `closed_with_pnl`. The summary endpoint includes `skipped_no_multiplier: int` (the length of `closed_missing_multiplier`) and `open_positions: int`. The dashboard summary card renders a yellow warning row when `skipped_no_multiplier > 0` with text like "5 positions excluded — add their instruments to the multiplier registry".

### Decision 4 — Timezone for hour-of-day bucketing (Q4)

**Add a separate `display_timezone` field to `app.json`, defaulting to `session.exchange_timezone` if unset. Plan 16's settings page will eventually expose it in the UI; for Plan 15 it is editable directly in `app.json`.**

**Why:** the user explicitly wants this configurable in settings, separate from the session-date rollover timezone. AC 6 says "configurable" and the realistic case (a Tokyo-based trader trading CME) wants the display timezone separable from the rollover timezone.

**How to apply:**
1. Add `display_timezone: str | None = None` to `Config` (in `config.py`). Loader treats `None` or missing key as "use `session.exchange_timezone`".
2. The `StatisticsService.by_hour(filter)` method accepts no timezone argument — it reads `config.display_timezone or config.session.exchange_timezone` from the injected config.
3. Plan 16 will add the field to the settings page UI later; Plan 15 just establishes the config field and the consumer.

### Decision 5 — Layout of `/statistics` and `/reports` (Q5)

**Functional split: two pages, two purposes.** `/statistics` is the at-a-glance daily dashboard (summary, equity curve, by-day, by-instrument, by-side, by-hour). `/reports` is the weekly/monthly deep-dive (calendar heatmap, larger equity curve, by-week and by-month, P&L distribution). Each page is a server-rendered shell template + ES module + JSON API calls. Shared filter bar component.

**Why:** matches doc 15's literal intent (two pages, two purposes), keeps each page focused, lets the filter bar be a small reusable component, plugs into Plan 12's existing pattern.

**How to apply:** see Section "Frontend layout" below.

### Visual direction (added during visual brainstorm)

The user requested an attractive, polished visual. Three style directions were shown in mockups:
- **Style A** — Bloomberg trader terminal (dense, monospace, dark, green/red)
- **Style B** — Modern fintech / Linear / Robinhood (rounded cards, big numbers, dark, purple accent) ✅ **selected**
- **Style C** — Editorial minimal (light, serif, lots of whitespace)

Three layout directions for `/statistics` were shown:
- **Layout A** — Single column, full-width sections stacked
- **Layout B** — Hybrid: full-width hero + two-column grid below
- **Layout C** — Bento grid (asymmetric, varying card sizes) ✅ **selected**

Three calendar heatmap directions were shown:
- **Calendar A** — GitHub-style small squares (day number only, hover for amount)
- **Calendar B** — Mid-size cells with inline P&L
- **Calendar C** — Tall cells with P&L + trade count + linear-gradient backgrounds ✅ **selected**

The selected combination — modern fintech style + bento dashboard + tall calendar cells — is the single visual direction Plan 15 implements.

---

## Architecture

One `services/statistics.py::StatisticsService` class with one method per `/api/stats/*` endpoint. Each method takes a `StatsFilter` and returns a typed Pydantic StrictModel.

```python
class StatisticsService:
    def __init__(self, config: Config): ...

    def summary(self, filter: StatsFilter) -> StatsSummary: ...
    def by_instrument(self, filter: StatsFilter) -> InstrumentBreakdown: ...
    def by_day(self, filter: StatsFilter) -> TimeBucketResponse: ...
    def by_week(self, filter: StatsFilter) -> TimeBucketResponse: ...
    def by_month(self, filter: StatsFilter) -> TimeBucketResponse: ...
    def by_hour(self, filter: StatsFilter) -> HourBucketResponse: ...
    def by_side(self, filter: StatsFilter) -> SideBreakdown: ...
    def equity_curve(self, filter: StatsFilter) -> EquityCurveResponse: ...
    def distribution(self, filter: StatsFilter) -> DistributionResponse: ...

    def _load_closed_positions(self, filter: StatsFilter) -> _LoadResult:
        """Load + bucket positions in scope.

        Returns a private _LoadResult dataclass with three lists:
          - closed_with_pnl: closed positions ready to aggregate
          - closed_missing_multiplier: closed but dollars_pnl is None (Decision 3)
          - open: open positions, excluded per AC 2
        """
```

**The hot loop** lives in `_load_closed_positions`:
1. `SELECT DISTINCT account, instrument FROM executions WHERE (filter clauses if any)` — gather pairs in scope
2. For each pair: load executions for that pair, call `services.positions.build_positions(executions)` (Plan 11), extend the result list
3. Filter to closed positions whose **session date of `entry_time`** falls inside `[filter.from_date, filter.to_date]`
4. Bucket into the three lists

**No SQL inside route handlers.** Routes parse the query string into a `StatsFilter`, dispatch to the service, jsonify the result. Same Rule 2 pattern as Plans 11/12/14.

**No caching layer.** AC 11 makes this explicit. If profiling ever proves stats are slow, the memoization cache described in doc 11 applies first; stats inherit it transparently.

### Pure aggregation helpers

A separate module `services/statistics_aggregations.py` holds the math. Each function is pure: takes a `list[Position]` (and possibly a parameter or two), returns a typed result, no I/O, no globals, no clock.

```python
def compute_summary(positions: list[Position], commission_total: float) -> _SummaryFields: ...
def bucket_by_session_date(positions: list[Position], granularity: Literal["day", "week", "month"]) -> list[TimeBucket]: ...
def bucket_by_hour(positions: list[Position], display_tz: ZoneInfo) -> list[HourBucket]: ...
def cumulative_equity(positions: list[Position]) -> list[EquityPoint]: ...
def pnl_histogram(positions: list[Position], n_buckets: int = 10) -> list[HistogramBucket]: ...
def split_by_side(positions: list[Position]) -> tuple[list[Position], list[Position]]: ...
def per_instrument(positions: list[Position]) -> list[InstrumentStats]: ...
def longest_streaks(positions: list[Position]) -> tuple[int, int]: ...  # (win streak, loss streak)
```

Each helper is unit-tested in isolation in `tests/test_statistics_aggregations.py`. The `StatisticsService` itself is integration-tested against an in-memory SQLite db in `tests/test_statistics_service.py`. The route layer is integration-tested in `tests/test_routes_stats.py`.

### Filter model

```python
class StatsFilter(StrictModel):
    account: str | None = None
    from_date: date | None = None  # inclusive, session date
    to_date: date | None = None    # inclusive, session date
```

Conversion from query-string ISO `YYYY-MM-DD` strings happens in a route helper `_parse_stats_filter(args) -> StatsFilter`. Mirrors Plan 12's `_parse_filter_from_query` for positions.

---

## Data models and API surface

Nine endpoints. Response models live in `models/statistics.py` and re-export from `models/__init__.py`.

| Endpoint | Service method | Response model |
|---|---|---|
| `GET /api/stats/summary` | `summary(filter)` | `StatsSummary` |
| `GET /api/stats/by-instrument` | `by_instrument(filter)` | `InstrumentBreakdown` |
| `GET /api/stats/by-day` | `by_day(filter)` | `TimeBucketResponse` |
| `GET /api/stats/by-week` | `by_week(filter)` | `TimeBucketResponse` |
| `GET /api/stats/by-month` | `by_month(filter)` | `TimeBucketResponse` |
| `GET /api/stats/by-hour` | `by_hour(filter)` | `HourBucketResponse` |
| `GET /api/stats/by-side` | `by_side(filter)` | `SideBreakdown` |
| `GET /api/stats/equity-curve` | `equity_curve(filter)` | `EquityCurveResponse` |
| `GET /api/stats/distribution` | `distribution(filter)` | `DistributionResponse` |

### `StatsSummary`

Carries every AC-3 field plus the Decision-3 additions:

```python
class StatsSummary(StrictModel):
    total_positions: int
    total_pnl: float
    wins: int
    losses: int
    scratches: int
    win_rate: float | None         # null if wins + losses == 0
    avg_win: float | None          # null if wins == 0
    avg_loss: float | None         # null if losses == 0 (negative when present)
    profit_factor: float | None    # null if losses == 0
    largest_win: float | None      # null if wins == 0
    largest_loss: float | None     # null if losses == 0 (negative)
    longest_win_streak: int
    longest_loss_streak: int
    avg_hold_minutes: float | None
    median_hold_minutes: float | None
    avg_position_size: float | None
    open_positions: int            # count of currently-open positions in filter scope
    skipped_no_multiplier: int     # Decision 3: closed positions with null dollars_pnl
```

### Other response models

```python
class InstrumentStats(StrictModel):
    instrument: str
    position_count: int
    total_pnl: float
    win_rate: float | None
    avg_pnl_per_position: float

class InstrumentBreakdown(StrictModel):
    rows: list[InstrumentStats]

class TimeBucket(StrictModel):
    bucket: str            # "2026-04-13" for day, "2026-W15" for week, "2026-04" for month
    position_count: int
    total_pnl: float

class TimeBucketResponse(StrictModel):
    granularity: Literal["day", "week", "month"]
    buckets: list[TimeBucket]   # always continuous: empty buckets within the filter range are zero-filled

class HourBucket(StrictModel):
    hour: int              # 0..23, in display_timezone
    position_count: int
    total_pnl: float

class HourBucketResponse(StrictModel):
    timezone: str          # IANA name, e.g. "America/Chicago"
    buckets: list[HourBucket]   # always 24 entries

class SideStats(StrictModel):
    position_count: int
    total_pnl: float
    win_rate: float | None

class SideBreakdown(StrictModel):
    long: SideStats
    short: SideStats

class EquityPoint(StrictModel):
    time: int              # unix seconds, the position's exit_time
    cumulative_pnl: float

class EquityCurveResponse(StrictModel):
    points: list[EquityPoint]   # ordered by exit_time ascending

class HistogramBucket(StrictModel):
    bucket_min: float
    bucket_max: float
    count: int

class DistributionResponse(StrictModel):
    buckets: list[HistogramBucket]   # 10 buckets, edges from min..max of filtered positions
    bucket_count: int                # always 10
```

### Common query string

Every endpoint accepts the same three optional query params:

| Param | Type | Notes |
|---|---|---|
| `account` | string | Exact match on `executions.account`. Omitted = all accounts. |
| `from` | ISO `YYYY-MM-DD` | Inclusive session date. Omitted = all-time. |
| `to` | ISO `YYYY-MM-DD` | Inclusive session date. Omitted = all-time. |

### Definitions (verbatim from doc 15)

These are referenced by every aggregation. They live in `services/outcomes.py` (Plan 12) — Plan 15 reuses `classify_outcome` and the constants.

- **Winner**: closed position with `dollars_pnl > commission`
- **Loser**: closed position with `dollars_pnl < -commission`
- **Scratch**: closed position with `|dollars_pnl| <= commission`
- **Win rate**: `count(winners) / (count(winners) + count(losers))`. Null if both are zero.
- **Profit factor**: `sum(winners.dollars_pnl) / abs(sum(losers.dollars_pnl))`. Null if no losers.
- **Average win**: `sum(winners.dollars_pnl) / count(winners)`
- **Average loss**: `sum(losers.dollars_pnl) / count(losers)` (negative)
- **Equity curve**: cumulative sum of `dollars_pnl` over closed positions ordered by `exit_time`
- **Session date**: `services/time_utils.py::compute_session_date(ts_utc)` — applies the 16:00 America/Chicago rollover. **All date bucketing uses this**, never raw calendar `entry_time.date()`.

---

## Frontend layout

Two pages, both server-rendered shell templates extending Plan 12's `base.html`. Each page is a thin Jinja shell + an ES module that fetches the JSON endpoints and renders the sections.

### Routes (page-rendering)

Both registered on `routes/pages.py`:

```python
@bp.get("/statistics")
def statistics_page():
    return render_template("statistics.html")

@bp.get("/reports")
def reports_page():
    return render_template("reports.html")
```

### `templates/statistics.html` — bento dashboard

```html
{% extends "base.html" %}
{% block extra_styles %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/stats.css') }}">
{% endblock %}
{% block content %}
  <body class="stats-page">
    <div id="stats-root">
      <div id="stats-filter-bar"></div>
      <div class="bento-grid">
        <section id="stats-summary" class="bento-cell bento-2x1"></section>
        <section id="stats-by-side" class="bento-cell bento-1x1"></section>
        <section id="stats-equity" class="bento-cell bento-2x1"></section>
        <section id="stats-by-instrument" class="bento-cell bento-1x1"></section>
        <section id="stats-by-day" class="bento-cell bento-1x1"></section>
        <section id="stats-by-hour" class="bento-cell bento-1x1"></section>
      </div>
    </div>
  </body>
{% endblock %}
{% block scripts %}
  <script src="{{ url_for('static', filename='vendor/lightweight-charts.standalone.production.js') }}"></script>
  <script type="module" src="{{ url_for('static', filename='js/statistics.js') }}"></script>
{% endblock %}
```

The bento grid is implemented in `stats.css` as a CSS Grid with `grid-template-columns: 2fr 1fr` and three rows. The `bento-2x1` and `bento-1x1` classes set `grid-column: span 2` / `span 1`.

### `templates/reports.html` — single-column deep dive

```html
{% extends "base.html" %}
{% block extra_styles %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/stats.css') }}">
{% endblock %}
{% block content %}
  <body class="reports-page">
    <div id="reports-root">
      <div id="stats-filter-bar"></div>
      <section id="reports-calendar"></section>
      <section id="reports-equity"></section>
      <div class="reports-row-2col">
        <section id="reports-by-week"></section>
        <section id="reports-by-month"></section>
      </div>
      <section id="reports-distribution"></section>
    </div>
  </body>
{% endblock %}
{% block scripts %}
  <script src="{{ url_for('static', filename='vendor/lightweight-charts.standalone.production.js') }}"></script>
  <script type="module" src="{{ url_for('static', filename='js/reports.js') }}"></script>
{% endblock %}
```

### New static JS files

| File | Purpose |
|---|---|
| `static/js/stats_filter.js` | Pure URL/DOM helpers: `parseFilterFromUrl()`, `writeFilterToUrl(f)`, `renderFilterBar(container, filter, onApply)`, `currentAccountOptions(callback)`. Reused by both pages. |
| `static/js/stats_charts.js` | Three exports: `mountLineChart(container, points, opts)`, `mountHistogramChart(container, buckets, opts)`, `mountCalendarHeatmap(container, dailyData, opts)`. First two wrap Lightweight Charts; third is hand-rolled CSS Grid. |
| `static/js/statistics.js` | The `/statistics` page module. Reads URL filter, fetches the seven endpoints in parallel via `Promise.all`, renders each bento cell. Listens to `popstate`. |
| `static/js/reports.js` | The `/reports` page module. Same pattern, fetches the four endpoints it needs. |

### New CSS file

`static/css/stats.css` (~250 lines) holds every Plan 15 visual rule. Loaded via the `{% block extra_styles %}` hook added to `templates/base.html`. The existing minimal CSS in `base.html` is untouched — Plan 15's styles scope themselves with `.stats-page` / `.reports-page` body classes.

---

## Visual specification

### Color palette

```css
:root {
  --bg-page: #0f1419;
  --bg-card: #1e293b;
  --border-card: #334155;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;

  --accent: #8b5cf6;          /* primary purple */
  --accent-soft: rgba(139, 92, 246, 0.15);

  --pos: #10b981;             /* emerald 500 */
  --pos-text: #6ee7b7;        /* emerald 300, used on dark backgrounds */
  --pos-bg-1: rgba(16, 185, 129, 0.10);
  --pos-bg-2: rgba(16, 185, 129, 0.20);
  --pos-bg-3: rgba(16, 185, 129, 0.35);
  --pos-bg-4: rgba(16, 185, 129, 0.55);

  --neg: #f43f5e;             /* rose 500 */
  --neg-text: #fda4af;        /* rose 300 */
  --neg-bg-1: rgba(244, 63, 94, 0.10);
  --neg-bg-2: rgba(244, 63, 94, 0.25);
  --neg-bg-3: rgba(244, 63, 94, 0.45);
}
```

### Typography

System sans-serif stack only — no web font download:

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
```

Numbers use `font-variant-numeric: tabular-nums` so columns align cleanly.

### Card style

All sections sit inside cards with:

```css
.bento-cell, #reports-calendar, #reports-equity, .reports-row-2col > section, #reports-distribution {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  padding: 18px;
}
```

Section labels are uppercase 11px with `letter-spacing: 0.06em` and `color: var(--text-secondary)`. Numbers are 24px bold.

### Bento grid for `/statistics`

```
+--------------------------------+----------+
|         Summary card           | By side  |
|         (4-col grid)           |  L / S   |
+--------------------------------+----------+
|       Equity curve             | Instr.   |
|       (line chart)             |  table   |
+----------------+---------------+----------+
|    By day      |   By hour     |          |
|   (histogram)  |  (histogram)  |    -     |
+----------------+---------------+----------+
```

```css
.bento-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 16px;
}
.bento-2x1 { grid-column: span 2; }
.bento-1x1 { grid-column: span 1; }
```

Top row: `#stats-summary` spans 2 columns, `#stats-by-side` 1. Middle row: `#stats-equity` 2, `#stats-by-instrument` 1. Bottom row: `#stats-by-day` 1, `#stats-by-hour` 1, third slot empty for now.

### Calendar heatmap (Style C from brainstorm)

CSS Grid, 7 columns per month (Sun..Sat). Each cell has min-height 70px and shows three pieces of info: the day-of-month number, the dollar P&L (`+$890` or `-$320`), and the trade count (`8 trades`). Empty cells (no trades on that session date) get a faint border with no fill.

Color scale: 4 win shades + 3 loss shades + neutral. Cells use `linear-gradient(135deg, ...)` for an extra polished look:

```css
.cal-day.win-1 { background: linear-gradient(135deg, var(--pos-bg-1), rgba(16, 185, 129, 0.05)); border-color: rgba(16, 185, 129, 0.25); }
.cal-day.win-2 { background: linear-gradient(135deg, var(--pos-bg-2), var(--pos-bg-1)); border-color: rgba(16, 185, 129, 0.45); }
.cal-day.win-3 { background: linear-gradient(135deg, var(--pos-bg-3), var(--pos-bg-2)); border-color: rgba(16, 185, 129, 0.60); }
.cal-day.win-4 { background: linear-gradient(135deg, var(--pos-bg-4), var(--pos-bg-3)); border-color: rgba(16, 185, 129, 0.80); }
/* same pattern for loss-1..3 */
```

Bucketing into the 8 levels happens client-side in `mountCalendarHeatmap`: compute the absolute max of the month's daily P&L, then bucket each day's value as a fraction of that max into one of (win-4, win-3, win-2, win-1, neutral, loss-1, loss-2, loss-3).

**Cells are clickable.** Clicking a day navigates to the positions list filtered to the trades that were taken on that **session date** — not the calendar date of `entry_time`. This is important: the calendar buckets positions by `compute_session_date(entry_time)`, so a position opened at 17:00 Chicago time on Jan 2 belongs to the Jan 3 session, and clicking the Jan 3 cell must include it.

Plan 12's existing `/positions` filter uses `entry_time_min` / `entry_time_max` (unix-second range), which is calendar-aligned, not session-aligned. Plan 15 needs the click to land on the right set. Two options for the plan to choose between when it is written:

- **(A) Compute the unix-second window in JS** before navigating: take the clicked session date, apply the 16:00 America/Chicago rollover rule (or whatever `display_timezone` says), and pass the resulting `entry_time_min` / `entry_time_max` to `/positions`. No backend change.
- **(B) Add a `session_date` query param to `/positions`** that does the conversion server-side via `compute_session_date`. This is the cleaner long-term API but requires modifying `routes/positions.py` and `services/position_filters.py`.

I'd recommend **(B)** — it keeps the session-date concept in one place (the time-utils module), avoids reimplementing the rollover rule in JavaScript, and gives a future Plan 17 (monitoring) the same primitive for free. The plan-writing step should pick this and add the `session_date` filter to Plan 12's existing filter as a small additive change. Total cost: ~10 lines in `position_filters.py`, a parser line in `routes/positions.py`, and one test.

### Filter bar

Sticky at the top of both pages, full width:

```html
<div id="stats-filter-bar" class="filter-bar">
  <label>Account
    <select id="filter-account">
      <option value="">All accounts</option>
      <!-- populated from /api/positions/filters -->
    </select>
  </label>
  <label>From
    <input type="date" id="filter-from">
  </label>
  <label>To
    <input type="date" id="filter-to">
  </label>
  <button id="filter-apply">Apply</button>
  <button id="filter-clear">Clear</button>
</div>
```

```css
.filter-bar {
  position: sticky;
  top: 0;
  background: var(--bg-page);
  border-bottom: 1px solid var(--border-card);
  padding: 12px 16px;
  display: flex;
  gap: 12px;
  align-items: end;
  z-index: 10;
}
```

Active filter (any non-default param set) makes the Apply button background `var(--accent)`.

### Empty states

Every chart and section renders a "No data for this filter" placeholder when its endpoint returns zero rows. No "Loading..." spinner — initial paint shows skeleton boxes; on filter change, sections fade to `opacity: 0.5` until the new data arrives.

---

## Testing

| File | Purpose |
|---|---|
| `tests/test_statistics_aggregations.py` | Pure-function unit tests for every helper in `services/statistics_aggregations.py`. No DB, no Flask. Tests cover: empty input, single position, win/loss/scratch classification, win-rate edge cases (all wins, all losses, all scratches, mixed), profit-factor null handling, longest streak, hour bucketing across timezones, day/week/month bucketing across DST and the 16:00 session rollover, equity curve ordering by `exit_time`, P&L histogram bucket edges. |
| `tests/test_statistics_service.py` | Integration tests against an in-memory SQLite DB seeded with realistic execution rows. One test per public method on `StatisticsService`. Covers filter scoping (account, from-date, to-date), the three-bucket return from `_load_closed_positions`, and the `skipped_no_multiplier` count. |
| `tests/test_routes_stats.py` | Route-level integration tests. One test per endpoint. Covers: query string parsing, error responses (invalid date format, unknown account → empty results not error), the JSON response shape matches each Pydantic model, both the `with-account` and `without-account` paths. |
| `tests/test_app_factory_plan15.py` | App-factory smoke test (same pattern as Plans 12 and 13). Spins up `create_app(...)`, asserts all 9 stats routes are reachable, asserts `/statistics` and `/reports` page routes return 200, asserts `/static/css/stats.css` and the four new JS files are served. |

No JS unit tests (same as Plan 13). Pure helpers in `stats_filter.js` and `stats_charts.js` are factored at module top level so a future plan can add a JS test runner without rewriting.

---

## File layout

```
/
├── migrations/                              # NO new migrations
├── models/
│   ├── statistics.py                        # NEW: all stats response models
│   └── __init__.py                          # MODIFY: export new models
├── services/
│   ├── statistics.py                        # NEW: StatisticsService class
│   └── statistics_aggregations.py           # NEW: pure aggregation helpers
├── routes/
│   ├── stats.py                             # NEW: 9 GET endpoints + filter parser
│   └── pages.py                             # MODIFY: add /statistics and /reports page routes
├── templates/
│   ├── base.html                            # MODIFY: add {% block extra_styles %} hook
│   ├── statistics.html                      # NEW: bento dashboard shell
│   └── reports.html                         # NEW: reports hub shell
├── static/
│   ├── css/
│   │   └── stats.css                        # NEW: ~250 lines, the full visual spec
│   └── js/
│       ├── stats_filter.js                  # NEW: shared filter bar module
│       ├── stats_charts.js                  # NEW: line/histogram/calendar wrappers
│       ├── statistics.js                    # NEW: dashboard page module
│       └── reports.js                       # NEW: reports page module
├── config.py                                # MODIFY: add display_timezone field
├── app.py                                   # MODIFY: register stats blueprint
├── data/config/app.json                     # NO change (display_timezone optional)
└── tests/
    ├── test_statistics_aggregations.py      # NEW: pure helper unit tests
    ├── test_statistics_service.py           # NEW: service integration tests
    ├── test_routes_stats.py                 # NEW: route integration tests
    └── test_app_factory_plan15.py           # NEW: app factory smoke
```

Total: 4 NEW Python files + 4 NEW test files, 4 NEW JS files, 2 NEW HTML templates, 1 NEW CSS file, 4 MODIFIED files (`models/__init__.py`, `routes/pages.py`, `templates/base.html`, `config.py`, `app.py`). No new migrations. No new dependencies in `requirements.txt`.

---

## What this plan deliberately does NOT do

- **No `chart_defaults` table or settings page** — Plan 16's surface
- **No second JS chart library** — reuse Plan 13's vendored Lightweight Charts; calendar heatmap is hand-rolled CSS Grid
- **No JS unit-test runner** — pure helpers are factored to module top so a future plan can add one
- **No statistics caching layer** — AC 11 is explicit; rely on doc 11's memoization if profiling ever proves it's needed
- **No new endpoint families beyond `/api/stats/*`** — no chart sharing, no PDF export, no email reports
- **No printable / PDF-friendly mode for `/reports`** — out of scope; the page is for screen viewing only
- **No real-time push** — stats are computed on demand per request, no SSE, no websocket
- **No cohort analysis, no Sharpe ratio, no risk-adjusted metrics** — these belong to a future "advanced statistics" plan if they're ever wanted
- **No new config keys beyond `display_timezone`**

---

## Open questions for plan-writing

These should be resolved by `superpowers:writing-plans` while it walks the doc-15 acceptance criteria:

1. **Empty-bucket fill rule for `by_week` and `by_month`.** Doc says "continuous timeline" — confirm whether a 6-month range with no September trades returns a row for September with `position_count: 0, total_pnl: 0` (yes per spirit of AC 5), or skips it. Plan should pick "always continuous" to match `by_day`.

2. **Definition of "month" and "week" buckets.** ISO week (Monday start) or Sunday-first week? The natural choice is ISO week with Monday start, but the calendar heatmap renders Sunday-first per US convention. The two are independent — bucketing math vs. calendar grid. Plan should pick ISO week for `by_week` keys (`"2026-W15"`) but render Sunday-first in the calendar.

3. **Equity curve x-axis time.** AC says ordered by `exit_time`; one point per closed position. The Lightweight Charts line series wants unix seconds — match that. Confirm this is fine for very-active days with many positions per minute.

4. **`/api/positions/filters`** already exists from Plan 12 and returns `{accounts: [...], instruments: [...]}`. The stats filter bar reuses it for the account dropdown. No new endpoint needed.

5. **Permissions / multi-user** — out of scope; this is a single-user app (Rule 1).

6. **Calendar cell click target** — see the visual spec section "Calendar heatmap (Style C from brainstorm)". The plan should adopt option (B): add a `session_date` query param to Plan 12's existing positions filter so the click navigates to `/positions?session_date=YYYY-MM-DD` (or a session-date range for week/month aggregations later). This keeps the rollover-rule logic in `services/time_utils.py` instead of reimplementing it in JS.
