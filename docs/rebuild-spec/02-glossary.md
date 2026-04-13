# Glossary

Domain vocabulary for FuturesTradingLog. Read this before any feature doc — these terms are used precisely throughout the spec, and confusing them is the root cause of most fragmentation in the previous codebase.

## Trading concepts

**Execution** — A single fill from the broker. The atomic unit of trading activity. One row in the NinjaTrader CSV. May represent a partial fill of a larger order. Has a price, quantity, timestamp, side (Buy/Sell), and a unique execution ID assigned by NinjaTrader. Synonym in NinjaTrader's UI: "fill."

**Order** — An instruction sent to the broker (e.g., "buy 5 MNQ at market"). May result in one execution or several (partial fills). The new app **does not store orders** — only the executions they produced. Orders exist only as a reference field on each execution.

**Position** — A logical grouping of executions that opens, adjusts, and closes a directional exposure to one instrument on one account. A position starts when the running net quantity for that account+instrument leaves zero, and ends when it returns to zero. Between those two zero-crossings, every fill belongs to that position. A position has an entry time, exit time, side (Long or Short), total quantity, weighted-average entry and exit prices, P&L in points and dollars, and total commission.

**Action** — The raw order-action string written by NinjaTrader in the CSV's `Action` column. One of **four** values: `Buy`, `Sell`, `BuyToCover`, `SellShort`. Stored verbatim on the execution as `original_action` for forensic display.

**Side** — The normalized two-value enum used for quantity-flow math: `Buy` or `Sell`. Computed at parse time from the raw action: `Buy` and `BuyToCover` → `Buy`; `Sell` and `SellShort` → `Sell`. This is the only value the position-builder cares about. **Not** the same as position side.

**Position side** — `Long` or `Short`. **Authoritatively present in the CSV** via the `Position` column, which the exporter writes as `{qty} L`, `{qty} S`, or `-` (flat) after each fill based on its internal running-position tracker. The importer reads position side from this column when assigning it to a new position, and the position-builder independently derives it from quantity flow as a cross-check — if the two disagree, that's an integrity issue.

**Account** — A NinjaTrader account name (e.g., `Sim101`, `APEX-12345`). A single trader has multiple accounts. Positions are always scoped to one account; a trade in account A and a trade in account B cannot belong to the same position even if they're on the same instrument at the same time.

**Instrument** — A futures contract symbol from NinjaTrader (e.g., `MNQ`, `ES`, `MNQ SEP25`). Stored verbatim as it arrives. Mapped to a base symbol and a Yahoo Finance symbol for OHLC fetching (see doc 14).

**Base symbol** — The root contract symbol with any month/year suffix stripped. `MNQ SEP25` → `MNQ`. Used as the canonical identifier for OHLC data and statistics aggregation.

**Multiplier** — The dollar value per point of price movement for a contract. MNQ is $2/point, ES is $50/point, etc. Used to convert points P&L to dollars P&L. Stored in instrument config.

**Tick size** — The minimum price increment for a contract (e.g., 0.25 for ES, 0.01 for CL). Used for chart price formatting and fill validation.

**Points P&L** — `(exit_price - entry_price) × signed_quantity`, where signed_quantity is positive for Long and negative for Short. The price-only profit, ignoring contract value.

**Dollars P&L** — `points_pnl × multiplier - commission`. The trader's actual realized P&L for the position.

**Commission** — Broker fees attached to executions. Summed across all executions in a position to get position commission. Always subtracted from gross P&L.

**Position quantity** — The total contracts traded on the open side. A position that bought 3, then bought 2, then sold 5 has quantity = 5 (not 10). The quantity is the maximum signed deviation from zero, not the sum of all fills.

**Quantity flow** — The running signed-quantity sequence as you walk executions in chronological order. `Buy 3` → +3, then `Sell 2` → +1, then `Sell 1` → 0. A complete quantity flow is one that starts at 0 and returns to 0; that defines a position.

**Direction reversal** — A single execution that takes the running quantity across zero in one step (e.g., long 3, sell 5 → new running qty -2). This is a **legitimate NinjaTrader scenario** produced by reversing orders, and the exporter emits a single CSV row for it marked `Exit` with a new position indicator (e.g., `2 S`). The position-builder treats such a fill as **two logical fills** — one that closes the open position (takes running qty to 0), one that opens the new position (takes running qty from 0 to the new value) — referenced to the same source `execution_id` with sub-indices to preserve identity. One reversing raw execution produces two entries in one position and one entry in the next.

**Entry/Exit** — The semantic role of a single execution within its position: `Entry` (opens the position or adds to it) or `Exit` (reduces or closes it). The exporter computes this itself in the CSV's `E/X` column based on its running quantity tracker, and the rules are: previous qty == 0 → `Entry`; new qty == 0 → `Exit`; same-sign grow → `Entry`; same-sign shrink → `Exit`; zero-cross → `Exit`. The importer preserves this value on each execution and the position-builder uses it for sanity-checking against its own derivation.

## Time concepts

