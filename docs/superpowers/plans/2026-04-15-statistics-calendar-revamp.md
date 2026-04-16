# Statistics & Calendar Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicate content between Statistics and Reports pages, fix the by-hour bug, add Long/Short depth stats and two new analysis tables (by day-of-week, trades-per-day), and replace Reports with a Calendar page whose by-week/by-month charts scale gracefully.

**Architecture:** Backend adds one new endpoint (`by-day-of-week`) and extends the `SideStats` model. All other backend endpoints are unchanged. Frontend rewrites `statistics.js` and replaces `reports.js` with `calendar.js`; `stats_charts.js` gains one new export (`mountLcHistogram`). The Reports route is renamed to `/calendar`.

**Tech Stack:** Flask, SQLite, Pydantic v2 (StrictModel), vanilla ES modules, LightweightCharts v4.2.3

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `models/statistics.py` | Modify | Add `avg_win/avg_loss/profit_factor` to `SideStats`; add `DayOfWeekBucket`/`DayOfWeekResponse` |
| `services/statistics_aggregations.py` | Modify | Add `bucket_by_day_of_week()` pure function |
| `services/statistics.py` | Modify | Update `_side_stats()`, add `by_day_of_week()` |
| `routes/stats.py` | Modify | Register `GET /api/stats/by-day-of-week` |
| `routes/pages.py` | Modify | Rename `/reports` → `/calendar` |
| `tests/test_statistics_aggregations.py` | Modify | Tests for `bucket_by_day_of_week` |
| `tests/test_statistics_service.py` | Modify | Test for `by_day_of_week()` service method |
| `templates/statistics.html` | Modify | Remove `stats-by-day`; add `stats-by-dow`, `stats-trades-per-day` |
| `templates/reports.html` | Delete | Replaced by `calendar.html` |
| `templates/calendar.html` | Create | Calendar page template |
| `static/js/statistics.js` | Modify | Full render overhaul |
| `static/js/reports.js` | Delete | Replaced by `calendar.js` |
| `static/js/calendar.js` | Create | Calendar page JS |
| `static/js/stats_charts.js` | Modify | Add `mountLcHistogram()` |
| `static/css/stats.css` | Modify | Add `.side-grid`/`.side-col`/`.side-stat` layout; remove stale `#reports-equity` rule |
| `templates/base.html` | Modify | Rename nav link "Reports" → "Calendar", update href |

---

## Task 1: Extend SideStats model

**Files:**
- Modify: `models/statistics.py`

- [ ] **Step 1: Add three optional fields to SideStats**

Open `models/statistics.py`. Replace the `SideStats` class (lines 69-72):

```python
class SideStats(StrictModel):
    position_count: int
    total_pnl: float
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    profit_factor: float | None
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```
pytest tests/test_statistics_service.py::test_by_side tests/test_statistics_aggregations.py -v
```

Expected: all PASS (existing `test_by_side` only checks `position_count`, not the new fields).

- [ ] **Step 3: Update `_side_stats()` in services/statistics.py**

`compute_summary` already returns `avg_win`, `avg_loss`, and `profit_factor`. Replace the `_side_stats` function at the bottom of `services/statistics.py` (currently lines 217–223):

```python
def _side_stats(positions: list[Position]) -> SideStats:
    s = compute_summary(positions)
    return SideStats(
        position_count=s.total_positions,
        total_pnl=s.total_pnl,
        win_rate=s.win_rate,
        avg_win=s.avg_win,
        avg_loss=s.avg_loss,
        profit_factor=s.profit_factor,
    )
```

- [ ] **Step 4: Run tests again**

```
pytest tests/test_statistics_service.py::test_by_side -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add models/statistics.py services/statistics.py
git commit -m "feat: extend SideStats with avg_win, avg_loss, profit_factor"
```

---

## Task 2: Add DayOfWeek models

**Files:**
- Modify: `models/statistics.py`

- [ ] **Step 1: Append two new models to models/statistics.py**

Add after the `DistributionResponse` class at the end of the file:

```python
class DayOfWeekBucket(StrictModel):
    dow: int           # 0=Mon … 4=Fri
    day_name: str      # "Mon" … "Fri"
    trading_days: int  # unique session dates for this weekday
    trades: int
    avg_pnl: float     # total_pnl / trading_days, 0.0 when trading_days == 0
    win_rate: float | None
    total_pnl: float


class DayOfWeekResponse(StrictModel):
    buckets: list[DayOfWeekBucket]  # always 5 rows, Mon–Fri order
