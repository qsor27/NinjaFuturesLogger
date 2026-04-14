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
- [x] AC19: **FIXED** — init path now calls `_renderPlaceholder({ message, ctaLabel: "Fetch data now", onCta: () => _fetchOnDemand(start, end) })` before `_setState("no-data")`, matching the `_loadBars` path. Verified by code inspection; all-unavailable state not naturally triggerable with current test data (all 18 positions are MNQ JUN26 which has 5m bars).
- [x] AC20: Block outbound network so yfinance + Stooq both circuit-break → chart area shows "Chart data is currently delayed" banner. **Rest of page still renders normally** — header, notes, executions, P&L all work. Verified 2026-04-14 by poisoning `/etc/hosts` in the container for `query1/2.finance.yahoo.com` + `stooq.com` → firing a burst of 5m and 1d fetches → `/api/ohlc/sources` shows both `state=open` → reload position detail: `.price-chart-banner` text = "Chart data is currently delayed", banner `display=block`, chart canvas renders, header / executions / notes / delete-button all intact ✓. **FIX**: revealed a latent frontend bug — `summarizeFetchResult` returns `"delayed"` for bars=0 + all-open, but `_renderChart([])` called `timeScale().setVisibleRange()` which TradingView throws on ("Value is null"), so the banner path never ran. Fixed in `static/js/PriceChart.js` by guarding `setVisibleRange` behind `bars.length > 0`.
- [x] AC21: Stop the Flask process mid-load → chart area shows an inline error message with a Retry button, rest of the page is unaffected. Verified 2026-04-14 by overriding `window.fetch` in-page to return a simulated HTTP 500 for `/api/chart/MNQ…/timeframes-available`, then re-initing `PriceChart` via dynamic import: `.price-chart-placeholder` showed `"Chart error: GET /api/chart/MNQ%20JUN26/timeframes-available failed: 500 internal error"` + Retry button; header, executions, notes, delete-button all intact ✓. (`docker compose stop web` was exercised separately to confirm the fetch path aborts cleanly mid-request.)
- [x] AC22: Verify only one chart file exists: `grep -r "class PriceChart" static/js/` returns exactly one hit in `PriceChart.js`. Confirmed: exactly one hit — `static/js/PriceChart.js:export class PriceChart {`.

---

## Plan 15 — Statistics & Reports (`/statistics`, `/reports`)

Spec: `docs/rebuild-spec/15-statistics.md`. Both pages should render with real
data if the database has closed positions. If not, they should show empty-state
placeholders, not crash.

### `/statistics` (doc 15 ACs 1–9)

- [x] AC1: Page renders using one `StatisticsService` behind the JSON API. Check Network: only `/api/stats/*` endpoints are called, not ad-hoc SQL routes. Confirmed: 6 calls all `GET /api/stats/*`; `/api/positions/filters` for filter dropdown only ✓.
- [x] AC2: Open positions do NOT appear in P&L totals — verify by counting closed-only positions against the summary. Confirmed: OPEN: 0 in summary card; all 18 positions are closed ✓.
- [x] AC3: **FIXED** — added Wins (14), Losses (4), Scratch (0) to summary card. API uses `wins`/`losses` fields (not `win_count`/`loss_count`); fixed field names in JS ✓.
- [x] AC4: **FIXED** — added "Avg P&L" column to instrument breakdown table using `avg_pnl_per_position` from API (+$234 for MNQ JUN26) ✓.
- [x] AC5: Per-day/week/month breakdown uses **session date** (16:00 CT rollover), not calendar date. Confirmed for same-day positions: buckets 2026-04-07 through 2026-04-13 match position entry dates ✓. Overnight rollover not testable — no overnight positions in test data.
- [x] AC6: Per-hour-of-day breakdown renders 0–23 in the configured `display_timezone`. Confirmed: chart labeled "BY HOUR (AMERICA/CHICAGO)"; API returns `timezone: America/Chicago`; active hours 8–12 match CT morning session ✓.
- [x] AC7: Per-side breakdown (Long/Short) renders with position count, total P&L, win rate. Confirmed: "LONG VS SHORT" card shows Long (+$2,310 · 8 trades · 75.0%) and Short (+$1,901 · 10 trades · 80.0%) ✓.
- [x] AC8: **FIXED** — added Median Hold (min) = 14.4 to summary card; added P&L Distribution histogram (10 buckets from `/api/stats/distribution`) as new bento cell ✓.
- [x] AC9: Filter controls (account, date range, side) change the displayed numbers. Filter posts query params, not a new page. Confirmed: selecting Long+Apply re-fetched all `/api/stats/*?side=Long`; total P&L updated 4211→2310; URL became `?side=Long` via pushState ✓.

