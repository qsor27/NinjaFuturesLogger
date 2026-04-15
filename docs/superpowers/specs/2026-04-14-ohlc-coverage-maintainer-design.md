# OHLC Coverage Maintainer — Design

**Date:** 2026-04-14
**Status:** Draft, awaiting user review
**Supersedes parts of:** plan 14 (OHLC adapters), plan 18 (circuit breaker tuning)

## Problem

The OHLC subsystem today leaves visible gaps on the data-health page that the user
has to click through manually. Three deeper issues sit underneath that symptom:

1. **No continuous coverage model.** OHLC is pulled opportunistically (post-import
   ±1h window, 15-min recent refresh, 4-hour week refresh). Nothing actively walks
   a gap list and fills it. Anything older than 7 days stays missing forever unless
   the user presses "Fetch Missing" in the detail panel.
2. **Wrong prices on back-month contracts.** `source_symbol()` strips the contract
   suffix and returns the continuous series (`NQ=F`), so every row in `bars` for
   any contract other than the currently-front-month is mis-tagged continuous data.
   Two contracts traded the same day at different prices will display the same
   continuous bars on their position detail pages.
3. **Permanent false positives on the data-health matrix.** `4h` is in the
   canonical-timeframe list but no source serves it, and slots beyond the
   provider's reach (yfinance 1m → 30 days) are flagged missing identically to
   slots that are just-not-fetched-yet.

## Goals

- Continuous OHLC coverage per active contract across `1m, 5m, 15m, 1h, 1d, 1wk, 1mo`.
- Per-contract correctness: bars attached to `"MNQ JUN26"` are actually JUN26 data.
- Respect yfinance rate limits; zero 429 bursts under normal operation.
- Worst-case visible lag ≤ 45 min (15 min Yahoo delay + 30 min refresh cadence).
- No user button-clicking required to get a complete chart.
- Honest data-health reporting: distinguish `out_of_reach`, `pending`, and actual
  `missing`.

## Non-goals

- Real-time (sub-15-minute) OHLC. CME charges for real-time; we accept delayed.
- Paid data sources. Polygon / Databento / CME-direct are deferred.
- Synthetic/derived candles stored to disk. The one exception (4h) is a read-time
  view transform over stored 1h bars, never persisted.
- Per-instrument configurable refresh cadence. One global schedule.
- Touching `ninjascript/ExecutionExporter.cs` or the CSV column contract.

## Load-bearing decisions

These cannot be changed without re-doing the design.

- **Coverage maintainer is a single scheduler-driven job**, not a post-import hook.
- **One global token bucket** (30 tokens, refill 30/min) governs every outbound
  OHLC call. This is the ONLY rate-limiting mechanism — no per-source buckets.
- **Per-contract fetching is mandatory** for yfinance; continuous symbols are never
  used as a silent fallback for specific contracts.
- **4h is a read-time view transform only.** It is never fetched, never stored,
  never listed on data-health.
- **Contract state (`active`/`winding_down`/`retired`) is a materialized view**
  derived from `executions` plus user overrides — not user data.
- **Existing bars are purged** on first startup after the migration. No attempt is
  made to salvage rows that "happen to be correct."

## Architecture

### Timeframe schedule

| TF    | Source                        | Cadence                                 | Reach      |
|-------|-------------------------------|-----------------------------------------|------------|
| 1m    | yfinance                      | every 30 min (coverage maintainer)      | 7 days     |
| 5m    | yfinance                      | every 30 min                            | 60 days    |
| 15m   | yfinance                      | every 30 min                            | 60 days    |
| 1h    | yfinance                      | every 30 min                            | 730 days   |
| 1d    | yfinance → stooq fallback     | daily at 16:01 CT                       | unlimited  |
| 1wk   | yfinance                      | Fridays at 16:01 CT                     | unlimited  |
| 1mo   | yfinance                      | last calendar day of month at 16:01 CT  | unlimited  |
| 4h    | derived from stored 1h bars at read time | n/a — never fetched or persisted | tracks 1h |

"Last calendar day of the month" = whatever it is that month: 28 in February,
29 in a leap-year February, 30 or 31 elsewhere.

Historical sweep runs every **4 hours** and fills older gaps (up to the provider
reach) for `1m`, `5m`, `15m`, `1h`, `1d`. It does not run weekly or monthly
intervals — those have their own cron jobs.