```

- [ ] **Step 2: Verify import is clean**

```
python -c "from models.statistics import DayOfWeekBucket, DayOfWeekResponse; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add models/statistics.py
git commit -m "feat: add DayOfWeekBucket and DayOfWeekResponse models"
```

---

## Task 3: Implement bucket_by_day_of_week (TDD)

**Files:**
- Modify: `tests/test_statistics_aggregations.py`
- Modify: `services/statistics_aggregations.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_statistics_aggregations.py`:

```python
from services.statistics_aggregations import bucket_by_day_of_week  # noqa: E402


# Timestamps (all 09:00 UTC, before 16:00 CDT rollover, so session date == calendar date):
# 1776070800 = 2026-04-13 Mon (dow 0)  — confirmed by existing test_bucket_by_week_iso_week_keys
# 1776157200 = 2026-04-14 Tue (dow 1)
# 1776243600 = 2026-04-15 Wed (dow 2)  — confirmed by existing test_bucket_by_day_continuous_fill
# 1776330000 = 2026-04-16 Thu (dow 3)
# 1776416400 = 2026-04-17 Fri (dow 4)
# 1776675600 = 2026-04-20 Mon (dow 0)  — confirmed by existing test_bucket_by_week_continuous_two_weeks


def test_dow_always_returns_five_rows():
    result = bucket_by_day_of_week([])
    assert len(result) == 5
    assert [b.dow for b in result] == [0, 1, 2, 3, 4]
    assert [b.day_name for b in result] == ["Mon", "Tue", "Wed", "Thu", "Fri"]


def test_dow_empty_rows_zeroed():
    result = bucket_by_day_of_week([])
    assert all(b.trades == 0 for b in result)
    assert all(b.trading_days == 0 for b in result)
    assert all(b.total_pnl == 0.0 for b in result)
    assert all(b.avg_pnl == 0.0 for b in result)
    assert all(b.win_rate is None for b in result)


def test_dow_single_monday_position():
    positions = [_at(1776070800, eid="a", pnl=100.0)]
    result = bucket_by_day_of_week(positions)
    mon = result[0]
    assert mon.trades == 1
    assert mon.trading_days == 1
    assert mon.total_pnl == 100.0
    assert mon.avg_pnl == 100.0
    # Other days untouched
    assert all(b.trades == 0 for b in result[1:])


def test_dow_win_rate_and_avg_pnl_across_two_mondays():
    # Two Monday sessions: +100 and -50 → win_rate 0.5, avg_pnl 25.0
    positions = [
        _at(1776070800, eid="a", pnl=100.0),   # 2026-04-13 Mon
        _at(1776675600, eid="b", pnl=-50.0),   # 2026-04-20 Mon
    ]
    result = bucket_by_day_of_week(positions)
    mon = result[0]
    assert mon.trading_days == 2
    assert mon.trades == 2
    assert mon.total_pnl == pytest.approx(50.0)
    assert mon.avg_pnl == pytest.approx(25.0)
    assert mon.win_rate == pytest.approx(0.5)


def test_dow_win_rate_none_when_all_scratches():
    # commission == |pnl| → scratch → win_rate is None
    scratch = _pos(eid="s", entry_time=1776070800, exit_time=1776070860,
                   dollars_pnl=2.0, commission=2.0)
    result = bucket_by_day_of_week([scratch])
    assert result[0].win_rate is None


def test_dow_uses_session_date_not_entry_calendar_date():
    # 1776115800 = 2026-04-13 21:30 UTC = 16:30 CDT → session date 2026-04-14 (Tue)
    # Confirmed by existing test_bucket_uses_session_date_not_calendar
    positions = [_at(1776115800, eid="rollover", pnl=10.0)]
    result = bucket_by_day_of_week(positions)
    assert result[0].trades == 0   # Monday gets nothing
    assert result[1].trades == 1   # Tuesday gets the rollover trade


def test_dow_multiple_trades_same_day_count_as_one_trading_day():
    # Three trades all on 2026-04-13 (Mon) → trading_days == 1
    positions = [
        _at(1776070800, eid="a", pnl=10.0),
        _at(1776071400, eid="b", pnl=20.0),
        _at(1776072000, eid="c", pnl=30.0),
    ]
    result = bucket_by_day_of_week(positions)
    assert result[0].trading_days == 1
    assert result[0].trades == 3
    assert result[0].total_pnl == pytest.approx(60.0)
    assert result[0].avg_pnl == pytest.approx(60.0)  # 60 / 1 trading day


