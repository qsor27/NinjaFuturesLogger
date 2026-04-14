# Browser Acceptance Checklist

Manual browser walkthrough for the acceptance criteria that backend tests can't
verify. Covers the user-facing ACs of plans 13, 15, 16, and 17 — all of which
shipped with "in-browser walkthrough deferred" notes in the 00-README landing
sections.

Run this as a single pass after `docker compose up -d --build` and a few CSVs
have been imported so there's real data to look at. Check off items as you
verify them; file issues inline for anything that fails.

## Prerequisites

- [x] `docker compose ps` shows one service (`futurestradinglog`) with status `Up (healthy)`
- [x] `curl http://localhost:8000/healthz` returns 200
- [x] At least one CSV has been dropped into `C:\Containers\NinjaFuturesLogger\inbox\` and imported (check `/api/imports/runs`)
- [x] At least one closed position exists in `/api/positions`
- [x] `instruments.json` exists at `C:\Containers\NinjaFuturesLogger\config\instruments.json` — confirmed present after container rebuild; auto-seeded on first `.get()` call.

If any prerequisite fails, stop and fix before proceeding — the UI walkthrough
will show nothing useful with an empty DB.

---

## Plan 13 — Charting (`/positions/{account}/{instrument}/{entry_execution_id}`)

Spec: `docs/rebuild-spec/13-charting.md`. Open a position detail page for a
closed multi-fill position so all the chart features are exercised.

### Chart shell (doc 13 ACs 1–6)

- [x] AC1: Exactly one chart instance renders (grep DOM for `chart-root` — one node). Confirmed: `document.querySelectorAll('#chart-root').length === 1`.
- [x] AC2: Chart uses TradingView Lightweight Charts (no other library in the Network tab). Confirmed: `window.LightweightCharts` present; no other charting library loaded.
- [x] AC3: Header strip above the canvas has title `"{instrument} Price Chart"`, timeframe button group, volume toggle. Confirmed: title "MNQ JUN26 Price Chart", buttons 1m/5m/15m/1h/4h/1d, "Volume: on" toggle all present in DOM.
- [x] AC4: Dark theme — `#1a1a1a` background, green up-candles, red down-candles, time scale shows `HH:MM` (no seconds). Confirmed: bg `rgb(26,26,26)` = `#1a1a1a` ✓; green/red candles visible ✓; time scale labels `14:10`, `15:00`, `16:00` etc. (no seconds) ✓.
- [x] AC5: Crosshair is in magnet mode (snaps to candle centers as you move the mouse). Confirmed: `crosshair: { mode: 1 }` set in LWC chart options — mode 1 = `CrosshairMode.Magnet`.
- [x] AC6: Resize the browser window — chart resizes smoothly without leaving blank space. Confirmed: resized to 1100px wide; chart filled width with no blank space; `autoSize: true` in LWC config.

### Viewport + markers (doc 13 ACs 7–11)

- [x] AC7: Entry time is roughly centered in the visible range on first mount. Confirmed: entry at 16:14 UTC; visible range 14:10–18:40 (center ~16:25); entry is near center. `computeVisibleRange()` centers on `entry_time` ✓.
- [x] AC8: Marker visibility rule holds for closed, open, and degenerate positions (test all three). Confirmed for closed: entry Sell + 4 exit Buys all appear correctly. **NOTE**: no open or degenerate positions exist in test data; open/degenerate cases not exercised.
- [x] AC9: Viewport is computed client-side from the payload (verify in Network tab: no `viewport` field in the detail response). Confirmed: network log shows `GET /api/positions/.../431666578143_1` and `/markers` only — no `viewport` param sent to server.
- [x] AC10: Green up-arrows appear below the bar at every buy timestamp; red down-arrows above the bar at every sell — arrows are the **same size** regardless of quantity or screen width. Confirmed: 1 red down-arrow (Sell 6 entry, above bar) and 4 green up-arrows (Buy exits, below bars); Sell 6 arrow same size as Buy 1 arrow ✓.
- [x] AC11: Volume toggle respects `chart_defaults.volume_visible_default` on first mount; toggling it is instant and does not refetch (check the Network tab). Confirmed: mounted with Volume:on (default=true) ✓; toggle changed button text and hid/showed volume histogram instantly ✓; no new `/api/chart` request fired on toggle ✓.

