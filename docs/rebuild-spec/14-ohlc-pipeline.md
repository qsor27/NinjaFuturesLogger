# Feature 14 — OHLC Data Pipeline

## Purpose

Fetch candlestick (OHLC) data for the instruments the trader uses, store it locally in SQLite, and serve it fast. The pipeline runs in the background, triggered automatically when new executions arrive and on a schedule to keep recent data fresh.

OHLC data is a **visual aid**, not a source of truth. P&L, stats, positions, notes, imports, and monitoring all work without it. When the chart is empty or stale, the user sees a notice and the rest of the app keeps running.

## Dependencies

- **Doc 02** — Glossary entries for OHLC, timeframe, bar, missing candles, Missing Candle Retrieval, coverage.
- **Feature 11** — New executions imply new time ranges that may need market data.
- **Feature 13** — Charts read from the `bars` table.
- **Feature 16** — Per-source symbol mappings live in `instruments.json`.

## Non-goals and graceful degradation

**OHLC is an isolated subsystem.** If every configured data source is down for a week, the rest of the application must continue to function normally:

- Imports continue to process CSV files.
- Executions continue to land in the `executions` table.
- Positions continue to compute from executions (doc 11).
- P&L, win rate, stats, and reports continue to render from executions.
- Notes, tags, and the monitoring dashboard continue to work.
- The chart page loads, but shows a banner: "Chart data is currently delayed. Positions and statistics are unaffected."

The only user-visible degradation is that the chart on the position detail page cannot display bars for time ranges not already in the local store. Operationally, this means **no request handler anywhere in the app ever blocks on an OHLC fetch**. If a handler needs OHLC, it either serves what's already in the `bars` table or it returns "not yet available" and lets the client re-poll. OHLC fetches are always fire-and-forget from the HTTP path's perspective.

This isolation is enforced structurally:

- The `bars` table has no foreign keys pointing at it from `executions`, positions, stats, or any other table.
- No service outside `services/ohlc/` imports from inside it for anything other than reading the `bars` table.
- The chart data route reads `bars` directly; it does not call the fetcher synchronously.
- The fetcher runs in the background thread pool (doc 03), never in a request thread.

If this invariant is ever broken by a future change — e.g., someone makes the positions page "wait for OHLC to be ready" — the failure mode of the whole app becomes tied to Yahoo Finance's uptime, and the graceful-degradation property is gone. Treat it as a hard rule.

## Source model: primary + fallback, different formats

**Primary: yfinance.** Python library that scrapes Yahoo Finance. Covers most of the instruments a futures trader uses (continuous contracts like `MNQ=F`, `ES=F`, specific contracts via the `.CME` suffix). Fast, no API key. Fragile — Yahoo breaks it periodically by changing cookie/crumb handling or rate limits. When it's up, it's the best free option for futures intraday data.

**Fallback: Stooq.** Zero-auth CSV endpoint (`https://stooq.com/q/d/l/?s={symbol}&i={interval}`). Covers most continuous futures contracts and many specific ones. Different codebase, different infrastructure, different failure modes than yfinance — which is the entire point of having it. Data is often end-of-day or coarser for intraday, and may be delayed 15+ minutes.

**The two sources return completely different data formats.** This is a first-class concern for the pipeline, not an afterthought. A short comparison:

| Aspect | yfinance | Stooq |
|---|---|---|
| Transport | Python library wrapping HTTP | Plain HTTP GET of a CSV file |
| Response type | `pandas.DataFrame` | CSV text |
| Index/time column | `DatetimeIndex`, timezone-aware | `Date` or `Date,Time` columns, no timezone |
| Timezone convention | Usually exchange-local, varies | Exchange local time, undocumented |
| Columns | `Open, High, Low, Close, Volume, Adj Close` | `Date[,Time],Open,High,Low,Close,Volume` |
| Timeframes available | 1m (last 7 days only), 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo | Mostly daily; some intraday via a separate endpoint, coarser granularity |
| Volume dtype | integer, sometimes NaN | integer, often empty string for futures |
| Adjusted close | Present | Not provided |
| Symbol format | `MNQ=F`, `MNQU25.CME` | `mnq.f`, often lowercase, different separator |
| Empty result | Empty DataFrame | Empty CSV body, sometimes 200 OK with single header row, sometimes 404 |
| Rate limit | Informal; Yahoo silently throttles | Undocumented; generous in practice |