def test_dow_all_five_days():
    positions = [
        _at(1776070800, eid="mon", pnl=10.0),  # Mon
        _at(1776157200, eid="tue", pnl=20.0),  # Tue
        _at(1776243600, eid="wed", pnl=30.0),  # Wed
        _at(1776330000, eid="thu", pnl=40.0),  # Thu
        _at(1776416400, eid="fri", pnl=50.0),  # Fri
    ]
    result = bucket_by_day_of_week(positions)
    assert [b.trades for b in result] == [1, 1, 1, 1, 1]
    assert [b.total_pnl for b in result] == [10.0, 20.0, 30.0, 40.0, 50.0]
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_statistics_aggregations.py::test_dow_always_returns_five_rows -v
```

Expected: `ImportError` or `AttributeError` — `bucket_by_day_of_week` not yet defined.

- [ ] **Step 3: Implement bucket_by_day_of_week in services/statistics_aggregations.py**

Add these imports at the top of `services/statistics_aggregations.py` (after the existing imports):

```python
from models.statistics import (
    ...
    DayOfWeekBucket,
    DayOfWeekResponse,  # noqa — imported for re-export convenience
)
```

Actually `DayOfWeekResponse` is only used by the service, not here. Just add `DayOfWeekBucket`:

In `services/statistics_aggregations.py`, the import block starting at line 17 currently imports from `models.statistics`. Extend it to include `DayOfWeekBucket`:

```python
from models.statistics import (
    DayOfWeekBucket,
    EquityPoint,
    HistogramBucket,
    HourBucket,
    InstrumentStats,
    StatsSummary,
    TimeBucket,
)
```

Then append the function at the end of `services/statistics_aggregations.py`:

```python
_DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def bucket_by_day_of_week(positions: list[Position]) -> list[DayOfWeekBucket]:
    """Always returns 5 buckets (Mon–Fri), zero-filled for days with no trades.

    Uses session date (exchange-tz rollover) for weekday attribution so that
    a Sunday-evening entry at 17:00 CT maps to Monday, not Sunday.
    """
    pnl_sums = [0.0] * 5
    trade_counts = [0] * 5
    wins = [0] * 5
    losses = [0] * 5
    trading_day_sets: list[set] = [set() for _ in range(5)]

    for p in positions:
        sd = _session_date_of(p)
        dow = sd.weekday()  # 0=Mon … 6=Sun
        if dow > 4:  # skip weekend session dates (rare but possible)
            continue
        pnl_sums[dow] += p.dollars_pnl or 0.0
        trade_counts[dow] += 1
        trading_day_sets[dow].add(sd)
        outcome = classify_outcome(p)
        if outcome == "winner":
            wins[dow] += 1
        elif outcome == "loser":
            losses[dow] += 1

    result: list[DayOfWeekBucket] = []
    for dow in range(5):
        td = len(trading_day_sets[dow])
        w, l = wins[dow], losses[dow]
        result.append(
            DayOfWeekBucket(
                dow=dow,
                day_name=_DOW_NAMES[dow],
                trading_days=td,
                trades=trade_counts[dow],
                avg_pnl=pnl_sums[dow] / td if td > 0 else 0.0,
                win_rate=w / (w + l) if (w + l) > 0 else None,
                total_pnl=pnl_sums[dow],
            )
        )
    return result
```

- [ ] **Step 4: Run all new tests**

```
pytest tests/test_statistics_aggregations.py -k "dow" -v
```

Expected: all 8 `test_dow_*` tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest tests/test_statistics_aggregations.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_statistics_aggregations.py services/statistics_aggregations.py models/statistics.py
git commit -m "feat: add bucket_by_day_of_week aggregation with tests"
```

---

## Task 4: Wire by-day-of-week into service and route

**Files:**
- Modify: `services/statistics.py`
- Modify: `tests/test_statistics_service.py`
- Modify: `routes/stats.py`

- [ ] **Step 1: Add import and method to StatisticsService**

In `services/statistics.py`, extend the import from `models.statistics` (line 17–28) to include the new models:

```python
from models.statistics import (
    DayOfWeekResponse,
    DistributionResponse,
    EquityCurveResponse,
    EquitySeries,
    HourBucketResponse,
    InstrumentBreakdown,
    SideBreakdown,
    SideStats,
    StatsFilter,
    StatsSummary,
    TimeBucketResponse,
)
```

Extend the aggregations import (lines 31–39) to include `bucket_by_day_of_week`:

```python
from services.statistics_aggregations import (
    _session_date_of,
    bucket_by_day_of_week,
    bucket_by_hour,
    bucket_by_session_date,
    compute_summary,
    cumulative_equity,
    per_instrument,
    pnl_histogram,
    split_by_side,
)
```

Add the method to `StatisticsService` after the `distribution` method:

```python
def by_day_of_week(self, filter: StatsFilter) -> DayOfWeekResponse:
    loaded = self._load_closed_positions(filter)
    return DayOfWeekResponse(buckets=bucket_by_day_of_week(loaded.closed_with_pnl))
```

- [ ] **Step 2: Write a service-layer test**

