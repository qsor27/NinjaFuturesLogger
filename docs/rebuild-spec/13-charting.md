# Feature 13 — Charting

## Purpose

Render a candlestick chart on the position detail page that shows the market context around a position's entry and exit, with the trader's actual fills marked on the chart so they can see how their executions compare to the bars.

## Dependencies

- **Feature 11** — Positions are the input.
- **Feature 14** — OHLC data is the source.
- **Feature 12** — The chart is embedded in the position detail page.
- **Feature 16** — Chart defaults (preferred timeframe, volume default) live in `chart_defaults`.

## User stories

1. **As the trader**, on a position detail page, I see a candlestick chart for the position's instrument, with the entry time at the center of the visible range and as many surrounding candles as will fit on screen.
2. **As the trader**, I see arrows on the chart at each of my fills: green up-arrows below the bar for buys, red down-arrows above the bar for sells. Arrows are a uniform size (they do not scale with quantity or screen width).
3. **As the trader**, I can switch the timeframe. The timeframe selector only offers timeframes for which bars exist in the local store for this instrument; timeframes with no data are shown but disabled. Switching timeframes keeps the entry time centered and re-fits the visible range to the new candle size (bigger candles cover more wall-clock time on the same chart width).
4. **As the trader**, I can toggle volume on/off.
5. **As the trader**, I see horizontal price lines on the chart marking my individual execution prices (dashed, colored by side) and my average entry price (solid, thicker). These are drawn across the full chart width with labels on the right price axis.
6. **As the trader**, when I hover the chart, a small overlay in the top-right shows the OHLC values of the candle under the crosshair along with volume, absolute price change, and percent change for that candle.
7. **As the trader**, I can click an execution arrow to highlight the matching row in the executions table, and click a row in the executions table to scroll the chart to that arrow and flash it briefly.
8. **As the trader**, when no OHLC data is available for the requested timeframe and range, I see a placeholder with a "Fetch data now" button that triggers an on-demand fetch (doc 14) and reloads the chart when the fetch completes.
9. **As the trader**, when OHLC sources are unavailable (doc 14), the rest of the position detail page still renders normally; the chart area shows a "Chart data is currently delayed" banner but the header, execution list, notes, and P&L are unaffected.
10. **As the trader**, while bars are loading I see an unobtrusive loading indicator over the chart. If the read fails with a network or server error, the chart area shows an inline error message with a retry button; the rest of the page is unaffected.

## Acceptance criteria

### Layout and styling

1. The position detail page contains exactly one chart instance.
2. The chart uses the TradingView Lightweight Charts library.
3. The chart has a header strip above the canvas containing (left-to-right): the chart title `"{instrument} Price Chart"`, a timeframe button group, and a volume-visibility toggle button.
4. The canvas is a dark theme: background `#1a1a1a`, grid `#333`, text `#e5e5e5`, green up-candles (`#4CAF50`), red down-candles (`#F44336`). The right price scale auto-scales with 10% top/bottom margins. The time scale shows hour:minute labels (no seconds).
5. The crosshair is in magnet mode (snaps to candles).
6. Resizing the browser window resizes the chart smoothly (ResizeObserver on the container).

### Viewport rule (initial render and timeframe switch)

7. The viewport is always centered on `entry_time` (the opening candle of the position). There is no fixed lookback duration. The number of bars shown is determined by the chart's pixel width and the bar spacing, so the visible range is *"as many bars as fit on screen, centered on entry_time"*. When the user switches timeframes, the chart recomputes the visible range with the new candle width — a 1d chart covers many more days than a 1m chart at the same pixel width, and this is the intended behavior.
8. This rule applies uniformly to closed, open, and degenerate positions. Execution markers outside the initial visible range still render at their correct timestamps; the user can pan or zoom to bring them into view.
9. The fallback computation runs client-side from the `entry_time` passed in by the position detail API.

### Controls