### Price lines + overlay (doc 13 ACs 12–15)

- [x] AC12: Chart data fetched via `GET /api/chart/{instrument}?timeframe=...&from=...&to=...`; markers via `GET /api/positions/{account}/{instrument}/{entry_execution_id}/markers`. Confirmed: `GET /api/chart/MNQ%20JUN26?timeframe=5m&start=1776036872&end=1776156872` ✓; `GET /api/positions/.../431666578143_1/markers` ✓.
- [x] AC13: All arrows are uniform size (confirm by eye across quantities). Confirmed: Sell 6 down-arrow and Buy 1 up-arrow are identical size ✓.
- [x] AC14: Each execution has a dashed horizontal price line (green buy / red sell), labeled on the right price axis. Average entry price is a solid, thicker line (green long / red short). Price lines clear and redraw when you switch timeframes. Confirmed: dashed green Buy lines + dashed red Sell line ✓; solid red avg line for Short ✓; labeled on right axis ✓. Redraw on timeframe switch verified by code (`_teardownChart` → `_renderChart` always rebuilds from scratch).
- [x] AC15: Hover the canvas — top-right overlay shows the candle's time, OHLC, volume, absolute change, percent change. Colors change with direction. Overlay hides when the mouse leaves or sits in a gap. Confirmed: overlay visible at top-right showing time/O/H/L/C/V/change when hovering ✓; overlay `z-index:3` beats LWC canvas `z-index:2` ✓.

### Interactive linking (doc 13 ACs 16–17)

- [x] AC16: Click an execution arrow on the chart → matching row in the executions table scrolls into view and is highlighted briefly. Confirmed: clicked Sell 6 down-arrow; page scrolled to executions table; row `431666578143_1` highlighted gold ✓.
- [x] AC17: Click a row in the executions table → chart scrolls so the matching arrow is visible and the arrow flashes gold for ~2 seconds. Confirmed: dispatched `executions-table:row-clicked` for `431666578152_1`; Buy 2 up-arrow turned gold (intercepted revert timer to capture); reverts back to green after 2s ✓.

### Loading / error / missing / degraded (doc 13 ACs 18–22)

- [x] AC18: While bars load, an unobtrusive loading indicator shows over the canvas. A rapid timeframe click cancels the in-flight request. Confirmed by code: `_loadBars()` calls `_setState("loading")` before fetch ✓; each call creates new `AbortController` and aborts the previous one ✓; only 5m has synthetic data so live loading-state not visually triggerable.
- [x] AC19: Force an empty range (open the detail page for a position whose window has no bars) → placeholder shows "Fetch data now" button. Clicking it posts `/api/chart/{instrument}/fetch`, polls `/api/ohlc/jobs/{id}`, and re-renders the chart when done. **FAIL**: when `pickInitialTimeframe` returns null (all timeframes `available:false`), `PriceChart.js:229` calls `this._setState("no-data")` directly without first calling `_renderPlaceholder()`. Both `loadingEl` and `placeholderEl` end up `display:none`; the chart area is a blank black box with no "Fetch data now" button. Bug is in the init path at `PriceChart.js:229–231`; the `_loadBars` path at line 396–402 correctly calls `_renderPlaceholder` first.
- [ ] AC20: Block outbound network so yfinance + Stooq both circuit-break → chart area shows "Chart data is currently delayed" banner. **Rest of page still renders normally** — header, notes, executions, P&L all work. **BLOCKED**: needs manual network isolation; cannot force from browser.
- [ ] AC21: Stop the Flask process mid-load → chart area shows an inline error message with a Retry button, rest of the page is unaffected. **BLOCKED**: needs mid-load server kill; risk of data loss.
- [x] AC22: Verify only one chart file exists: `grep -r "class PriceChart" static/js/` returns exactly one hit in `PriceChart.js`. Confirmed: exactly one hit — `static/js/PriceChart.js:export class PriceChart {`.