Append to `tests/test_statistics_service.py`:

```python
def test_by_day_of_week(tmp_path):
    # Seeded position is on 2026-04-13 = Monday (dow 0)
    svc = _service(_fresh(tmp_path))
    r = svc.by_day_of_week(StatsFilter())
    assert len(r.buckets) == 5
    assert r.buckets[0].day_name == "Mon"
    assert r.buckets[0].trades == 1
    assert r.buckets[0].trading_days == 1
    # Other days have zero trades
    assert all(b.trades == 0 for b in r.buckets[1:])
```

- [ ] **Step 3: Run the test to verify it passes**

```
pytest tests/test_statistics_service.py::test_by_day_of_week -v
```

Expected: PASS.

- [ ] **Step 4: Register the endpoint in routes/stats.py**

In `routes/stats.py`, add inside `build_stats_blueprint()`, after the `distribution` route:

```python
@bp.get("/api/stats/by-day-of-week")
def by_day_of_week():
    return _dispatch("by_day_of_week")
```

- [ ] **Step 5: Verify the endpoint responds**

Start the app (`gunicorn -w 1 -b 0.0.0.0:8000 wsgi:app` or docker) and run:

```
curl -s http://localhost:8000/api/stats/by-day-of-week | python -m json.tool
```

Expected: JSON with `{"buckets": [...]}` containing 5 objects with `dow`, `day_name`, `trading_days`, `trades`, `avg_pnl`, `win_rate`, `total_pnl`.

- [ ] **Step 6: Commit**

```bash
git add services/statistics.py routes/stats.py tests/test_statistics_service.py
git commit -m "feat: add by-day-of-week service method and API endpoint"
```

---

## Task 5: Update statistics.html

**Files:**
- Modify: `templates/statistics.html`

- [ ] **Step 1: Replace the bento-grid contents**

Replace the full content of `templates/statistics.html`:

```html
{% extends "base.html" %}
{% block title %}Statistics — FuturesTradingLog{% endblock %}
{% block extra_styles %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/stats.css') }}">
{% endblock %}
{% block content %}
  <div id="stats-root" class="stats-page">
    <div id="stats-filter-bar"></div>
    <div class="bento-grid">
      <section id="stats-summary" class="bento-cell bento-2x1"></section>
      <section id="stats-by-side" class="bento-cell bento-1x1"></section>
      <section id="stats-equity" class="bento-cell bento-2x1"></section>
      <section id="stats-by-instrument" class="bento-cell bento-1x1"></section>
      <section id="stats-by-dow" class="bento-cell bento-1x1"></section>
      <section id="stats-by-hour" class="bento-cell bento-1x1"></section>
      <section id="stats-trades-per-day" class="bento-cell bento-1x1"></section>
      <section id="stats-distribution" class="bento-cell bento-1x1"></section>
    </div>
  </div>
{% endblock %}
{% block scripts %}
  <script src="{{ url_for('static', filename='vendor/lightweight-charts.standalone.production.js') }}"></script>
  <script type="module" src="{{ url_for('static', filename='js/statistics.js') }}"></script>
{% endblock %}
```

Changes from the previous template: `stats-by-day` removed; `stats-by-dow` and `stats-trades-per-day` added.

- [ ] **Step 2: Commit**

```bash
git add templates/statistics.html
git commit -m "feat: update statistics template – remove by-day, add by-dow and trades-per-day sections"
```

---

## Task 6: Add CSS for side-grid layout and clean up stats.css

**Files:**
- Modify: `static/css/stats.css`

- [ ] **Step 1: Add side-grid styles**

Append to `static/css/stats.css` (after the `.bar-top-value` block at the end):

```css
/* Long vs Short side-by-side layout */
.side-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.side-col {
  background: rgba(51, 65, 85, 0.25);
  border-radius: 6px;
  padding: 10px 12px;
}
.side-col-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.side-count {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
}
.side-stat {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  font-size: 12px;
}
.side-stat:last-child { border-bottom: none; }
.side-stat-label { color: var(--text-secondary); font-size: 11px; }
.side-stat-value { font-weight: 500; }
```

- [ ] **Step 2: Remove the stale #reports-equity rule and add body selector for calendar page**

Find and remove this rule (currently around line 246):
```css
#reports-equity .chart-container { height: 320px; }
```

Find the `body:has(.stats-page), body:has(.reports-page)` selector (currently line 28) and add `.calendar-page`:

```css
body:has(.stats-page),
body:has(.reports-page),
body:has(.calendar-page) {
  background: var(--bg-page);
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 3: Commit**

```bash
git add static/css/stats.css
git commit -m "style: add side-grid CSS for long/short section; add calendar-page body selector"
```

---

## Task 7: Rewrite statistics.js

**Files:**
- Modify: `static/js/statistics.js`

- [ ] **Step 1: Replace the full file**

```javascript
import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import {
  mountHistogramChart,
  mountLineChart,
} from "./stats_charts.js";