10. **Timeframe selector.** Populated from `GET /api/chart/{instrument}/timeframes-available`, which returns the set of timeframes that have any bars in the local store for this instrument. Timeframes with no local data are rendered in the selector but disabled and visually muted. The user cannot select a disabled timeframe. Default selection comes from `chart_defaults.default_timeframe` (feature 16), or — if that timeframe is not available for the current instrument — the first available timeframe in the canonical order (`1m, 5m, 15m, 1h, 4h, 1d`).
11. **Volume toggle.** Default state comes from `chart_defaults.volume_visible_default`. Toggling is instantaneous; the data does not re-fetch.

### Data and markers

12. The chart fetches OHLC data via `GET /api/chart/{instrument}?timeframe=...&from=...&to=...` and execution markers via `GET /api/positions/{account}/{instrument}/{entry_execution_id}/markers`. The position URL uses the natural key (doc 11, doc 12); there is no numeric position_id anywhere in the chart API.
13. Each execution is rendered as an arrow marker at its timestamp, positioned below the bar for buys (green up-arrow) and above the bar for sells (red down-arrow). All arrows are the same size regardless of quantity or screen dimensions.
14. Price lines for individual executions are drawn as dashed horizontal lines at each execution's price, colored green for buys and red for sells. The position's average entry price is drawn as a solid, thicker horizontal line (green for long, red for short). Each price line has a label visible on the right price axis. Price lines are cleared and redrawn on timeframe change.

### Crosshair OHLC overlay

15. An overlay box anchored to the top-right corner of the chart appears when the mouse enters the chart area. It shows the time of the candle under the crosshair, its O/H/L/C values, its volume, and the absolute and percent change from open to close for that candle (green if up, red if down). The overlay hides when the mouse leaves the chart or when the crosshair is in a gap between candles.

### Arrow ↔ executions-table linking

16. Clicking an execution arrow dispatches a document-level custom event that the executions-table component listens for; the matching table row scrolls into view and is highlighted briefly.
17. Clicking an executions-table row causes the chart to scroll so the matching arrow is visible and flashes the arrow gold for ~2 seconds.

### States and errors

18. **Loading.** While a bar fetch is in flight, a loading indicator is visible over the canvas. Controls remain enabled; a second change (e.g., a rapid timeframe click) cancels the in-flight request and starts a new one.
19. **No data for range.** If `GET /api/chart/{instrument}` returns an empty result for the requested range, the chart area shows a placeholder with a "Fetch data now" button that calls `POST /api/chart/{instrument}/fetch` (doc 14) with the range and polls `GET /api/ohlc/jobs/{job_id}` until the fetch completes, then re-fetches the bars. This retry is user-triggered only — the chart does not auto-retry.
20. **Delayed-data banner.** The chart read path never blocks on a fetch. `GET /api/chart/{instrument}` reads the `bars` table only. If the OHLC fetcher's circuit breakers are all open, the read returns whatever bars are present and the chart area shows a "Chart data is currently delayed" banner over or above the canvas. This is the user-facing expression of doc 14's isolation rule.
21. **Read error.** If the read endpoint returns a non-empty error (5xx, network failure, malformed response), the chart area shows an inline error message with the error text and a "Retry" button. The rest of the position detail page is unaffected.

### Code organization