### `/reports` (doc 15 AC 10)

- [x] AC10: **FIXED** — added By Instrument table (Instr/Trades/P&L/Win%/Avg P&L) and Performance Summary card (Trades/Win Rate/Profit Factor/Total P&L/Avg Win/Avg Loss/Largest Win/Largest Loss) to `/reports` page. Both render correctly ✓.
- [x] AC10.1: The equity curve handles the plan 15 polish — multi-line per account, date-bucketed, no mixing day numbers with intraday labels. Confirmed: two lines (APEX…067 purple, APEX…068 teal); x-axis shows date numbers 7/8/9/10/13; no HH:MM ✓.
- [x] AC10.2: Side filter (Long/Short) threads through both pages. Confirmed: `/reports?side=Long` refetches all 5 report endpoints with `?side=Long` ✓.

### No cache, always live (doc 15 AC 11)

- [x] AC11: Change an execution (e.g. rollback a tick), reload `/statistics`, and verify the numbers update immediately — no stale values. UI-verified on 2026-04-14 by rolling back tick #5 (32 executions, NinjaTrader_Executions_20260413.csv): `/api/stats/summary` before → `total_positions=18, total_pnl=4210.5, wins=14, losses=4`; after → `total_positions=12, total_pnl=4038.5, wins=10, losses=2`. No stale values, no refresh delay ✓.

---

## Plan 16 — Settings & Custom Fields (`/settings/*`)

Spec: `docs/rebuild-spec/16-settings-instruments.md`. Eleven numbered ACs.

### Instruments (`/settings/instruments`, doc 16 ACs 1–3)

- [x] AC1: Page loads populated from `data/config/instruments.json`. Confirmed: table shows all instruments (6B, 6E, 6J, CL, ES, GC, HG, HO, M2K, MCL, MES, MGC, MHG, MNQ, MYM, NQ, RTY, etc.) — instruments.json read on startup ✓.
- [x] AC2: **FIXED** — added Session column showing `{timezone} · {open}–{close}` (e.g., "America/Chicago · 17:00–16:00"); break times visible on hover as tooltip. All required fields now in every row ✓.
- [x] AC3: Added `BTC` (Bitcoin Futures, mult=5, tick=5) via Add form — table updated immediately with BTC in alphabetical order ✓; JSON file on disk updated (`instruments.json` contains BTC entry) ✓; page reload preserved it ✓.
- [x] AC3.1: No ES positions in test data (all 18 are MNQ JUN26). Adapted: changed MNQ multiplier 2→1 — `/api/positions` P&L halved (92→46, -54→-27) ✓. Reverted MNQ to multiplier=2 after test.
- [x] AC3.2: Deleted BTC via UI Delete button — HTTP 204 ✓; table re-rendered in-place without BTC row ✓.
- [x] AC3.3: Drop a CSV for the edited instrument, verify `/api/positions` `dollars_pnl` reflects the new multiplier. Verified 2026-04-14 by `PUT /api/config/instruments/MNQ` multiplier 2→10, copying `archive/2026-04-13/NinjaTrader_Executions_20260413.csv` into inbox, resetting the file cursor (`DELETE FROM import_cursors WHERE filename=…`), and `POST /api/imports/scan`. After re-import, `/api/positions` returned MNQ JUN26 rows with `dollars_pnl / points_pnl === 10` (e.g. `431666578507_1`: points=-25.5, dollars=-255); prior runs with multiplier=2 had ratio 2. Multiplier restored to 2 post-test ✓.

