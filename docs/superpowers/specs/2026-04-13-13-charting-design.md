# Plan 13 — Charting: Design

**Date:** 2026-04-13
**Status:** Approved for plan-writing
**Spec source:** `docs/rebuild-spec/13-charting.md`
**Predecessors:** Plans 00, 10, 11, 14, 12 (all ✅ complete)
**Successor:** Plan 13 implementation plan at `docs/superpowers/plans/2026-04-13-13-charting.md`

## Purpose

Embed a working candlestick chart on the position detail page, rendered with the TradingView Lightweight Charts library, with execution markers, price lines, timeframe switching, volume toggle, hover OHLC overlay, fetch-now CTA, delayed-data banner, and arrow ↔ executions-table linking. Plan 13 is almost entirely frontend plus two thin backend additions; it adds no migrations, no new tables, and no new Python dependencies.

## Architecture

Plan 13 splits cleanly into a small backend slice and a larger frontend slice.

**Backend additions:**

- `services/chart_defaults.py` — module-level stub returning `{default_timeframe: "1m", volume_visible_default: true}`. Plan 16 swaps the implementation to read from a future `chart_defaults` table; Plan 13 establishes the function-level seam (`get_defaults()`) so no frontend rewiring is needed later.
- `services/markers.py::build_markers(executions) -> list[Marker]` — pure function turning execution rows into marker records. Suffix-strips `#close` / `#open` per Plan 12's rules. No DB access.
- `models/markers.py::Marker` — `StrictModel` with `(time, price, side, quantity, label)`. Exported from `models/__init__.py`.
- Two new routes on existing blueprints:
  - `GET /api/chart/{instrument}/timeframes-available` (extends the existing chart blueprint)
  - `GET /api/positions/{account}/{instrument}/{entry_execution_id}/markers` (extends the existing positions blueprint)

Both routes are thin parse/dispatch/format wrappers per Rule 2. Both read-only; neither calls the OHLC fetcher.

**Frontend additions:**

- `static/vendor/lightweight-charts.standalone.production.js` — committed v5 standalone production build of the TradingView Lightweight Charts library, ~250 KB. Loaded via plain `<script src="...">` in the position detail template before the existing module loader. No CDN, no bundler, no Node, no `package.json`. The version is pinned by the file's contents; upgrades are a manual re-download documented in the plan and the commit message.
- `static/js/PriceChart.js` — one ES module exporting `{ init }`. The only chart implementation in the app per AC 22 / hazard 1. Internal structure is a small set of pure helper functions (viewport math, marker building, price-line building, polling state, fetch-result summarization, initial-timeframe pickup, hover-overlay formatting) followed by a single `PriceChart` class that owns the lightweight-charts instance, the controls header, the ResizeObserver, the fetch state machine, and the document-level custom-event bus for arrow ↔ table linking.
- `static/js/position_detail.js` — modified to import `PriceChart` and call `PriceChart.init({account, instrument, entryExecutionId, entryTime, executions})` after the existing `/api/positions/.../` and `.../executions` fetches resolve. Also wires up the listeners for `chart:execution-clicked` and `executions-table:row-clicked` custom events so the existing executions table can flash and scroll on chart-driven clicks.
- `templates/position_detail.html` — drops the `Chart loads in plan 13` placeholder text from `<div id="chart-root">` and adds one `<script src="/static/vendor/lightweight-charts.standalone.production.js">` tag in the `{% block scripts %}` block before the existing module loader.

**Why this shape.** Doc 13 is unusually well-specified (22 acceptance criteria, six fragmentation hazards, six deviations). Most of the design is locked in by the spec. The genuine choices Plan 13 makes are: where `chart_defaults` lives until Plan 16 ships (a Python module stub, not a table); how the Lightweight Charts library reaches the browser (a committed vendor file, not a CDN); whether the markers payload is a dedicated endpoint or derived client-side from the existing `/executions` payload (dedicated endpoint, matching AC 12 verbatim); and the polling cadence for the fetch-now flow (2-second interval, 2-minute timeout, the same numbers doc 14 already suggests).

## Components

### `services/chart_defaults.py`

```python
DEFAULT_TIMEFRAME = "1m"
VOLUME_VISIBLE_DEFAULT = True

def get_defaults() -> dict:
    return {
        "default_timeframe": DEFAULT_TIMEFRAME,
        "volume_visible_default": VOLUME_VISIBLE_DEFAULT,
    }
```

Plan 16 replaces the body with a SELECT against a `chart_defaults` table. The function name is the seam; Plan 13's route and the `pickInitialTimeframe` helper in `PriceChart.js` both go through it.