22. The chart wrapper class lives in exactly one file (`static/js/PriceChart.js`), is constructed by one init script, and is the only chart implementation in the app. Method names, internal structure, and public surface are implementation detail — the spec does not prescribe them beyond the user-visible behavior in this document.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/chart/{instrument}` | OHLC bars for instrument+timeframe+range. Returns array of `{time, open, high, low, close, volume}`. Reads only. |
| GET | `/api/chart/{instrument}/timeframes-available` | Which timeframes have any bars in the local store for this instrument. Returns the canonical timeframe set with an availability flag (and optionally a bar count) per timeframe. |
| GET | `/api/positions/{account}/{instrument}/{entry_execution_id}/markers` | Execution markers for the position: array of `{time, price, side, quantity, label}`. |
| POST | `/api/chart/{instrument}/fetch` | Trigger on-demand OHLC fetch for a range. Returns a job ID. (Already in doc 14.) |
| GET | `/api/ohlc/jobs/{job_id}` | Poll fetch job status. (Already in doc 14.) |

## Fragmentation hazards

1. **Multiple chart implementations.** The old codebase had `PriceChart.js`, `SimpleChart.js`, `charts/ChartComponentManager.js`, `charts/ModernChartComponent.js`, plus a legacy `price_chart_old.html` template and a `test_chart_simple.html` test harness. None were clearly canonical. **Rule:** there is exactly one chart class file, one constructor, one template partial. Delete is allowed; alternates are not.

2. **Chart pages that don't know which position they're showing.** The old `/charts/{instrument}` page rendered an instrument chart with no position context. The position detail page also had a chart, sometimes with markers, sometimes not, depending on which template was loaded. **Rule:** the only place a chart appears is the position detail page. The instrument-only `/charts` page is removed. If the user wants market context without a position, the position-detail chart already provides pan/zoom navigation.

3. **OHLC fetch and chart render coupled in the route.** The old `/api/chart-data/{instrument}` route had branching for `cache_only_chart_service` vs `ohlc_service` vs `background_data_manager`, and would sometimes fetch and sometimes not. **Rule:** the chart endpoint reads from the OHLC store only. It never fetches. If data is missing, it returns "missing" and the user (or an explicit fetch endpoint) requests a fetch as a separate action. Reads and writes are not entangled.

4. **Inline JS in chart templates.** The old `positions/detail.html` had ~80 LOC of inline JS for chart wiring. **Rule:** the template contains a `<div id="chart">` and a single `<script>` that calls `PriceChart.init({account, instrument, entry_execution_id})`. Everything else is in `PriceChart.js`.

5. **Multiple chart-data endpoints.** The old code had `/api/chart-data/{instrument}`, `/api/chart-data-simple/{instrument}`, `/api/chart-data-adaptive/{instrument}`, `/api/debug-ohlc-service/{instrument}`. **Rule:** one endpoint, one shape. If different consumers need different shapes, they parameterize the one endpoint.

6. **Auto-fallback behaviors that silently change user intent.** The old chart code, on encountering a missing timeframe, would auto-switch to a "best" timeframe and silently reload — and on a missing range, would auto-trigger a gap-fill fetch. Both made it impossible for the user to tell what they were actually looking at. **Rule:** if the user's selected timeframe has no data, show the no-data placeholder; do not auto-switch. If a range is missing, show the fetch-now CTA; do not auto-fetch. The only automatic selection is the *initial* default, which picks the first available timeframe if the configured default is not available (AC 10).

## Deviations from old behavior

- The standalone `/charts/{instrument}` and `/charts` gallery pages are removed. Charts only exist embedded in position detail.
- The "instrument list with chart status" view is moved to feature 17 (data monitoring).
- Multiple "chart settings" APIs (`/api/v1/settings/chart`, `/api/v2/settings/categorized`, etc.) are collapsed to one chart-defaults endpoint exposed via the settings page (feature 16).
- The old `chart_defaults.default_lookback_minutes` setting is removed. The viewport is computed from chart width and bar spacing (AC 7), so a configurable lookback duration is no longer meaningful.
- The arrow hover tooltip (a floating card showing execution details on mouseover) is removed. The arrow label, the executions-table row, and the arrow ↔ table linking (AC 16–17) cover the same information.
- The arrow size is uniform. The old code scaled arrows by chart width; the spec scaled them by execution quantity. Both are removed in favor of a single fixed size.
- Contract-fallback warnings and timeframe auto-switch warnings are removed along with the auto-fallback behaviors themselves (hazard 6).