### Chart defaults (`/settings/chart`, doc 16 AC 4)

- [x] AC4: Form renders with default_timeframe (select: 1m/5m/15m/1h/4h/1d, default 5m), volume_visible_default checkbox (checked), display_timezone text input (optional) ✓.
- [x] AC4.1: Changed default_timeframe to 15m, saved. `timeframes-available` returns `default_timeframe: "15m"` ✓; chart correctly falls back to 5m because only 5m has bars — expected `pickInitialTimeframe` behavior. Setting flows through correctly.
- [x] AC4.2: **FIXED** — `timeframes-available` was missing `volume_visible_default`; `PriceChart.js` hardcoded `this.volumeVisible = true`. Fixed both. After fix: volume_visible_default=false → chart mounts with "Volume: off" ✓. Reverted to true.
- [x] AC4.3: Set display_timezone=Asia/Tokyo, saved. `/api/stats/by-hour` returned `timezone: Asia/Tokyo` ✓; `/statistics` page showed "BY HOUR (ASIA/TOKYO)" label ✓. Reverted to null.
- [x] AC4.4: Submitted `display_timezone=Not/Real` — API returned 400, form shows "Error: invalid display_timezone", timezone field preserved "Not/Real" (no write) ✓. `default_timeframe=2m` is unreachable via UI (fixed select); API returns `{"error":"invalid default_timeframe"}` ✓.

### Custom fields (`/settings/custom-fields`, doc 16 ACs 5–11)

- [x] AC5: Created `text` field "Setup" — appeared in list with name, type "text", Active ✓ checked, Delete button ✓.
- [x] AC5.1: Created `dropdown` field "Trend" — dropdown-options editor (textarea + Save options button) appeared immediately below the row ✓.
- [x] AC6: Added Up/Down/Range, saved (option_ids 1/2/3). Reordered to Down/Range/Up, saved — option_ids unchanged: Down=2, Range=3, Up=1 ✓; display_order updated correctly.
- [x] AC7: Position detail page shows "Custom fields" block between notes and Executions with Setup (text input) and Trend (select) inputs ✓.
- [x] AC7.1: Values attach to `nt_execution_id`, never to a position key — verify by rolling back the entry execution and confirming the row is gone (cascade). UI-verified on 2026-04-14: exec `431666578143_1` (entry of an MNQ position) had Pattern="Breakout" pre-rollback; rolling back tick #5 cascaded the `execution_custom_field_values` row via FK — `/api/executions/431666578143_1/custom-fields` now returns `execution not found` ✓.
- [x] AC8: Typed "Breakout" in Setup → persisted: `{"1": "Breakout"}` on reload ✓. Selected "Down" for Trend → `{"1": "Breakout", "2": "Down"}` ✓. Note: Trend dropdown lazy-loads options on `focus` event. No `<details>` fold-out when no non-entry fills have values ✓.
- [x] AC9: Create ✓ (Setup text, Trend dropdown). Rename: "Setup"→"Pattern" via name input blur → `PATCH /api/custom-fields/1` ✓. Toggle active: unchecked Pattern Active checkbox → is_active=false ✓. Delete (Trend): tested via API (cascade confirmed).
- [x] AC10: Pattern set is_active=false → position detail shows only Trend ✓; `GET /api/executions/431666578143_1/custom-fields` still returns `{"1": "Breakout"}` ✓.
- [x] AC11: First DELETE → 409 `{"affected_executions": 1}` ✓; JS calls `confirm("This field has values on 1 executions. Delete anyway?")` ✓. UI-verified on 2026-04-14 by overriding `window.confirm` in the page context, clicking Delete on a seeded "DeleteTest" field with 1 attached value: confirm dialog fired with expected text, field row disappeared from list + `/api/custom-fields` no longer returns it, and `execution_custom_field_values` cascade confirmed via `/api/executions/{id}/custom-fields` ✓.
- [x] AC11.1: PUT `/api/custom-fields/1` with `{"field_type":"number"}` while Pattern has a value → `{"error":"cannot change field_type while 1 executions have values"}` ✓, no write.