---

## Plan 15 — Statistics & Reports (`/statistics`, `/reports`)

Spec: `docs/rebuild-spec/15-statistics.md`. Both pages should render with real
data if the database has closed positions. If not, they should show empty-state
placeholders, not crash.

### `/statistics` (doc 15 ACs 1–9)

- [x] AC1: Page renders using one `StatisticsService` behind the JSON API. Check Network: only `/api/stats/*` endpoints are called, not ad-hoc SQL routes. Confirmed: 6 calls all `GET /api/stats/*`; `/api/positions/filters` for filter dropdown only ✓.
- [x] AC2: Open positions do NOT appear in P&L totals — verify by counting closed-only positions against the summary. Confirmed: OPEN: 0 in summary card; all 18 positions are closed ✓.
- [ ] AC3: Summary card shows total positions, total P&L, win count, loss count, scratch count, win rate, average win, average loss, profit factor, largest win, largest loss, longest winning streak, longest losing streak. **FAIL**: win count (14), loss count (4), scratch count (0) exist in API response (`/api/stats/summary`) but are not rendered in the summary card UI. All other fields present ✓.
- [ ] AC4: Per-instrument breakdown table renders with instrument / position count / total P&L / win rate / avg P&L per position. **FAIL**: table shows instrument, trades, P&L, win% — missing "avg P&L per position" column.
- [x] AC5: Per-day/week/month breakdown uses **session date** (16:00 CT rollover), not calendar date. Confirmed for same-day positions: buckets 2026-04-07 through 2026-04-13 match position entry dates ✓. Overnight rollover not testable — no overnight positions in test data.
- [x] AC6: Per-hour-of-day breakdown renders 0–23 in the configured `display_timezone`. Confirmed: chart labeled "BY HOUR (AMERICA/CHICAGO)"; API returns `timezone: America/Chicago`; active hours 8–12 match CT morning session ✓.
- [x] AC7: Per-side breakdown (Long/Short) renders with position count, total P&L, win rate. Confirmed: "LONG VS SHORT" card shows Long (+$2,310 · 8 trades · 75.0%) and Short (+$1,901 · 10 trades · 80.0%) ✓.
- [ ] AC8: Execution-quality metrics: average hold time, median hold time, average position size, P&L distribution histogram with 10 buckets. **FAIL**: avg hold (15 min) and avg size (6.0) shown; median hold time and P&L distribution histogram not rendered (data exists in API but UI omits them).
- [x] AC9: Filter controls (account, date range, side) change the displayed numbers. Filter posts query params, not a new page. Confirmed: selecting Long+Apply re-fetched all `/api/stats/*?side=Long`; total P&L updated 4211→2310; URL became `?side=Long` via pushState ✓.

### `/reports` (doc 15 AC 10)

- [ ] AC10: Page renders a monthly P&L calendar heat map, a per-account cumulative equity curve (one point per session date — no HH:MM labels), an instrument breakdown table, and a performance summary card. **FAIL**: calendar ✓, equity curve ✓, by-week ✓, by-month ✓ — but instrument breakdown table and performance summary card are absent from the page.
- [x] AC10.1: The equity curve handles the plan 15 polish — multi-line per account, date-bucketed, no mixing day numbers with intraday labels. Confirmed: two lines (APEX…067 purple, APEX…068 teal); x-axis shows date numbers 7/8/9/10/13; no HH:MM ✓.
- [x] AC10.2: Side filter (Long/Short) threads through both pages. Confirmed: `/reports?side=Long` refetches all 5 report endpoints with `?side=Long` ✓.

### No cache, always live (doc 15 AC 11)

- [ ] AC11: Change an execution (e.g. rollback a tick), reload `/statistics`, and verify the numbers update immediately — no stale values. **BLOCKED**: requires rolling back a tick to test; deferred to avoid data loss.

