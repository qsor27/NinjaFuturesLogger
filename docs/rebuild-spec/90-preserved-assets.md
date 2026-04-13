# Feature 90 — Preserved Assets

## Purpose

Document the code that is kept verbatim from the previous implementation and the contracts it imposes on the rebuilt application. **Nothing in this document is up for negotiation by the implementer** — these are external constraints.

## What is preserved

### `ninjascript/ExecutionExporter.cs` (1876 lines, C#)

The NinjaScript add-on that runs inside NinjaTrader 8 and writes execution CSVs to disk. This file is copied to the new repository unchanged. It has its own deployment lifecycle (compiled by NinjaTrader's editor, loaded into NT8) and is not built by the Python app's tooling.

**Why preserved:** It contains tested integration with NinjaTrader's event model, futures session date logic in Pacific time, position-state tracking that mirrors the trader's account, and a trade-validation panel that interacts with NinjaTrader's order-blocking machinery. Reimplementing this in another language would re-introduce risk for no benefit.

**The new application's only responsibility regarding this file:**

1. Provide a watched directory for the CSVs it writes (default: `data/inbox/`).
2. Consume its CSV format unchanged (specified below).
3. Not modify the file except for the narrow write-path exception below.

### Write-path exception

The **CSV column contract below is immutable** — the importer (feature 10) depends on exactly these columns in exactly this order with exactly these types. Changing any column, reordering, or adding/removing fields breaks the importer and is forbidden without a coordinated update to doc 90 and feature 10.

The **write-path behavior** of the exporter — how the file is opened, how often it flushes, which sharing mode it uses, which line endings it writes — is **allowed to change** in support of the new importer's tailing read model (doc 10). The following changes are pre-authorized:

- Opening the daily file with `FileShare.Read | FileShare.Delete` so the importer can read while NT holds the handle, and so the archiver can rename the file even if NT still has it open.
- Setting `StreamWriter.AutoFlush = false` and calling `streamWriter.Flush()` + `fileStream.Flush(flushToDisk: true)` explicitly after every execution row so the tailing importer sees rows within milliseconds and a process crash never loses an already-written row.
- Setting `streamWriter.NewLine = "\n"` so every row is terminated with a single LF regardless of host OS, giving the tailing importer an unambiguous "last complete line" marker.
- Removing the "move existing daily file to `exported/` on open" logic (lines ~574–578 of the current file). The new model leaves the file in place across NT restarts; the importer's cursor handles partial reads correctly and `UNIQUE(nt_execution_id, account)` absorbs any duplicated rows if NT re-emits after a crash.

These changes affect **how** the CSV is written, not **what** is written. A row produced by the modified exporter is byte-equivalent (modulo line ending) to a row produced by the current exporter. Doc 10's tailing importer is the consumer that makes these changes necessary; making them is a prerequisite for doc 10 working reliably on Windows.

Any write-path change beyond this list — especially any change that alters the CSV content itself — is **not** pre-authorized and requires a doc 90 revision.

Bug fixes to NinjaScript (logic bugs in the exporter's session-date math, validation panel, order-blocking machinery, etc.) remain outside this exception and happen separately, by the project owner.

## CSV Format Contract

This is the specification of the file ExecutionExporter.cs writes. The new importer (feature 10) must consume this format exactly. **No format auto-detection. No backward-compatibility shims for other formats. This is the only format.**

### Filename pattern

```
NinjaTrader_Executions_YYYYMMDD.csv
```

- One file per session date.
- `YYYYMMDD` is the **session date** computed in Pacific time, rolling over at 3pm PT (= 5pm CT, futures market open). Executions after market open are tagged with the next calendar day.
- File rotation also occurs if the file exceeds `MaxFileSizeMB` (default 10 MB).

### Header line

```
Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,Commission,Rate,Account,Connection,TradeValidation
```

Exactly 15 columns. The header is always present as the first line of every file.

### Column specification

| # | Name | Type | Format | Example | Notes |
|---|---|---|---|---|---|
| 1 | Instrument | string | NinjaTrader full name | `MNQ` | From `execution.Instrument.FullName` |
| 2 | Action | string | enum | `Buy` | One of: `Buy`, `Sell`, `BuyToCover`, `SellShort` |
| 3 | Quantity | int | unsigned, no decimals | `3` | `Math.Abs(execution.Quantity)` |
| 4 | Price | decimal | `F2` (2 decimals always) | `4237.75` | |
| 5 | Time | datetime | `M/d/yyyy h:mm:ss tt` (US format, 12-hour with AM/PM) | `1/15/2025 2:45:30 PM` | NinjaTrader local time (typically the trader's machine timezone) |
| 6 | ID | string | execution UUID, or fallback `{Instrument}_{ticks}_{OrderId}` | `abc123def456` | Used for deduplication |
| 7 | E/X | string | enum | `Entry` | One of: `Entry`, `Exit`. Computed by the exporter from quantity flow (see below). |
| 8 | Position | string | `{qty} L`, `{qty} S`, or `-` | `5 L` | Post-execution running position for that account+instrument |
| 9 | Order ID | string | NinjaTrader order ID | `12345` | |
| 10 | Name | string | order name or fallback to E/X | `Manual Entry` | |
| 11 | Commission | string | `$`-prefixed, F2 format | `$5.00` | Always includes the dollar sign |
| 12 | Rate | string | always `1` | `1` | Hardcoded constant. Future use. |
| 13 | Account | string | NinjaTrader account name | `Sim101` | |
| 14 | Connection | string | always `Apex Trader Funding ` (with trailing space) | `Apex Trader Funding ` | Hardcoded. Importer should not parse this. |
| 15 | TradeValidation | string | empty, `Valid`, or `Invalid` | `Valid` | Optional validation marker; may be empty if the position has not yet been validated |

### Quoting rules

- Fields containing `,`, `"`, or newline are wrapped in double quotes.
- Inner quotes are escaped by doubling: `He said "hi"` → `"He said ""hi"""`.
- Fields without special characters are written bare (no quotes).
- The importer must use a CSV parser that handles RFC 4180-style quoting; do not split on commas.

### Action → Side normalization (importer's responsibility)

| Action | Normalized Side | Position semantic |
|---|---|---|
| `Buy` | `Buy` | Long entry or short cover |
| `Sell` | `Sell` | Long exit or short entry |
| `BuyToCover` | `Buy` | Closing a short — quantity is positive in flow |
| `SellShort` | `Sell` | Opening a short — quantity is negative in flow |

For position-flow purposes only `Buy`/`Sell` matter. The original action string is preserved on the execution record as `original_action` for forensic display.

### Time parsing

- Format: `M/d/yyyy h:mm:ss tt` (US locale, 12-hour, with `AM`/`PM`).
- The importer must parse this with an explicit format string and `en-US` culture; do not rely on auto-detection.
- The timestamp is in the trader's machine local time. There is no timezone marker. The application stores all timestamps as Unix seconds; for storage, treat the parsed time as the configured "trader timezone" (default America/Chicago) and convert to UTC.

### Position field interpretation

The `Position` column shows the running position **after** the execution is applied:

- `5 L` → 5 contracts long
- `3 S` → 3 contracts short
- `-` → flat

The importer can use this for sanity checking (does the running quantity match what the exporter computed?) but it is not the source of truth — the new position-builder (feature 11) computes positions from scratch from the execution sequence.

### TradeValidation field

This field is set by the exporter's internal validation panel (a separate user workflow inside NinjaScript). Possible values:

- empty string → not validated yet (most common at the time of export)
- `Valid` → user marked the closed position as valid in the NinjaScript validation panel
- `Invalid` → user marked it invalid

The importer stores this value on the corresponding executions and exposes it as a derived position attribute. The new application **does not modify this field** — it is owned by the NinjaScript side.

## ExecutionExporter.cs configuration knobs

These properties are exposed in the NinjaScript editor when the user adds the exporter to NinjaTrader. The Python application has no control over them.

| Property | Type | Default | Notes |
|---|---|---|---|
| ExportPath | string | `My Documents/FuturesTradingLog/data` | Where CSVs are written. The Python app's watched directory must match. |
| CreateDailyFiles | bool | true | True: one file per session date. False: timestamped rotation when size exceeded. |
| MaxFileSizeMB | int | 10 | Rotation threshold when CreateDailyFiles=false |
| EnableLogging | bool | true | Writes `execution_export.log` |
| UseSessionCloseDate | bool | true | True: PT session-aware date. False: server local calendar date. **Recommended: true.** |
| SessionStartHourPT | int | 15 | Session boundary in 24-hour Pacific time |
| EnableValidationTracking | bool | true | Tracks closed positions for validation panel |
| EnableOrderBlocking | bool | true | If unvalidated positions exist, NinjaScript cancels new orders |
| GracePeriodSeconds | int | 0 | Delay before order blocking enforces |
| BypassAutomatedStrategies | bool | true | Skip validation for strategy orders |
| EnableEmergencyOverride | bool | true | Ctrl+Shift bypass |

The Python app does not need to know about these except `ExportPath`, which determines where the watched directory is.

## Other preserved bits

After reviewing the old codebase, no other files are preserved. Specifically:

- **No Python services preserved.** Every service is reimplemented under the new architecture. This is the point of the rebuild.
- **No JavaScript files preserved.** The new chart wrapper is rewritten to be a single class with the public API documented in feature 13.
- **No HTML templates preserved.** Templates are rewritten to be shells only (Rule 5).
- **No SQL migrations preserved.** The new schema is fresh.
- **No CSS preserved.** The new app uses Bootstrap 5 with minimal custom CSS.

The project owner may flag specific small assets for preservation as they review this spec — for example, a tricky regex, a symbol-mapping table, a hand-tuned SQL query. Any such items should be added below this line in this document before implementation begins.

## Owner-flagged preservation items

*(empty — to be filled by the project owner during spec review)*