The pipeline never lets these format differences leak out of the per-source parser. Each source has a `fetch()` method that returns a `list[Bar]` — a normalized, validated, timezone-aware, UTC-timestamped list of records. Downstream code (the fetcher orchestrator, the store, the cache, the chart route) sees only `Bar`. Yahoo-specific column names and Stooq-specific date parsing live inside their respective adapter files and nowhere else.

## The `Bar` normalized record

```python
class Bar(BaseModel):
    instrument: str          # canonical NT instrument key, not the source-specific symbol
    timeframe: str           # '1m','5m','15m','1h','4h','1d' — canonical set
    time: int                # unix seconds, UTC, always
    open: float
    high: float
    low: float
    close: float
    volume: int              # 0 if source didn't provide one, never None
    source: str              # 'yfinance' | 'stooq' | ... — which source produced it
```

Rules:

- **Timestamps are always UTC unix seconds.** Each source adapter is responsible for converting whatever timezone it received into UTC before constructing a `Bar`.
- **`volume` is never None.** Stooq occasionally returns blank volume for thin futures contracts; the adapter converts blank to `0` rather than propagating None into SQLite, where it would break integer aggregation.
- **`instrument` is the canonical key**, not the source-specific symbol. The adapter maps in both directions using `instruments.json`.
- **`source` is preserved on every bar**, so the monitoring dashboard can tell the operator "these 47 bars were filled in from Stooq because Yahoo was down Tuesday morning."
- **No adjusted-close field.** The chart displays unadjusted futures prices. Yahoo's `Adj Close` is dropped at the adapter boundary.

## The source protocol

```python
from typing import Protocol

class OhlcSource(Protocol):
    name: str                      # 'yfinance', 'stooq', ...
    supported_timeframes: set[str] # e.g. {'1m','5m','15m','1h','1d'} for yfinance

    def fetch(
        self,
        instrument: str,
        timeframe: str,
        start: int,               # unix seconds, UTC, inclusive
        end: int,                 # unix seconds, UTC, exclusive
    ) -> list[Bar]: ...
```

Each source implementation lives in its own file:

```
services/ohlc/
  __init__.py
  source.py          # OhlcSource protocol, Bar model
  yfinance_source.py # primary
  stooq_source.py    # fallback
  registry.py        # ordered source list + per-source circuit breaker
  fetcher.py         # orchestrates: try primary, fall back to fallback, write bars
  store.py           # SQLite read/write over the bars table
  gap_detection.py   # given a range, returns the minimal missing sub-ranges to fetch
```

## Per-source failure isolation