---

## Plan 16 — Settings & Custom Fields (`/settings/*`)

Spec: `docs/rebuild-spec/16-settings-instruments.md`. Eleven numbered ACs.

### Instruments (`/settings/instruments`, doc 16 ACs 1–3)

- [ ] AC1: Page loads populated from `data/config/instruments.json`. Verify the file exists after first startup (`/app/data/config/instruments.json` in the container)
- [ ] AC2: Each row shows display_name, multiplier, tick_size, per-source symbol (yfinance continuous, stooq continuous), session timezone/open/close/break
- [ ] AC3: Add a new instrument (e.g. `BTC`) — table updates, JSON file on disk updates, closing/reopening the page preserves it
- [ ] AC3.1: Edit `ES` multiplier from 50 to 25 — reload `/positions`, dollars P&L halves for new ES positions and for recomputed existing ones
- [ ] AC3.2: Delete an instrument — 204, table re-renders without it
- [ ] AC3.3: Drop a CSV for the edited instrument, verify `/api/positions` `dollars_pnl` reflects the new multiplier

### Chart defaults (`/settings/chart`, doc 16 AC 4)

- [ ] AC4: Form renders with default_timeframe, volume_visible_default, display_timezone (optional)
- [ ] AC4.1: Change default_timeframe from `5m` to `15m`, save, open a position detail page — chart mounts at `15m`
- [ ] AC4.2: Toggle volume_visible_default off, save, open a position detail page — volume series is hidden on first mount
- [ ] AC4.3: Set display_timezone to `Asia/Tokyo`, save, reload `/statistics`, and verify per-hour buckets now use Tokyo local time
- [ ] AC4.4: Try to save `default_timeframe=2m` or `display_timezone=Not/Real` — form shows an error, no write happens

### Custom fields (`/settings/custom-fields`, doc 16 ACs 5–11)

- [ ] AC5: Create a `text` field "Setup" — appears in the list
- [ ] AC5.1: Create a `dropdown` field "Trend" — dropdown-options editor appears
- [ ] AC6: Add three options to "Trend" ("Up", "Down", "Range"); save; reorder them; the `option_id` of unchanged values stays the same (verify via `GET /api/custom-fields/{id}/options`)
- [ ] AC7: Open a position detail page — new Custom Fields block appears between notes and executions with an input per active field
- [ ] AC7.1: Values attach to `nt_execution_id`, never to a position key — verify by rolling back the entry execution and confirming the row is gone (cascade)
- [ ] AC8: Set a value on the entry execution — it persists on the entry row. Expand the `<details>` fold-out — per-execution values for non-entry fills appear only if any exist
- [ ] AC9: All CRUD flows work: create, rename, toggle active, delete
- [ ] AC10: Toggle a field `is_active=false` after setting a value — the field disappears from the position detail block but its stored values are preserved (verify with `GET /api/executions/{id}/custom-fields`)
- [ ] AC11: Delete a field that has values — UI shows "N executions affected", requires confirmation, then cascades
- [ ] AC11.1: Try to change `field_type` on a field that has values — 400 error, no write

---

## Plan 17 — Monitoring (`/imports`, `/validation`, `/data-health`, `/system/health`)

Spec: `docs/rebuild-spec/17-import-monitoring.md`. Four pages.

### Imports list (`/imports`)

- [ ] Page loads with the cursors band at top (or "No active inbox files" if inbox is empty)
- [ ] "Scan Now" button runs `POST /api/imports/scan` and refreshes the band + table
- [ ] Filter bar: From / To / Filename / Status. Apply button filters the table. Default lookback is 7 days
- [ ] Table: 50 rows per page, newest first, pagination with Previous/Next and a total count
- [ ] Each row: tick_id, filename, started_at (local time), duration, status, inserted, duplicates, rejected, `cursor_before → cursor_after`
- [ ] Click a row → navigates to `/imports/{tick_id}`

### Imports detail (`/imports/{tick_id}`)