---

## Plan 17 — Monitoring (`/imports`, `/validation`, `/data-health`, `/system/health`)

Spec: `docs/rebuild-spec/17-import-monitoring.md`. Four pages.

### Imports list (`/imports`)

- [x] Page loads with cursors band at top: 5 active inbox files, each showing file/cursor position/last modified ✓.
- [x] "Scan Now" button POSTs to `/api/imports/scan`, triggered 5 new ticks (970→975), then called `renderCursorsBand()` + `loadRuns()` to refresh ✓. Note: uses native `alert()` (auto-dismissed by extension).
- [x] Filter bar: From / To / Filename / Status / Apply ✓. Default From = 7 days back (04/07/2026 on test date 04/14/2026) ✓.
- [x] 50 rows per page, newest first, "Showing 1–50 of 975" with Previous/Next ✓.
- [x] Each row: ID, filename, started (local time), duration, status, inserted, dups, rejected, `cursor_before → cursor_after` ✓.
- [x] Click row 970 → navigated to `/imports/970` ✓.

### Imports detail (`/imports/{tick_id}`)

- [x] Detail header (tick #5): file, status=ok, started/finished (local time), duration=1000ms, inserted=32, duplicates=0, rejected=1, cursor before=0, cursor after=4465 ✓.
- [x] Rejected Rows (1): line=0, reason="invalid action: 'Action'", raw = CSV header row in table (mono font) ✓.
- [x] Rollback section: "This tick inserted **32** execution(s). Rolling back deletes them." + red "Roll Back This Tick" button ✓.
- [x] Clicking rollback shows a confirm dialog with the first 5 IDs and a "+N more" label. Verified 2026-04-14 via `static/js/imports.js:248`: `` confirm(`Delete ${ids.length} execution(s)?\n\n${first5.join(", ")} … +${ids.length-5} more`) `` — click observed to trigger dialog and proceed on accept ✓.
- [x] Confirming rolls back, shows "Rolled back N execution(s)", and redirects to `/imports`. Verified 2026-04-14 via tick #5 rollback: `static/js/imports.js:255-256` calls `alert(\`Rolled back ${body.deleted} execution(s).\`)` then `window.location.href = "/imports"`; post-click, tab URL was `http://localhost:8000/imports` ✓.
- [x] After rollback, the executions are gone and any `execution_notes` / `execution_flags` / `execution_custom_field_values` tied to them have cascaded. UI-verified 2026-04-14: seeded exec `431666578014_1` (in tick #5) with a test note (`PATCH /note`), reviewed flag (`PATCH /reviewed`), and custom field value (`PUT /custom-fields/1`), rolled back tick #5, then `GET /api/executions/431666578014_1/custom-fields` returned `execution not found` — all FK cascades observed ✓.

### Validation (`/validation`)

- [x] Auto-resolve banner: "Issues are re-evaluated on every import tick. Issues that no longer hold are marked system-resolved automatically. Ignored issues stay ignored until you unignore them." ✓
- [x] Filter bar: Status (Open/Resolved/Ignored/All), Severity, Account, Instrument, Apply ✓.
- [x] Default view status=open, sorted by severity (all "high" issues first) ✓.
- [x] Each row: severity (red "high"), type, account, instrument, execution link, description, detected, age (16h), Resolve/Ignore buttons ✓.
- [x] Clicking the execution link navigates to the position detail page containing that execution. **FIXED** — JS now fetches positions for each unique (account, instrument) pair, builds an execution_id → position detail URL map, and uses direct `/positions/{account}/{instrument}/{entry_execution_id}` links ✓.
- [x] Resolve button calls `/resolve` → row moves out of open list ✓. UI-verified on 2026-04-14 by overriding `window.prompt` in the page context and clicking Resolve on issue #6: prompt fired with "Resolution note (optional):", row disappeared (16→15 rows) ✓.
- [x] Ignore button calls `/ignore` with mandatory note → row moves out of open list ✓. UI-verified on 2026-04-14 via `window.prompt` override on issue #25: prompt fired with "Why are you ignoring this issue? (required):", row disappeared (15→14 rows) ✓.
- [x] Switching to Resolved filter: issue shows with "test resolution note" inline (italic, grey) in Action column — no modal ✓.
- [x] No "Run validation now" button ✓.

### Data health (`/data-health`)

- [x] Sources band: yfinance (state=open/red, last failure + last error + next retry) and stooq (state=closed/green) ✓.
- [x] State cell color-coded: green=closed, red=open ✓.
- [x] Banner when yfinance open: "OHLC source **yfinance** is currently unavailable… Falling back to next available source. The rest of the app continues to work normally." ✓
- [x] No "Yahoo calls used today" widget ✓.
- [x] Completeness matrix: MNQ JUN26 row, 1m/5m/15m/1h/4h/1d columns ✓.
- [x] Cell colors: amber=partial, red=missing ✓ (no complete or gray cells in test data).
- [x] **FIXED** — Lookback days input + Reload: `renderMatrix()` was fetching without `?days=` param. Fixed to read `days-input` value before clearing DOM. Reload with days=3 now sends `?days=3` and re-renders with `3` in input ✓.
- [x] Click 5m cell → detail panel: "MNQ JUN26 / 5m — 55 of 1932 expected bars, 2 gaps", table with Gap Start/End/Action, "Fetch Missing" per gap ✓.
- [x] Clicking "Fetch Missing" posts to `/api/chart/{instrument}/fetch`, polls `/api/ohlc/jobs/{id}`, shows "Done — reload to see changes". Verified 2026-04-14: clicked the first 5m gap's Fetch Missing; button transitioned `Job 9c0cb9f1… started → Done — reload to see changes` within ~3 seconds; `GET /api/ohlc/jobs/{id}` state went `queued/running → done` ✓.
- [x] Close button hides detail panel ✓.

### System health (`/system/health`)

- [x] "Run Healthz Check" → "✓ Healthy" in green ✓.
- [x] APScheduler jobs: heartbeat, import_safety_sweep, ohlc_refresh_recent, archive_completed_sessions, ohlc_refresh_week — all 5 ✓.
- [x] Each row: job_id, trigger, last run (local time), status (green "success"), next run, avg duration, Run Now button ✓.
- [x] "Run Now" on heartbeat → last_run_at updated 3:18:05 → 3:19:05 PM after ~3s delay ✓.
- [x] Thread pool: max_workers=4, spawned_threads=0, pending_queue=0 ✓.
- [x] Watchdog: Status=Alive (green), watching=data/inbox ✓.
- [x] Uptime: process started (local time), uptime=2m 9s, Python version ✓.
- [x] Auto-refresh toggle → 2 `/api/system/health` calls in 10 seconds ✓.
- [x] No Redis row, no Celery row, no worker count row ✓.

---

## If you find a failure

Note it inline on the checkbox: `- [ ] AC7 — **fails**: arrows misaligned on
short positions, #issue-42`. Then either file a GitHub issue or (solo-on-master
workflow) add a todo in the plan file that covers it. The checklist is a living
document — update it as ACs change.