const ENDPOINTS = [
  "summary",
  "by-side",
  "equity-curve",
  "by-instrument",
  "by-day",         // still fetched: drives summary avg-day calc + trades-per-day table
  "by-hour",
  "distribution",
  "by-day-of-week",
];

async function fetchAll(filter) {
  const qs = filterToQueryString(filter);
  const responses = await Promise.all(
    ENDPOINTS.map((name) => fetch(`/api/stats/${name}${qs}`).then((r) => r.json())),
  );
  return Object.fromEntries(ENDPOINTS.map((n, i) => [n, responses[i]]));
}

function fmtMoney(v) {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtPercent(v) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtNum(v, digits = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toFixed(digits);
}

function _avgDayPnl(dayBuckets, positive) {
  const days = dayBuckets.filter(
    (b) => b.position_count > 0 && (positive ? b.total_pnl > 0 : b.total_pnl < 0),
  );
  if (!days.length) return null;
  return days.reduce((s, b) => s + b.total_pnl, 0) / days.length;
}

function renderSummary(container, summary, dayBuckets) {
  const avgWinDay = _avgDayPnl(dayBuckets, true);
  const avgLossDay = _avgDayPnl(dayBuckets, false);

  container.innerHTML = `
    <p class="section-label">Summary</p>
    <p class="big-number ${summary.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(summary.total_pnl)}</p>
    <div class="summary-grid">
      <div><div class="stat-label">Trades</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Win Rate</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Profit Factor</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Hold (min)</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Median Hold (min)</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Avg Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Largest Win</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Largest Loss</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Wins</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Losses</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Scratch</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Win Streak</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Loss Streak</div><div class="stat-value pnl-neg"></div></div>
      <div><div class="stat-label">Avg Size</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Open</div><div class="stat-value"></div></div>
      <div><div class="stat-label">Avg Win Day</div><div class="stat-value pnl-pos"></div></div>
      <div><div class="stat-label">Avg Loss Day</div><div class="stat-value pnl-neg"></div></div>
    </div>
  `;
  const values = container.querySelectorAll(".summary-grid .stat-value");
  values[0].textContent = String(summary.total_positions);
  values[1].textContent = fmtPercent(summary.win_rate);
  values[2].textContent = fmtNum(summary.profit_factor, 2);
  values[3].textContent = fmtNum(summary.avg_hold_minutes, 1);
  values[4].textContent = fmtNum(summary.median_hold_minutes, 1);
  values[5].textContent = fmtMoney(summary.avg_win);
  values[6].textContent = fmtMoney(summary.avg_loss);
  values[7].textContent = fmtMoney(summary.largest_win);
  values[8].textContent = fmtMoney(summary.largest_loss);
  values[9].textContent = String(summary.wins ?? 0);
  values[10].textContent = String(summary.losses ?? 0);
  values[11].textContent = String(summary.scratch_count ?? summary.scratches ?? 0);
  values[12].textContent = String(summary.longest_win_streak);
  values[13].textContent = String(summary.longest_loss_streak);
  values[14].textContent = fmtNum(summary.avg_position_size, 1);
  values[15].textContent = String(summary.open_positions);
  values[16].textContent = fmtMoney(avgWinDay);
  values[17].textContent = fmtMoney(avgLossDay);

  if (summary.skipped_no_multiplier > 0) {
    const warn = document.createElement("div");
    warn.className = "warning-row";
    warn.textContent = `${summary.skipped_no_multiplier} positions excluded — add their instruments to the multiplier registry.`;
    container.appendChild(warn);
  }
}

function renderBySide(container, breakdown) {
  function sideCol(label, s) {
    return `
      <div class="side-col">
        <div class="side-col-header">
          ${label}<span class="side-count">${s.position_count} trades</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Total P&L</span>
          <span class="side-stat-value ${s.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(s.total_pnl)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Win Rate</span>
          <span class="side-stat-value">${fmtPercent(s.win_rate)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Avg Win</span>
          <span class="side-stat-value pnl-pos">${fmtMoney(s.avg_win)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Avg Loss</span>
          <span class="side-stat-value pnl-neg">${fmtMoney(s.avg_loss)}</span>
        </div>
        <div class="side-stat">
          <span class="side-stat-label">Profit Factor</span>
          <span class="side-stat-value">${fmtNum(s.profit_factor, 2)}</span>
        </div>
      </div>
    `;
  }
  container.innerHTML = `
    <p class="section-label">Long vs Short</p>
    <div class="side-grid">
      ${sideCol("Long", breakdown.long)}
      ${sideCol("Short", breakdown.short)}
    </div>
  `;
}

function renderInstrumentTable(container, breakdown) {
  if (!breakdown.rows.length) {
    container.innerHTML =
      '<p class="section-label">By Instrument</p><div class="empty-state">No data</div>';
    return;
  }
  const rowsHtml = breakdown.rows
    .map(
      (r) => `
    <tr>
      <td>${r.instrument}</td>
      <td>${r.position_count}</td>
      <td class="${r.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.total_pnl)}</td>
      <td>${fmtPercent(r.win_rate)}</td>
      <td class="${r.avg_pnl_per_position >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(r.avg_pnl_per_position)}</td>
    </tr>
  `,
    )
    .join("");
  container.innerHTML = `
    <p class="section-label">By Instrument</p>
    <table class="instrument-table">
      <thead><tr><th>Instr</th><th>Trades</th><th>P&amp;L</th><th>Win %</th><th>Avg P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderDayOfWeek(container, dowData) {
  if (!dowData.buckets || dowData.buckets.every((b) => b.trades === 0)) {
    container.innerHTML =
      '<p class="section-label">By Day of Week</p><div class="empty-state">No data for this filter</div>';
    return;
  }
  const rowsHtml = dowData.buckets
    .map(
      (b) => `
    <tr>
      <td>${b.day_name}</td>
      <td>${b.trades}</td>
      <td class="${b.avg_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.avg_pnl)}</td>
      <td>${fmtPercent(b.win_rate)}</td>
      <td class="${b.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.total_pnl)}</td>
    </tr>
  `,
    )
    .join("");
  container.innerHTML = `
    <p class="section-label">By Day of Week</p>
    <table class="instrument-table">
      <thead><tr><th>Day</th><th>Trades</th><th>Avg P&amp;L</th><th>Win Rate</th><th>Total P&amp;L</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function renderTradesPerDay(container, byDayBuckets) {
  const buckets = _tradeCountBuckets(byDayBuckets);
  if (!buckets.length) {
    container.innerHTML =
      '<p class="section-label">Trades per Day</p><div class="empty-state">No data for this filter</div>';
    return;
  }
  const rowsHtml = buckets
    .map((b) => {
      const winPct = b.days > 0 ? Math.round((b.win_days / b.days) * 100) : 0;
      return `
      <tr>
        <td>${b.trades_per_day}</td>
        <td>${b.days}</td>
        <td class="${b.total_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtMoney(b.total_pnl)}</td>
        <td>${b.win_days}</td>
        <td>${winPct}%</td>
      </tr>
    `;
    })
    .join("");
  container.innerHTML = `
    <p class="section-label">Trades per Day</p>
    <table class="instrument-table">
      <thead><tr><th>Trades/Day</th><th>Days</th><th>Net P&amp;L</th><th>Win Days</th><th>Win %</th></tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function _tradeCountBuckets(byDayBuckets) {
  const map = new Map();
  for (const b of byDayBuckets) {
    if (b.position_count === 0) continue;
    const k = b.position_count;
    if (!map.has(k)) map.set(k, { trades_per_day: k, total_pnl: 0, days: 0, win_days: 0 });
    const entry = map.get(k);
    entry.total_pnl += b.total_pnl;
    entry.days += 1;
    if (b.total_pnl > 0) entry.win_days += 1;
  }
  return [...map.values()].sort((a, b) => a.trades_per_day - b.trades_per_day);
}

async function refresh(filter) {
  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "0.5"));
  const data = await fetchAll(filter);

  renderSummary(
    document.getElementById("stats-summary"),
    data["summary"],
    data["by-day"].buckets,
  );
  renderBySide(document.getElementById("stats-by-side"), data["by-side"]);
  renderInstrumentTable(document.getElementById("stats-by-instrument"), data["by-instrument"]);
  renderDayOfWeek(document.getElementById("stats-by-dow"), data["by-day-of-week"]);
  renderTradesPerDay(document.getElementById("stats-trades-per-day"), data["by-day"].buckets);

  const equityCard = document.getElementById("stats-equity");
  equityCard.innerHTML = '<p class="section-label">Equity Curve</p>';
  const equityHost = document.createElement("div");
  equityCard.appendChild(equityHost);
  mountLineChart(equityHost, data["equity-curve"].series);

  // Filter to hours that had trades — avoids 24-bar wall of zeros
  const activeHourBuckets = data["by-hour"].buckets.filter((b) => b.position_count > 0);
  const hourCard = document.getElementById("stats-by-hour");
  hourCard.innerHTML = `<p class="section-label">By Hour (${data["by-hour"].timezone})</p>`;
  const hourHost = document.createElement("div");
  hourCard.appendChild(hourHost);
  mountHistogramChart(hourHost, activeHourBuckets, { kind: "hour" });

  const distCard = document.getElementById("stats-distribution");
  distCard.innerHTML = '<p class="section-label">P&amp;L Distribution</p>';
  const distHost = document.createElement("div");
  distCard.appendChild(distHost);
  mountHistogramChart(distHost, data["distribution"].buckets, { kind: "distribution" });

  document.querySelectorAll(".bento-cell").forEach((c) => (c.style.opacity = "1"));
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
```

- [ ] **Step 2: Load /statistics in the browser and verify**

Check that:
- Long vs Short shows two cards with Avg Win / Avg Loss / Profit Factor (no bar)
- By Hour shows only hours with actual trades (not 24 bars)
- By Day of Week shows the 5-row table
- Trades per Day shows the table with Win Days and Win %
- No By Day bar chart appears
- Equity curve, By Instrument, and Distribution still render

- [ ] **Step 3: Commit**

```bash
git add static/js/statistics.js
git commit -m "feat: overhaul statistics.js – by-side expansion, by-hour fix, by-dow and trades-per-day tables"
```

---

## Task 8: Add mountLcHistogram to stats_charts.js

**Files:**
- Modify: `static/js/stats_charts.js`

- [ ] **Step 1: Append mountLcHistogram export**

Append to `static/js/stats_charts.js` (after the last line of `_formatPnl`):

```javascript
// LightweightCharts-based histogram for by-week and by-month on the Calendar
// page. `buckets` are TimeBucket objects ({bucket, position_count, total_pnl}).
// `toDateFn` converts the bucket key string to a "YYYY-MM-DD" date string.
export function mountLcHistogram(container, buckets, toDateFn) {
  container.innerHTML = "";
  const activeBuckets = (buckets || []).filter((b) => b.position_count > 0);
  if (!activeBuckets.length) {
    container.innerHTML = '<div class="empty-state">No data for this filter</div>';
    return null;
  }

  const wrap = document.createElement("div");
  wrap.className = "chart-container";
  container.appendChild(wrap);

  const chart = window.LightweightCharts.createChart(wrap, {
    ...CHART_DEFAULTS,
    width: wrap.clientWidth,
    height: wrap.clientHeight,
  });

  const series = chart.addHistogramSeries({
    priceFormat: { type: "price", precision: 0, minMove: 1 },
  });

  const data = activeBuckets
    .map((b) => ({
      time: toDateFn(b.bucket),
      value: b.total_pnl,
      color: b.total_pnl >= 0 ? "#22c55e" : "#f87171",
    }))
    .sort((a, b) => (a.time < b.time ? -1 : 1));

  series.setData(data);
  chart.timeScale().fitContent();

  new ResizeObserver(() => {
    chart.applyOptions({ width: wrap.clientWidth, height: wrap.clientHeight });
  }).observe(wrap);

  return chart;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/js/stats_charts.js
git commit -m "feat: add mountLcHistogram to stats_charts for scalable week/month charts"
```

---

## Task 9: Create calendar.html and calendar.js

**Files:**
- Create: `templates/calendar.html`
- Create: `static/js/calendar.js`

- [ ] **Step 1: Create templates/calendar.html**

```html
{% extends "base.html" %}
{% block title %}Calendar — FuturesTradingLog{% endblock %}
{% block extra_styles %}
  <link rel="stylesheet" href="{{ url_for('static', filename='css/stats.css') }}">
{% endblock %}
{% block content %}
  <div id="calendar-root" class="calendar-page">
    <div id="stats-filter-bar"></div>
    <section id="calendar-heatmap"></section>
    <div class="reports-row-2col">
      <section id="calendar-by-week"></section>
      <section id="calendar-by-month"></section>
    </div>
  </div>
{% endblock %}
{% block scripts %}
  <script src="{{ url_for('static', filename='vendor/lightweight-charts.standalone.production.js') }}"></script>
  <script type="module" src="{{ url_for('static', filename='js/calendar.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create static/js/calendar.js**

```javascript
import {
  parseFilterFromUrl,
  filterToQueryString,
  renderFilterBar,
} from "./stats_filter.js";
import { mountCalendarHeatmap, mountLcHistogram } from "./stats_charts.js";

const ENDPOINTS = ["by-day", "by-week", "by-month"];

async function fetchAll(filter) {
  const qs = filterToQueryString(filter);
  const responses = await Promise.all(
    ENDPOINTS.map((name) => fetch(`/api/stats/${name}${qs}`).then((r) => r.json())),
  );
  return Object.fromEntries(ENDPOINTS.map((n, i) => [n, responses[i]]));
}

// "2026-W16" → "2026-04-13" (Monday of that ISO week)
function isoWeekToDate(bucket) {
  const [yearStr, weekStr] = bucket.split("-W");
  const year = parseInt(yearStr, 10);
  const week = parseInt(weekStr, 10);
  // Jan 4 is always in ISO week 1; find Monday of W1, then offset.
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Dow = jan4.getUTCDay() || 7; // convert Sun=0 to 7
  const w1Monday = new Date(jan4.getTime() - (jan4Dow - 1) * 86400000);
  const monday = new Date(w1Monday.getTime() + (week - 1) * 7 * 86400000);
  return monday.toISOString().slice(0, 10);
}

async function refresh(filter) {
  const data = await fetchAll(filter);

  mountCalendarHeatmap(document.getElementById("calendar-heatmap"), data["by-day"].buckets, {
    title: "Daily P&L Calendar",
  });

  const weekCard = document.getElementById("calendar-by-week");
  weekCard.innerHTML = '<p class="section-label">By Week</p>';
  const weekHost = document.createElement("div");
  weekCard.appendChild(weekHost);
  mountLcHistogram(weekHost, data["by-week"].buckets, isoWeekToDate);

  const monthCard = document.getElementById("calendar-by-month");
  monthCard.innerHTML = '<p class="section-label">By Month</p>';
  const monthHost = document.createElement("div");
  monthCard.appendChild(monthHost);
  // "2026-04" → "2026-04-01"
  mountLcHistogram(monthHost, data["by-month"].buckets, (b) => b + "-01");
}

const initial = parseFilterFromUrl();
renderFilterBar(document.getElementById("stats-filter-bar"), initial, refresh);
refresh(initial);
```

- [ ] **Step 3: Commit**

```bash
git add templates/calendar.html static/js/calendar.js
git commit -m "feat: add calendar page template and JS (replaces reports)"
```

---

## Task 10: Wire calendar route, update navigation, delete reports files

**Files:**
- Modify: `routes/pages.py`
- Modify: `templates/base.html`
- Delete: `templates/reports.html`
- Delete: `static/js/reports.js`

- [ ] **Step 1: Rename the route in routes/pages.py**

Replace the `reports_page` function:

```python
@bp.get("/calendar")
def calendar_page():
    return render_template("calendar.html")
```

- [ ] **Step 2: Update the nav link in templates/base.html**

Find the line:
```html
      <a href="/reports">Reports</a>
```

Replace it with:
```html
      <a href="/calendar">Calendar</a>
```

- [ ] **Step 3: Delete the replaced files**

```bash
git rm templates/reports.html static/js/reports.js
```

- [ ] **Step 4: Verify full test suite passes**

```
pytest -v
```

Expected: all tests PASS (no test references `/reports`, the deleted templates, or the old JS file).

- [ ] **Step 5: Load /calendar in the browser and verify**

Check that:
- The monthly P&L heatmap renders
- By Week shows an LC histogram (not the old CSS bars)
- By Month shows an LC histogram
- Filter bar works
- No equity curve, no instrument table, no performance summary

- [ ] **Step 6: Commit**

```bash
git add routes/pages.py templates/base.html
git commit -m "feat: rename /reports to /calendar; wire calendar route; remove old reports files"
```

---

## Self-review checklist

- [x] **Spec coverage:**
  - SideStats extended with avg_win/avg_loss/profit_factor ✓ (Task 1)
  - renderBySide shows new fields, no win-rate bar ✓ (Task 7)
  - By Hour filters to position_count > 0 ✓ (Task 7)
  - By Day bar chart removed from Statistics ✓ (Tasks 5, 7)
  - By Day of Week table — new endpoint + render ✓ (Tasks 2, 3, 4, 7)
  - Trades per Day table with win days + win% ✓ (Task 7)
  - Calendar page: heatmap + LC week/month charts ✓ (Tasks 8, 9)
  - Equity curve only on Statistics ✓ (reports.js removed)
  - By Instrument only on Statistics ✓ (calendar.js never fetches it)
  - /calendar route, nav link renamed ✓ (Task 10)

- [x] **Type consistency:**
  - `DayOfWeekBucket.avg_pnl` set to `0.0` when `trading_days == 0` ✓ (Task 3 implementation)
  - `bucket_by_day_of_week` imported into `statistics_aggregations.py` then into `statistics.py` ✓
  - `DayOfWeekResponse` imported in `statistics.py` ✓
  - `mountLcHistogram` exported from `stats_charts.js`, imported in `calendar.js` ✓
  - `isoWeekToDate` is local to `calendar.js`, used as `toDateFn` argument ✓

- [x] **No placeholders:** All steps contain full code.