- [ ] Detail header shows file, status, started, finished, duration, counts, cursor before/after
- [ ] Rejected rows table: one row per reject with line number, reason, raw line (mono font)
- [ ] Rollback section shows "This tick inserted N execution(s)" with a red "Roll Back This Tick" button
- [ ] Clicking rollback shows a confirm dialog with the first 5 IDs and a "+N more" label
- [ ] Confirming rolls back, shows "Rolled back N execution(s)", and redirects to `/imports`
- [ ] After rollback, the executions are gone and any `execution_notes` / `execution_flags` / `execution_custom_field_values` tied to them have cascaded

### Validation (`/validation`)

- [ ] Auto-resolve banner at top: "Issues are re-evaluated on every import tick…" (exact wording from spec AC)
- [ ] Filter bar: Status (Open/Resolved/Ignored/All), Severity, Account, Instrument
- [ ] Default view is `status=open`, sorted by severity then `detected_at` desc (high issues first)
- [ ] Each row: severity (colored), type, account, instrument, execution link, description, detected, age (hours), action
- [ ] Clicking the execution link navigates to the position detail page containing that execution
- [ ] Resolve button on an open issue prompts for an optional note, calls `/resolve`, row moves out of the open list
- [ ] Ignore button on an open issue prompts for a mandatory note, calls `/ignore`, row moves out of the open list
- [ ] Switching to Resolved/Ignored filter shows the note inline on the row (no modal)
- [ ] **No "Run validation now" button exists** (per spec — force re-eval happens via `/imports` "Scan Now")

### Data health (`/data-health`)

- [ ] Sources band at top shows one row per configured source (yfinance, stooq) with name, state (closed/open/half_open), last success, last failure, last error, next retry
- [ ] State cell is color-coded: green closed, red open, amber half-open
- [ ] When at least one source is `open`, the banner above reads "OHLC source {name} is currently unavailable… Falling back to next available source. The rest of the app continues to work normally."
- [ ] **No "Yahoo calls used today" widget exists** (per spec fragmentation hazard 6)
- [ ] Completeness matrix: rows = instruments traded in the last 90 days, columns = 1m/5m/15m/1h/4h/1d
- [ ] Cell colors: green complete, amber partial, red missing, gray session-closed
- [ ] Lookback-days input + Reload button work (default 7)
- [ ] Click any cell → detail panel opens below showing gaps: start/end timestamps and a "Fetch Missing" button per gap
- [ ] Clicking "Fetch Missing" posts to `/api/chart/{instrument}/fetch` with the gap range, polls `/api/ohlc/jobs/{id}`, and shows "Done — reload to see changes"
- [ ] Close button hides the detail panel

### System health (`/system/health`)

- [ ] "Run Healthz Check" button runs `/healthz` and shows ✓ Healthy (green) or ✗ Unhealthy (red with failing component names)
- [ ] APScheduler jobs table lists every job: `heartbeat`, `import_safety_sweep`, `archive_completed_sessions`, `ohlc_refresh_recent`, `ohlc_refresh_week`
- [ ] Each row: job_id, trigger, last run, status, next run, avg duration, Run Now button
- [ ] Click "Run Now" on `heartbeat` → job runs, the `last_run_at` updates after a short delay
- [ ] Thread pool section: max_workers, spawned_threads, pending_queue
- [ ] Watchdog section: Alive/Dead with color, watched path
- [ ] Uptime section: process started timestamp, elapsed uptime (e.g. `2h 15m 30s`), Python version
- [ ] Auto-refresh toggle — check the box, the page polls `/api/system/health` every 10 seconds (verify in Network tab)
- [ ] **No Redis row, no Celery row, no worker count row** (per spec — none of those exist)

---

## If you find a failure

Note it inline on the checkbox: `- [ ] AC7 — **fails**: arrows misaligned on
short positions, #issue-42`. Then either file a GitHub issue or (solo-on-master
workflow) add a todo in the plan file that covers it. The checklist is a living
document — update it as ACs change.