Each source has its own circuit breaker tracked in memory (not Redis — there is no Redis). The breaker has three states: `closed` (normal), `open` (recent failures, don't call), `half_open` (probationary call allowed after cooldown).

State transitions:

- **Closed → Open**: three consecutive `fetch()` errors, or a single error of type `HTTPError(429)` or `HTTPError(5xx)`.
- **Open → Half-open**: after `cooldown_seconds` (default 600s for yfinance, 1800s for Stooq — Yahoo fails fast and recovers fast; Stooq failures tend to be longer outages).
- **Half-open → Closed**: the probationary call succeeds.
- **Half-open → Open**: the probationary call fails; reset the cooldown.

While a source's breaker is open, the fetcher silently skips it and moves to the next source in the registry. If all sources are open, the fetcher returns `FetchResult(status=all_sources_unavailable, bars_added=0, next_retry_at=…)` without raising. The caller (the background job) logs the result and schedules a retry; request handlers never see this state because they don't call the fetcher directly.

## The fetcher orchestrator

```python
def fetch_range(instrument: str, timeframe: str, start: int, end: int) -> FetchResult:
    # 1. Ask the store what's already present in [start, end).
    missing = gap_detection.find_gaps(instrument, timeframe, start, end)
    if not missing:
        return FetchResult(status=Status.CACHED, bars_added=0)

    bars_collected: list[Bar] = []
    attempted: list[AttemptRecord] = []

    for gap_start, gap_end in missing:
        for source in registry.sources_for(timeframe):
            if not source.breaker.allows():
                attempted.append(AttemptRecord(source.name, skipped=True))
                continue
            try:
                bars = source.fetch(instrument, timeframe, gap_start, gap_end)
                source.breaker.record_success()
                bars_collected.extend(bars)
                attempted.append(AttemptRecord(source.name, ok=True, count=len(bars)))
                break  # this gap filled; move to next gap
            except Exception as e:
                source.breaker.record_failure(e)
                attempted.append(AttemptRecord(source.name, failed=True, error=str(e)))
                continue
        else:
            # All sources failed or are open for this gap.
            pass

    if bars_collected:
        store.insert_many(bars_collected)   # UPSERT on (instrument, timeframe, time)

    return FetchResult(
        status=summarize(bars_collected, missing),
        bars_added=len(bars_collected),
        attempts=attempted,
    )
```

Rules:

- **Sources are tried in registry order per gap.** Once a gap is filled by one source, the next source is not called for the same gap.
- **A gap that one source can't fill can still be filled by the next source.** Yahoo might have 1m data for a range while Stooq only has 5m — `registry.sources_for('1m')` returns only Yahoo, and if Yahoo is down, the fetcher returns a partial result rather than silently upscaling.
- **Upscaling is forbidden.** If the requested timeframe is 1m and only 5m is available, the fetcher returns what 1m data it can get and reports the rest as unavailable. The UI decides whether to offer "show me 5m instead" — the pipeline does not synthesize 1m bars by downsampling 5m bars.
- **`store.insert_many` uses UPSERT** (`INSERT ... ON CONFLICT(instrument, timeframe, time) DO UPDATE`). Re-fetching an existing range rewrites the bars cleanly. Source priority is implicit: whichever source last wrote a bar wins. This is fine because a successfully-fetched bar from Yahoo and a successfully-fetched bar from Stooq should agree (they both reflect real market prices); if they disagree, the monitoring dashboard surfaces it.

## Triggers (how fetches get scheduled)

Three contexts, all running in the background thread pool or via APScheduler (doc 03). None of these run inside an HTTP request handler.

1. **Post-import** — after the import pipeline commits new executions (doc 10), it submits one `fetch_range` call per distinct `(instrument, timeframe)` to the thread pool, covering the time range of the new executions ± a 1-hour buffer on each end. This is fire-and-forget. The import pipeline does not wait for these to complete before returning.
2. **Scheduled refresh** — an APScheduler job runs every 15 minutes and calls `fetch_range` for the last 6 hours across all instruments that have any execution in the last 7 days. A second job runs every 4 hours and refreshes the last 7 days for the same set. Both jobs tolerate source outages gracefully — they log and move on.
3. **On-demand** — `POST /api/chart/{instrument}/fetch` from the UI submits a fetch for a specific range to the thread pool and returns a job ID. The client polls `GET /api/ohlc/jobs/{job_id}` to know when the data is ready. This is the only user-visible fetch trigger.

## The store

```sql
CREATE TABLE bars (
  instrument TEXT NOT NULL,
  timeframe  TEXT NOT NULL,     -- '1m','5m','15m','1h','4h','1d'
  time       INTEGER NOT NULL,  -- unix seconds, UTC
  open       REAL NOT NULL,
  high       REAL NOT NULL,
  low        REAL NOT NULL,
  close      REAL NOT NULL,
  volume     INTEGER NOT NULL,  -- 0 if source didn't provide
  source     TEXT NOT NULL,     -- 'yfinance', 'stooq', ...
  fetched_at INTEGER NOT NULL,  -- unix seconds, when this bar was written
  PRIMARY KEY (instrument, timeframe, time)
);
CREATE INDEX idx_bars_instrument_tf_time ON bars(instrument, timeframe, time);
```

No surrogate ID. The composite key is the natural identifier. `source` and `fetched_at` exist for forensic purposes — "where did this bar come from and when did we get it" — and are surfaced in the monitoring dashboard.

## Gap detection

`gap_detection.find_gaps(instrument, timeframe, start, end)` returns the minimal list of `(sub_start, sub_end)` ranges not currently covered by bars in the store. Implementation is one SQL query:

```sql
SELECT time FROM bars
WHERE instrument = ? AND timeframe = ? AND time >= ? AND time < ?
ORDER BY time
```

Walk the result, compare against the expected stride for the timeframe (60 for 1m, 300 for 5m, etc.), and emit any run of missing slots. "Expected" bars only exist during the instrument's trading session — gap detection consults the session calendar from `instruments.json` to avoid treating the overnight close as a missing range.

## Configuration

`data/config/instruments.json` gains per-source mappings and a session calendar:

```json
{
  "instruments": {
    "MNQ": {
      "display_name": "Micro NASDAQ",
      "multiplier": 2.0,
      "tick_size": 0.25,
      "sources": {
        "yfinance": {
          "continuous": "MNQ=F",
          "contract_template": "MNQ{month}{year}.CME"
        },
        "stooq": {
          "continuous": "mnq.f"
        }
      },
      "session": {
        "timezone": "America/Chicago",
        "open": "17:00",
        "close": "16:00",
        "daily_break": { "start": "16:00", "end": "17:00" }
      }
    }
  },
  "default_timeframes": ["1m", "5m", "15m", "1h", "1d"],
  "source_registry": ["yfinance", "stooq"],
  "circuit_breaker": {
    "yfinance": { "failure_threshold": 3, "cooldown_seconds": 600 },
    "stooq":    { "failure_threshold": 3, "cooldown_seconds": 1800 }
  }
}
```

`source_registry` is the order the fetcher tries sources. Changing it is a config edit; no code changes needed.

**On `default_timeframes`:** `4h` is a valid canonical timeframe (see doc 02's glossary, the `bars` table, and `chart_defaults`'s CHECK constraint in doc 16), but is deliberately omitted from default fetches — it is not a useful interval for the intraday futures workflow this app targets. The pipeline already supports it end-to-end; an operator who wants `4h` data adds it to this list and the scheduled refresh jobs pick it up on the next run.

**On circuit-breaker fast-trip policy:** the `failure_threshold` config field governs the "three consecutive errors → open" rule. The "single `HTTPError(429)` or `HTTPError(5xx)` → open" rule described earlier is a hardcoded policy, not a configurable threshold — it exists to protect upstream services from us as much as to protect us from them, and loosening it per-source is not a supported operation. If a new source needs different fast-trip semantics, that's a code change in its adapter, not a config edit.

## API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/chart/{instrument}` | Read OHLC bars. Reads `bars` only. Never fetches. |
| POST | `/api/chart/{instrument}/fetch` | Queue a fetch for a specific range. Returns job ID. |
| GET | `/api/ohlc/jobs/{job_id}` | Poll fetch job status. |
| GET | `/api/ohlc/sources` | Per-source status: circuit state, last success, last failure, last error. For the monitoring dashboard. |

## Fragmentation hazards

1. **Read paths that fetch.** The old `/api/chart-data/{instrument}` hit Yahoo Finance synchronously inside the request, blocking the UI for seconds and — worse — tying the chart page's reliability to Yahoo's uptime. **Rule:** the chart read endpoint never fetches. If data is missing, it returns a "missing range" response with a suggestion for the client to trigger an explicit fetch. The client triggers. The fetch runs in the background. The client polls.

2. **Format leakage.** If any code outside `yfinance_source.py` or `stooq_source.py` sees a pandas DataFrame, a Yahoo column name like `Adj Close`, a Stooq CSV row, or a naive `datetime`, the normalization layer has failed. **Rule:** every path out of a source adapter returns `list[Bar]`. If an adapter can't produce `Bar` objects from a response, it raises — it does not return "partially normalized" data.

3. **Shared symbol mapping.** The old code had `symbol_service.py` and `instrument_mapper.py` with overlapping responsibilities. **Rule:** one `InstrumentRegistry` service backed by `instruments.json`. Source adapters call `registry.source_symbol(instrument, source_name)` to get their per-source symbol. Nothing hardcodes a ticker anywhere else.

4. **"Background data manager" as a hidden second pipeline.** The old codebase had a `background_data_manager.py` running its own retrieval logic in parallel with `tasks/gap_filling.py`. **Rule:** there is one fetcher (`services/ohlc/fetcher.py`). Background triggers are APScheduler jobs and thread pool submissions that call the fetcher. There is no second fetcher, no "pre-warmer," no "completeness watcher" with its own retrieval loop.

5. **Cache that doesn't invalidate.** The old code wrote new bars but didn't always evict entries in the chart-data cache that overlapped. **Rule:** the store does not have a separate cache layer. SQLite is the cache. The OS page cache is the hot-data cache. If a page is slow, add an index or denormalize — do not introduce Redis.

6. **Synchronous OHLC in the position page.** The old codebase had code paths in `routes/positions.py` that waited for OHLC fetches before rendering, making the position list page unusable during Yahoo outages. **Rule:** no route outside `services/ohlc/` ever calls the fetcher. The position pages read from `bars` if they need chart data for a preview; if the data isn't there, they render without it.

7. **Mixing sources within a single bar range without audit trail.** If one range is half-filled by Yahoo and half by Stooq, it must be possible to tell which source produced which bar. **Rule:** the `bars.source` column is always populated. Monitoring exposes a per-source breakdown.

## Deviations from old behavior

- The "data completeness service" with its own monitoring loop is gone. Completeness is computed on demand by feature 17 from SQL queries against `bars` + session calendar.
- The "expected minimum bars per timeframe" heuristic is replaced by honest gap detection that understands the instrument's session calendar.
- Pre-warming is removed. Scheduled refresh covers "keep recent data fresh"; one-shot post-import fetches cover "make sure the trade I just imported is chartable." Any bar that's never been charted is never fetched. Disk and quota aren't wasted on ranges the user will never view.
- The old single-source `YahooFinanceClient` is replaced by the source registry. yfinance is one implementation, Stooq is another. Adding Databento or a different fallback is a new file in `services/ohlc/` and an entry in `source_registry`; nothing else changes.

## Open questions for the implementer

- **How long should the client poll for a pending fetch?** Suggest 2-minute timeout with 2-second intervals. If the fetch isn't done in 2 minutes, the UI tells the user "still working, check back later" and stops polling. The job itself continues.
- **Do we want a `GET /api/ohlc/bars/{instrument}/{timeframe}/missing` endpoint** that returns the current gap list for a range, so the monitoring dashboard can show "MNQ 1m has 37 missing bars in the last week"? Yes, but this is a feature-17 concern — decide there.
- **Stooq intraday support depth.** Stooq's intraday endpoint (`i=5` for 5-minute) works for some symbols and not others, and the library of supported intervals is narrower than yfinance. The Stooq adapter should declare `supported_timeframes` conservatively (default `{'1d'}`; add intraday intervals as they're verified per-instrument). This keeps the fetcher from calling Stooq for 1m data it can't supply.
