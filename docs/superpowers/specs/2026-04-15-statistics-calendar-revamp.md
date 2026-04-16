# Statistics & Calendar Revamp

**Date:** 2026-04-15  
**Status:** Approved

## Overview

Eliminate duplicate content between the Statistics and Reports pages, fix known bugs, and add new analytical sections. Reports is renamed to Calendar with a clear purpose split: Statistics answers *"How am I trading?"*, Calendar answers *"What happened when?"*

---

## Page 1: Statistics

### What stays

- Filter bar (account, date range, side) — unchanged
- Summary KPIs grid — unchanged (18 stats)
- Equity Curve (LightweightCharts line) — **only here, removed from Calendar**
- By Instrument table — unchanged (instrument, trades, P&L, win%, avg P&L)
- P&L Distribution histogram — unchanged

### What changes

#### Long vs Short (expanded)
Currently shows: total P&L, trade count, win rate per side.

Add to `SideStats` model and `_side_stats()` helper:
- `avg_win: float | None`
- `avg_loss: float | None`
- `profit_factor: float | None`

UI: side-by-side stat cards (Long left, Short right). Each card shows:
- Trade count in the header
- Total P&L
- Win rate (plain text, no progress bar)
- Avg win
- Avg loss
- Profit factor

#### By Hour (bug fix)
Current bug: backend returns all 24 hours including pre-market/overnight hours with zero trades, making the chart look like a 24-bar wall.

Fix: **frontend-only**. Before rendering, filter `data["by-hour"].buckets` to only entries where `position_count > 0`. The backend already converts to local time correctly via `display_tz` — no backend change needed.

#### By Day bar chart — REMOVED
The Statistics "By Day" bar chart (P&L per calendar date) is redundant with the Calendar page's monthly heatmap. Remove it. Its section element and render call are deleted from `statistics.js` and `statistics.html`.

### What's new

#### By Day of Week (new section, new endpoint)
Table only. Columns: Day | Trades | Avg P&L | Win Rate | Total P&L. Rows: Mon–Fri.

**New endpoint:** `GET /api/stats/by-day-of-week`

Backend aggregation (`bucket_by_day_of_week` in `statistics_aggregations.py`):
- Walk `closed_with_pnl` positions
- Convert `entry_time` to `display_tz` local datetime
- Extract weekday (0=Mon … 4=Fri; skip 5=Sat, 6=Sun — futures sessions may occasionally touch weekend boundaries but positions are attributed to the entry day)
- Per weekday: count unique trading days (distinct session dates), total trades, sum P&L, count winning positions (dollars_pnl > 0), count losing positions
- Compute `avg_pnl = total_pnl / trading_days` if `trading_days > 0`, else `0.0` (average per day that had trades, not per occurrence in the calendar range)
- Compute `win_rate = wins / (wins + losses)` or None if no winners/losers

Response model `DayOfWeekResponse`:
```python
class DayOfWeekBucket(StrictModel):
    dow: int            # 0=Mon … 4=Fri
    day_name: str       # "Mon" … "Fri"
    trading_days: int
    trades: int
    avg_pnl: float
    win_rate: float | None
    total_pnl: float

class DayOfWeekResponse(StrictModel):
    buckets: list[DayOfWeekBucket]  # always 5 rows, Mon–Fri, even if 0 trades
```

The five rows are always emitted in Mon–Fri order even if a day has zero trades (so the table always shows all weekdays).

#### Trades per Day (expanded to table)
Currently rendered as a bar chart via `_tradeCountBuckets`. Replace with a plain HTML table.

Extend `_tradeCountBuckets` (client-side, `reports.js` → moved to `statistics.js`) to also emit:
- `win_days`: count of days in this bucket where `total_pnl > 0`
- `win_pct`: `win_days / days * 100` (formatted as `X%`)

Table columns: Trades/Day | Days | Net P&L | Win Days | Win %

---

## Page 2: Calendar (renamed from Reports)

### What stays

- Filter bar — unchanged
- Monthly P&L Calendar heatmap — unchanged (calendar grid with day cells, click → positions list)

### What changes

#### By Week — chart type change
Currently: `mountHistogramChart` (hand-rolled CSS bar chart, grows unwieldy after ~10 weeks).

Change to: LightweightCharts histogram series. Each bucket's `bucket` key is `"YYYY-Www"` (e.g. `"2026-W16"`). Convert to a date by computing the Monday of that ISO week (use a small pure helper `isoWeekToDate(yearStr, weekStr) → "YYYY-MM-DD"`). Pass to LC as a histogram series with green/red coloring by sign. LC's time-axis compression handles 52+ weeks gracefully.

#### By Month — chart type change
Same approach. `bucket` key is `"YYYY-MM"`. Convert to `"YYYY-MM-01"` for the LC time value. Result: a scalable monthly histogram that handles multi-year data.

### What's removed

- **Equity Curve** — lives on Statistics only
- **By Instrument table** — lives on Statistics only
- **Performance Summary** — duplicate of Statistics summary KPIs

---

## Navigation

- Rename nav link "Reports" → "Calendar" in `base.html`
- Rename route `/reports` → `/calendar`. Update `routes/pages.py` and the nav href in `base.html`. No redirect — this is a single-user app with no external link surface.

---

## File changes summary

| File | Change |
|---|---|
| `models/statistics.py` | Add `avg_win`, `avg_loss`, `profit_factor` to `SideStats`; add `DayOfWeekBucket`, `DayOfWeekResponse` models |
| `services/statistics_aggregations.py` | Add `bucket_by_day_of_week()` pure function |
| `services/statistics.py` | Update `_side_stats()` to populate new fields; add `by_day_of_week()` method |
| `routes/stats.py` | Add `GET /api/stats/by-day-of-week` endpoint |
| `routes/pages.py` | Rename `/reports` → `/calendar`, template → `calendar.html` |
| `templates/reports.html` → `templates/calendar.html` | Rename file; remove equity/instrument/summary sections; adjust section IDs |
| `templates/statistics.html` | Remove `stats-by-day` section; add `stats-by-dow` and `stats-trades-per-day` sections |
| `static/js/statistics.js` | Remove by-day render; add by-hour zero-filter fix; add by-dow table render; add trades-per-day table render; expand by-side render |
| `static/js/reports.js` → `static/js/calendar.js` | Rename; remove equity/instrument/summary renders; add LC histogram renders for by-week and by-month |
| `static/js/stats_charts.js` | Add `mountLcHistogram(container, buckets, toDateFn)` helper for the new by-week/by-month LC charts |
| `base.html` | Rename nav link; update href |

---

## Acceptance criteria

1. Statistics page has no duplicate content with Calendar page.
2. By Hour shows only hours where at least one trade occurred in the filtered set.
3. Long vs Short shows avg win, avg loss, and profit factor per side. No win-rate bar.
4. By Day of Week table shows Mon–Fri (all five rows even with zero trades), with avg P&L (not total), win rate, and total P&L.
5. Trades per Day shows a table with win days and win% columns.
6. Calendar page shows By Week and By Month as LightweightCharts histograms that do not grow unwieldy with more data.
7. Calendar page has no equity curve, no instrument table, no performance summary.
8. `/calendar` route works; nav link reads "Calendar". `/reports` no longer exists (replaced, no redirect).
9. All existing filter interactions (account, date range, side) still work on both pages.
10. No new third-party JS dependencies introduced.