### Rate-limit budget

One full active-contract refresh costs **5 yfinance calls per instrument** (one
per intraday timeframe, window clipped to reach). With 30-min cadence and a
30-tokens/min bucket, the safe ceiling is roughly 12 concurrently-active contracts
before the bucket becomes the limiting factor. Realistic steady state is 3–6.

### Coverage maintainer

One new APScheduler job, `ohlc_coverage_maintainer`, replaces:

- the post-import OHLC hook (`app.py::_ohlc_hook`)
- `ohlc_refresh_recent` (every 15 min, last 6h)
- `ohlc_refresh_week` (every 4h, last 7d)

Pseudocode:

```python
def coverage_maintainer_tick(db_path, registry, token_bucket):
    state = refresh_instrument_coverage_state(db_path)  # updates instrument_coverage
    active = [c for c in state if c.state == "active"]
    for contract in active:
        for tf, window in MAINTAINER_WINDOWS.items():  # 1m, 5m, 15m, 1h
            gaps = find_gaps(...)
            for gap in gaps:
                with token_bucket.acquire(timeout=60):
                    fetch_range(...)
```

A second job, `ohlc_historical_sweep`, runs every 4 hours and uses a larger
window table (`SWEEP_WINDOWS`) covering the full reach of each timeframe. It
shares the same token bucket, so a running sweep naturally yields to the
30-min refresh.

Daily / weekly / monthly jobs are separate APScheduler cron jobs:

- `ohlc_daily_refresh` — `cron(hour=16, minute=1, tz=America/Chicago)`
- `ohlc_weekly_refresh` — `cron(day_of_week='fri', hour=16, minute=1, tz=America/Chicago)`
- `ohlc_monthly_refresh` — custom trigger firing at 16:01 CT on the last day of
  each month (compute via `calendar.monthrange`).

### Token bucket

New module `services/ohlc/rate_limiter.py`:

```python
class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float, clock): ...
    def acquire(self, *, timeout: float) -> ContextManager: ...
    def available(self) -> int: ...
    def stats(self) -> dict: ...  # for the maintainer-status panel
```

- Capacity **30**, refill **0.5 tokens/sec** (= 30/min).
- Blocking acquire with bounded wait. On timeout, the caller logs and defers.
- One module-level instance owned by `create_app()`, injected into the fetcher.

The existing `fetcher.py::fetch_range` acquires a token before calling
`source.fetch()` and releases it on return. No other behavior change.

### Contract symbology

`instruments.json` gains real `contract_template` values for yfinance. Stooq
templates stay `null` — stooq only serves daily and doesn't have per-contract
symbols.

Template rendering uses CME month codes:

| Month | Code | Month | Code | Month | Code |
|-------|------|-------|------|-------|------|
| Jan   | F    | May   | K    | Sep   | U    |
| Feb   | G    | Jun   | M    | Oct   | V    |
| Mar   | H    | Jul   | N    | Nov   | X    |
| Apr   | J    | Aug   | Q    | Dec   | Z    |

Template form: `"{ROOT}{M}{YY}.CME"`. Examples:

- `MNQ JUN26` → `MNQM26.CME`
- `ES MAR26` → `ESH26.CME`
- `CL DEC26` → `CLZ26.CME`

`services/instruments.py::source_symbol(instrument, source)` behavior:

1. Parse `instrument` into `(root, contract_suffix)` via first-space split. If no
   space, `contract_suffix = None`.
2. Look up `root` in the registry.
3. If `contract_suffix` is present AND the source has a non-null `contract_template`,
   render and return the template.
4. If `contract_suffix` is absent, return `continuous`.
5. If the template is `null` (stooq), return `None` — the fetcher will skip this
   source for this instrument.
6. **Never** silently fall back to `continuous` for a suffixed instrument. A
   returned `None` is the only "give up" path.

### Contract state machine

New table `instrument_coverage` (migration 008):

```sql
CREATE TABLE instrument_coverage (
  instrument TEXT PRIMARY KEY,
  state TEXT NOT NULL
    CHECK (state IN ('active','winding_down','retired')),
  last_execution_at INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  retired_at INTEGER,
  updated_at INTEGER NOT NULL
);
```

State transitions, computed once per maintainer tick by
`services/ohlc/coverage_state.py::refresh_instrument_coverage_state`:

- `active` iff any execution in the last 30 days **OR** `pinned = 1` **AND**
  `retired_at IS NULL`.
- `winding_down` iff `last_execution_at` > 30 days ago, not pinned, not manually
  retired, AND the historical sweep still finds reachable gaps for it.
- `retired` iff manually retired **OR** (winding_down AND historical sweep
  completed a full pass with zero reachable gaps across all tracked timeframes).

A hard safety cap of **180 days** forces transition to `retired` regardless of
sweep state — prevents a permanently-spotty contract from polling forever.

Historical sweep processes `active + winding_down`. The 30-min refresh processes
`active` only. A contract in `winding_down` therefore gets attention only every
4 hours, and naturally retires once the sweep reports "nothing reachable to
fill."

**Rollover is not calendar-driven.** A new front-month contract becomes `active`
the first time the user trades it, because that updates its `last_execution_at`.
The old front-month stays `active` as long as the user keeps trading it. No
"prevailing contract" heuristic, no hardcoded roll dates.

**User overrides** on the instruments settings page:

- **Pin** — forces `active` regardless of execution recency.
- **Retire now** — immediate jump to `retired`, bypasses winding-down.
- **Reactivate** — from `retired` back to `active`. Coverage maintainer picks it
  up on the next tick.

### 4h view transform

New module `services/ohlc/aggregate.py`:

```python
def derive_4h(bars_1h: list[Bar]) -> list[Bar]:
    """Aggregate stored 1h bars into 4h bars. Never persisted.

    Block boundaries align to CME session convention (blocks start at 17:00 CT).
    A 4h bar is emitted only if all 1h constituents in its block are present.
    Partial blocks are silently omitted — the chart shows a gap.

    The 16:00-17:00 daily break splits naturally: the block that would
    otherwise be 13:00-17:00 is treated as 13:00-16:00 (3 bars present → not
    emitted as 4h — the chart falls back to showing 1h for that window).
    """
```

Consumers call it from the chart API route when `?tf=4h` is requested. Read-only,
pure, testable without any DB or network.

### Data-health page changes

New cell states:

- **`out_of_reach`** (gray) — slot falls outside the provider's reach for this
  timeframe. Not actionable. Computed in `gap_detection.py` using a new
  `provider_reach(timeframe) -> seconds` table.
- **`pending`** (light blue) — bars missing but a coverage job has been scheduled
  and hasn't completed. Distinguishes "we're working on it" from "we can't".

Other changes:

- **4h row removed entirely** from `CANONICAL_TIMEFRAMES`. `1wk` and `1mo` rows
  added.
- **Banner above the matrix**: `4h candles are derived from 1h bars at read
  time — no separate 4h data is stored or fetched.`
- **Stooq row in the sources panel** gets inline note: `daily bars only — used
  as fallback for 1d when yfinance is unavailable`.
- **New "Coverage Maintainer" panel** showing:
  - next scheduled run time
  - last run status + duration
  - requests in the last minute (from token bucket stats)
  - 429 count in the last 24h
- Existing "Fetch Missing" button is retained for manual one-offs.

### Circuit breaker tuning

Numbers change, machinery stays. Updated via `registry.py::build_default_registry`:

- yfinance: first 429 → **1 hour** cooldown (was 15 min). Second consecutive 429
  after cooldown → **4 hours**. Third → **12 hours**. 5xx/network errors keep
  their current 5-min base with existing 2x escalation.
- stooq: unchanged.

Rationale: a 429 means Yahoo already classifies us as a bot. Probing back in 15
min is how you escalate to a full-day IP ban.

## File layout

```
services/ohlc/
  coverage_maintainer.py   NEW
  rate_limiter.py          NEW
  aggregate.py             NEW
  coverage_state.py        NEW
  fetcher.py               MODIFIED — token acquire around source.fetch()
  yfinance_source.py       MODIFIED — uses rendered contract template
  stooq_source.py          MODIFIED — refuses contract-specific instruments
  registry.py              MODIFIED — retuned breaker numbers
  gap_detection.py         MODIFIED — out_of_reach classification

services/instruments.py    MODIFIED — source_symbol template rendering

routes/
  monitoring.py            MODIFIED — new cell states, maintainer panel
  settings.py              MODIFIED — pin / retire / reactivate endpoints

templates/
  data_health.html         MODIFIED — notices + maintainer panel
  instruments.html         MODIFIED — pin/retire controls

static/js/
  data_health.js           MODIFIED — new cell states, maintainer panel
  instruments.js           MODIFIED — pin/retire wiring

migrations/
  008_instrument_coverage.sql           NEW
  009_purge_mistagged_bars.sql          NEW
  010_update_instrument_templates.sql   NEW

app.py                     MODIFIED — drop post-import OHLC hook, drop
                                      ohlc_refresh_recent and ohlc_refresh_week,
                                      register coverage_maintainer,
                                      historical_sweep, and the daily/weekly/
                                      monthly cron jobs

background.py              UNCHANGED
```