**Trading session** — A 23-hour futures market window. The CME daily session ends and the next day's session begins at the daily settlement/close. The rollover instant is the same moment expressed in three timezones:

- **14:00 America/Los_Angeles** (2:00pm Pacific)
- **16:00 America/Chicago** (4:00pm Central — the CME exchange timezone)
- **17:00 America/New_York** (5:00pm Eastern)

Any execution whose timestamp is at or after the rollover is tagged with the **next** calendar day's session date. Daily P&L groups by session, not calendar day, so a trade placed at 4:30pm Central on Monday belongs to Tuesday's session.

**Session date** — The calendar date assigned to a session for grouping purposes. Computed from a UTC execution timestamp by converting to the exchange timezone (America/Chicago), applying the 16:00 rollover, and taking the resulting calendar date. The canonical implementation lives in `services/time_utils.py::compute_session_date(ts_utc) -> date` and is called everywhere session-date bucketing is needed (feature 15 statistics, feature 10 inbox rollover, feature 17 monitoring). The exporter (doc 90) uses Pacific-time equivalents of the same rollover.

**Entry time** — The timestamp of the first execution in a position.

**Exit time** — The timestamp of the last execution that brought the position back to zero quantity. Null for open positions.

**Duration** — `exit_time - entry_time`, in minutes. Null for open positions.

## Data concepts

**OHLC** — Open / High / Low / Close — the four prices of a single candlestick bar. Stored together with volume and a timestamp.

**Timeframe** — The bar interval: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`. Each instrument has OHLC data fetched at multiple timeframes.

**Bar** — One row of OHLC data: one timeframe interval at one timestamp for one instrument.

**Missing candles** — A range of bars that the OHLC store does not have for an instrument+timeframe but ought to. The word "gap" is deliberately avoided here because in technical analysis a gap means a specific price-pattern phenomenon (a price discontinuity between adjacent bars), which is unrelated to whether data is present in our store.

**Coverage** — The percentage of expected bars actually present in the OHLC store for a given instrument+timeframe over a given range. <100% means there is at least one range of missing candles.

## Pipeline concepts

**Import** — The act of consuming a NinjaTrader CSV and turning its rows into stored executions. Followed by position building.

**Position building** — Computing positions from stored executions on demand by running the `build_positions` function (doc 11) over a sorted list of executions for one `(account, instrument)` pair. Positions are never stored; every query that needs them recomputes them from the current execution set. There is no "rebuild" lifecycle because nothing is materialized to rebuild.

**Missing Candle Retrieval** — The named action of fetching missing OHLC bars from a data source (doc 14) and storing them. Triggered automatically after an import (for the time range of the new executions) and on a schedule; can also be triggered manually. **Avoid "gap fill"** — that phrase is a reserved technical-analysis term referring to price action that closes a chart-pattern gap, and using it here would conflate two unrelated concepts.

**Integrity diff** — The post-import step that runs `build_positions` for each affected `(account, instrument)`, compares the returned `IntegrityIssue` list against the persisted `integrity_issues` table, inserts new issues, and auto-resolves issues that no longer hold. Replaces the old "nightly validation" job — integrity is re-evaluated every import, not on a schedule.

## Identity concepts

**NT ExecutionId** — The NinjaTrader-assigned identifier for a single fill (`Execution.ExecutionId`). Stable across NT restarts, globally unique per NT installation. The natural primary key for the `executions` table, used with `UNIQUE(nt_execution_id, account)` to make imports idempotent. Synthetic sub-fills produced by the position-builder's reversal splitter use the suffixes `#close` and `#open` appended to the parent ExecutionId.

**Position natural key** — The three-tuple `(account, instrument, entry_execution_id)` that identifies a position. Used in URLs, API paths, link group member rows, and anywhere else a "which position are we talking about" reference is needed. There is no numeric position ID in the database or the API — positions are derived on demand and do not have surrogate keys.

**Source file** — The CSV filename an execution was originally read from. Not stored on the execution row; instead, `import_runs` records which tick inserted which rows and which file that tick was reading. Reconciliation goes through `import_runs`, not through a column on `executions`.

## What this glossary deliberately omits

- "Trade" as a noun. The previous codebase used "trade" to mean both individual execution and full position, depending on context. This caused the worst fragmentation. **The new spec does not use "trade" as a domain term.** When a UI label needs a friendly word, prefer "execution" or "position." When code needs a name, prefer those too.
- "Position ID" as a number. The old codebase had a database-generated integer `position_id` that changed every time positions were rebuilt. It's gone — positions are derived, and their identity is the natural key defined above. If you find yourself wanting a `position_id: int`, you're recreating the problem this rebuild exists to fix.
- "Import batch." The old import pipeline had a batch concept with its own lifecycle. The new pipeline (doc 10) has ticks (per-watchdog-event reads) recorded in `import_runs`, and rollback operates on execution IDs directly. There is no batch entity.
- "Position rebuild" as a triggered operation. Positions are pure functions of executions; "rebuilding" them is the same operation as "looking at them," which happens transparently on every read.