### `models/markers.py::Marker`

```python
class Marker(StrictModel):
    time: int          # unix seconds, UTC
    price: float
    side: Literal["Buy", "Sell"]
    quantity: int
    label: str         # un-suffixed nt_execution_id
```

Exported from `models/__init__.py`. Reused by the markers route and the markers service.

### `services/markers.py::build_markers`

```python
def build_markers(executions: list[Execution]) -> list[Marker]:
    """One marker per real execution (suffixes stripped). Order preserved."""
```

Pure function. No DB access. Suffix-strips via the helper from Plan 12's `services/notes.py` (or a small local copy if importing across services is awkward — the plan will pick one and document it). Returns `Marker` records ordered by `(timestamp, nt_execution_id)`.

### Routes

**`GET /api/chart/{instrument}/timeframes-available`**

Implementation:

```sql
SELECT timeframe, COUNT(*) AS bar_count
  FROM bars
 WHERE instrument = :instrument
 GROUP BY timeframe
```

Merge against the canonical `["1m","5m","15m","1h","4h","1d"]` order so missing timeframes come back with `available: false, count: 0`. Response shape:

```json
{
  "timeframes": [
    {"timeframe": "1m", "available": true,  "count": 4321},
    {"timeframe": "5m", "available": true,  "count": 864},
    {"timeframe": "15m","available": false, "count": 0},
    ...
  ],
  "default_timeframe": "1m"
}
```

`default_timeframe` comes from `chart_defaults.get_defaults()`. Reads only — never fetches.

**`GET /api/positions/{account}/{instrument}/{entry_execution_id}/markers`**

Loads executions via the existing `positions_service.get_position_detail` lookup, hands the executions to `build_markers`, returns `{markers: [...]}`. 404 if the position doesn't resolve. Reuses the same `(account, instrument, entry_execution_id)` natural-key parsing as Plan 12's existing position-detail route. No new DB queries beyond the existing detail lookup.

### `static/js/PriceChart.js` — internal structure

```javascript
// --- Pure helpers (no DOM, no fetch, no library refs) ---
export function computeVisibleRange(entryTime, barCount, secondsPerBar) { ... }
export function buildMarkersFromExecutions(executions) { ... }
export function buildPriceLines(executions, avgEntryPrice, side) { ... }
export function summarizeFetchResult(barsArray) { ... }      // 'ok' | 'no-data' | 'delayed'
export function nextPollDelay(elapsedMs) { ... }              // 2000 until 120000, then null
export function pickInitialTimeframe(available, configured) { ... } // AC 10 fallback
export function formatOhlcOverlay(bar, prevClose) { ... }     // AC 15 hover overlay text

// --- Constants ---
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 120000;
const CANONICAL_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

// --- The class ---
export class PriceChart {
  static init({account, instrument, entryExecutionId, entryTime, executions}) { ... }
  // wires: container element, controls header (timeframe button group + volume toggle),
  //        ResizeObserver, fetch state machine, AbortController for in-flight fetches,
  //        no-data CTA + fetch-job poller, delayed-data banner, loading indicator,
  //        error message + retry, document-level custom-event bus for arrow↔table linking
}
```

Pure helpers are factored to the top so they're inspectable and a future plan could add a JS test runner without rewriting. Plan 13 itself ships no JS test infrastructure — verification of the chart is the browser walkthrough described below.

### State machine

`PriceChart` has a single `state` field with values:

- `loading` — fetch in flight; loading indicator visible over the canvas
- `ok` — bars rendered; chart fully interactive
- `no-data` — empty array returned; no-data placeholder + "Fetch data now" button
- `delayed` — bars rendered (possibly partial) + "Chart data is currently delayed" banner overlay
- `error` — read failed; inline error message + Retry button

Transitions:

- Initial render: `loading` → `ok` | `no-data` | `delayed` | `error`
- Timeframe click: cancel any in-flight fetch via `AbortController`, transition to `loading`, fetch new range, transition again
- Volume toggle: instantaneous, no state transition (data unchanged)
- "Fetch data now" click: `no-data` → `loading` → POST `/api/chart/{instrument}/fetch` → poll `GET /api/ohlc/jobs/{job_id}` every 2s until `done` / `failed` / 120s timeout → re-fetch bars → `ok` | `no-data` | `delayed`
- Retry click (from `error`): same as initial render

A second timeframe click during an in-flight fetch cancels via `AbortController` and starts a new request (AC 18).

### Arrow ↔ executions-table linking

Two `document`-level custom events:

- **`chart:execution-clicked`** with `detail: {executionId}` — fired by `PriceChart` when the user clicks an arrow. `position_detail.js`'s executions-table renderer listens, finds the matching row by data attribute, scrolls it into view, and adds a brief highlight class.
- **`executions-table:row-clicked`** with `detail: {executionId}` — fired by the table renderer when the user clicks a row. `PriceChart` listens, finds the matching marker, scrolls the chart's visible range so the marker is centered, and gold-flashes the arrow for ~2 seconds.

Both events are dispatched on `document` so the listeners don't need direct references to each other. This keeps `PriceChart` and `position_detail.js` decoupled.

### Vendor file: TradingView Lightweight Charts v5

`static/vendor/lightweight-charts.standalone.production.js` is committed to the repo. The file is the v5 standalone production build downloaded once from the official TradingView CDN. The plan task that adds the file records the exact upstream URL and the SHA-256 of the committed file in its commit message, so future upgrades are auditable.

The file is loaded via a plain `<script src="...">` tag in `position_detail.html`'s `{% block scripts %}`, before the existing module loader for `position_detail.js`. The library exposes a global `LightweightCharts` object, which `PriceChart.js` references directly — there is no `import` for it (it is not an ES module).

Why a vendor commit instead of a CDN: zero runtime network dependency, works offline, works inside Docker without internet, no third-party uptime tied to the page that's supposed to gracefully degrade when OHLC sources are down (Rule 6's spirit). The cost is one ~250 KB file in the repo and a manual upgrade step; both are acceptable for a single-user app.

## File layout

```
/
├── migrations/                          # NO new migrations
├── models/
│   ├── markers.py                       # NEW: Marker StrictModel
│   └── __init__.py                      # MODIFY: export Marker
├── services/
│   ├── chart_defaults.py                # NEW: get_defaults() stub for Plan 16
│   └── markers.py                       # NEW: build_markers(executions)
├── routes/
│   ├── chart.py                         # MODIFY: add /api/chart/{instrument}/timeframes-available
│   └── positions.py                     # MODIFY: add /api/positions/{a}/{i}/{e}/markers
├── templates/
│   └── position_detail.html             # MODIFY: vendor script tag, drop placeholder text
├── static/
│   ├── vendor/
│   │   └── lightweight-charts.standalone.production.js  # NEW: committed v5 vendor file
│   └── js/
│       ├── PriceChart.js                # NEW: the one chart class
│       └── position_detail.js           # MODIFY: import & init PriceChart
└── tests/
    ├── test_chart_defaults.py           # NEW
    ├── test_markers_service.py          # NEW
    ├── test_routes_chart_timeframes.py  # NEW
    ├── test_routes_position_markers.py  # NEW
    └── test_app_factory_plan13.py       # NEW (smoke: blueprints registered, routes wired)
```

Total: 5 NEW Python files, 1 NEW JS file, 1 NEW vendor file, 3 MODIFIED files. No new migrations. No new dependencies in `requirements.txt`.

## Task breakdown

Each task = failing test → implementation → green → conventional commit. Same cadence as Plan 12.

1. **`services/chart_defaults.py` + tests** — `feat(charting): chart_defaults stub for plan 16 seam`
2. **`models/markers.py` Marker StrictModel + tests** — `feat(charting): Marker model`
3. **`services/markers.py::build_markers` + tests** (suffix stripping, ordering, side/qty mapping) — `feat(charting): build_markers pure function`
4. **`GET /api/chart/{instrument}/timeframes-available` route + tests** — `feat(charting): timeframes-available route`
5. **`GET /api/positions/.../markers` route + tests** — `feat(charting): position markers route`
6. **Vendor commit: `static/vendor/lightweight-charts.standalone.production.js`** with download URL + SHA in commit message — `chore(charting): vendor lightweight-charts v5 standalone`
7. **`templates/position_detail.html`** — drop placeholder, add vendor `<script>` tag — `feat(charting): wire vendor script into detail template`
8. **`static/js/PriceChart.js`** — pure helpers + class + state machine — `feat(charting): PriceChart.js`
9. **`static/js/position_detail.js`** — import PriceChart, call `init`, wire custom-event listeners — `feat(charting): position_detail.js mounts PriceChart`
10. **`tests/test_app_factory_plan13.py`** — smoke test that both new routes are wired and respond — `test(charting): app factory smoke for plan 13 routes`
11. **`ruff check .` + `ruff format --check .`** — `chore(charting): ruff format pass`
12. **End-to-end Docker verification + AC 1–22 browser walkthrough**, then update `00-README.md` progress table — `docs(rebuild-spec): record Plan 13 completion`