## Migration plan

Three migrations run in order on first startup after deploy:

1. **008_instrument_coverage.sql** — creates the `instrument_coverage` table.
2. **009_purge_mistagged_bars.sql** — `DELETE FROM bars;` + a log line indicating
   the correctness-migration purge is complete.
3. **010_update_instrument_templates.sql** — populates `contract_template` for
   every yfinance entry in `instruments.json` (via a Python migration step, since
   `instruments.json` is outside the DB). Stooq entries untouched.

After migration runs, the coverage maintainer's first tick populates
`instrument_coverage` from executions and begins fetching. Expect ~4 hours for
the historical sweep to fill older windows within the token budget.

## Testing strategy

- **`test_rate_limiter.py`** — bucket math with monotonic clock; concurrent
  acquire; blocking with timeout; stats snapshot.
- **`test_coverage_state.py`** — state transitions; pin/retire/reactivate
  overrides; 30-day and 90-day thresholds; rollover via new executions.
- **`test_coverage_maintainer.py`** — with a fake `fetch_range` and fake clock,
  verify the right `(instrument, timeframe, window)` tuples get submitted per
  cadence; verify historical sweep uses wider windows; verify token-bucket
  yielding.
- **`test_aggregate_4h.py`** — 1h→4h block alignment at CME session boundaries;
  partial-block omission; daily-break handling.
- **`test_yfinance_source_contract.py`** — monkeypatched `_download`, verify
  `MNQ JUN26` → `MNQM26.CME` rendering and that returned bars carry the full
  instrument string; verify non-suffixed instruments still use continuous.
- **`test_stooq_source_contract.py`** — verify suffixed instruments get `None`
  back from `source_symbol` and the fetcher skips stooq for them.
- **`test_gap_detection_out_of_reach.py`** — slots beyond reach classified as
  `out_of_reach`, not `missing`.
- **`test_data_health_routes.py`** — new cell states; maintainer status fields;
  4h row absent; 1wk/1mo rows present.
- **`test_migrations_008_009_010.py`** — fresh DB and populated-bars DB; verify
  purge is total; templates populated; idempotent re-run safe.
- **Live smoke test** (manual, in the running container): delete `bars`, run
  maintainer for one 30-min cycle, confirm a traded contract fills correctly
  without any 429s in the sources snapshot.

## Acceptance criteria

1. After the app runs >4 hours in a clean state, `/api/data-health/completeness?days=30`
   returns **zero `missing` cells** for active contracts within provider reach.
   `out_of_reach` and `pending` are allowed; `partial` only transiently.
2. A position detail page for any traded contract displays bars sourced from
   that **exact contract**. Two contracts traded the same day at different prices
   show visibly different chart contexts.
3. No 429 in `/api/ohlc/sources` during normal operation with ≤12 active contracts.
4. "Fetch Missing" button still works but is never required for a complete chart.
5. Retiring a contract via settings stops fetches for it within one maintainer
   cycle; reactivating resumes them.
6. The purge migration runs once (recorded in `schema_migrations`) and never
   re-purges.

## Open risks the implementation plan must address

- **Per-contract yfinance data availability for older/thin contracts.** Known to
  be spotty — we accept this, show the gaps honestly, never fall back to
  continuous. Plan must include a smoke-test step against a real contract before
  shipping to confirm the template rendering works end-to-end.
- **CME 4h block boundary vs 16:00–17:00 daily break.** Plan nails down the
  concrete block-alignment rule and writes tests.
- **Token bucket starvation by historical sweep.** Plan mitigates with priority
  for the 30-min refresh — implementation-level detail.
- **Contract string parsing.** Assumes exactly one space between root and suffix.
  NinjaTrader exports match this, but a defensive parser with a clear error on
  malformed input is required.