Roughly 12 commits, fewer than Plan 12's 20 because there's no migration, no schema, and no second blueprint family.

## Load-bearing rules from the spec

These rules will appear verbatim in the implementation plan's "Load-bearing rules" section. If any task is about to violate one, stop.

1. **Exactly one chart implementation.** One `PriceChart.js`, one class, one constructor, one mount point. No `SimpleChart`, no `ChartComponentManager`, no alternates. Doc 13 hazard 1 + AC 22.
2. **The chart endpoint never fetches.** `GET /api/chart/{instrument}` (already shipped by Plan 14) reads `bars` only. Plan 13's two new routes also read-only. If data is missing the user clicks fetch-now; nothing auto-fetches. Doc 13 hazards 3 and 6, plus Rule 6.
3. **No numeric position IDs.** The markers route uses `(account, instrument, entry_execution_id)` natural-key path params. No `position_id` anywhere — URL, JS, payload, or service.
4. **No auto-fallback behaviors.** If the user's selected timeframe has no data, show the no-data placeholder — do not auto-switch. The only automatic timeframe selection is the *initial* default from `pickInitialTimeframe(available, configured)` (AC 10). Doc 13 hazard 6.
5. **Templates are shells.** `position_detail.html` gets one new `<script src>` tag for the vendor file and one placeholder removal. All chart logic lives in `PriceChart.js`. No inline `<script>` blocks beyond the existing module loader and the new vendor `<script src>`. Rule 5 + doc 13 hazard 4.

## What this plan deliberately does NOT do

- **No new migrations, no new tables, no schema churn.** `chart_defaults` stays a Python stub until Plan 16.
- **No `chart_defaults` settings page.** That's Plan 16's surface.
- **No standalone `/charts/{instrument}` page or chart gallery.** Removed by doc 13 deviation 1.
- **No new OHLC fetcher, no new circuit-breaker config, no new `bars` writes from the chart route.** Plan 14 owns that surface entirely.
- **No JS unit-test runner.** Pure helpers are factored to be testable later, but Plan 13 ships zero new test infrastructure. Verification is pytest for backend + browser walkthrough for frontend.
- **No arrow-tooltip floating card.** Removed by doc 13 deviation 5; AC 16/17 cover the same information via row linking.
- **No quantity-scaled or width-scaled arrows.** Uniform size per AC 13 / doc 13 deviation 6.
- **No new dependencies in `requirements.txt`.** The vendor file is the only new external code.
- **No new endpoint families.** The two new routes register on existing blueprints (chart and positions).

## Decisions captured during brainstorming

These five decisions are the only places where doc 13 left genuine room for choice. The rationale is recorded here so the implementation plan and any future reviewer can see why Plan 13 looks the way it does.

1. **`chart_defaults` until Plan 16: Python module stub, not a table.** A function-level seam (`services/chart_defaults.get_defaults()`) lets Plan 16 swap the implementation later without touching the frontend, the routes, or the tests. A premature migration would build Plan 16's storage without its UI and violate the "one plan at a time" rule.
2. **Lightweight Charts: committed vendor file, v5 standalone production build.** The only option consistent with Plan 12's no-bundler, no-Node, no-network philosophy. CDN at runtime would tie the chart's reliability to an unrelated third party. The committed file is ~250 KB and pinned by content; the upgrade procedure is documented.
3. **Markers endpoint: build it, do not derive in JS.** AC 12 names the endpoint and its payload shape verbatim. The duplication with `/executions` is small (~30 LOC of route + service + test) and the dedicated endpoint gives the marker-builder logic a clean unit-tested home (`build_markers`) instead of hiding it in `PriceChart.js`.
4. **Polling cadence: 2-second interval, 2-minute total timeout.** Doc 14's own suggestion. Lives as constants at the top of `PriceChart.js`.
5. **JS testing: match Plan 12 (none).** Backend gets full pytest coverage; frontend is verified manually via the Docker smoke test and an AC 1–22 browser walkthrough. Mitigation: pure helpers are factored to the top of `PriceChart.js` so a future plan can add a JS test runner without rewriting.

## Verification

- `pytest -q` — all new tests + 351 existing tests stay green
- `ruff check .` and `ruff format --check .` — clean
- Docker end-to-end: `docker compose up -d --build` → drop a CSV → open `/positions/{a}/{i}/{e}` in a browser → walk every AC 1–22 → `docker compose down`
- The AC walkthrough is recorded as a numbered checklist in the implementation plan's final task; each AC is marked off only after observing the behavior in a real browser.
