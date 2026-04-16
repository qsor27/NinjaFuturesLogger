# Position Detail — Per-Exit P&L, Commission Fallback, Color-Coded Header

**Date:** 2026-04-15  
**Status:** Approved

## Overview

Three related improvements to the position detail page and instrument settings:

1. **Per-exit P&L in executions table** — each exit row shows points P&L and net-dollar P&L against the position's weighted average entry price.
2. **Commission fallback in instrument registry** — a new `commission_per_contract` field lets users configure a per-contract rate used when NinjaTrader reports $0 commission.
3. **Color-coded P&L in position header** — Points P&L and $ P&L rows turn green (positive) or red (negative).

---

## 1. Commission fallback — `commission_per_contract`

### Data model

Add `commission_per_contract: float` (default `0.0`) to `InstrumentConfig` in `models/settings.py`. A value of `0.0` means "not configured / use NT as-is."

### Effective commission rule

For any execution:

```
effective_commission = execution.commission  (if > 0)
                     = commission_per_contract * execution.quantity  (if execution.commission == 0 and rate > 0)
                     = 0.0  (otherwise — sim accounts, unset instruments)
```

This logic lives in a small pure helper `services/instruments.py::effective_commission(instrument, execution_commission, quantity) -> float`.

### Registry changes

- `InstrumentRegistry` reads and writes the new field (defaults to `0.0` for existing entries on first load).
- The instruments settings API (`routes/settings.py`) accepts and returns `commission_per_contract`.

### UI changes

- `settings_instruments.html` — new "Commission per contract ($)" column in the table (shows "—" when 0).
- Instrument edit dialog — new numeric input field below tick size. Must use same readable text styling as existing fields (white text on dark background).

---

## 2. Per-exit P&L in executions table

### API change — `/api/positions/<account>/<instrument>/<entry_execution_id>/executions`

Enrich each execution row with three new fields computed server-side:

| Field | Type | Description |
|---|---|---|
| `avg_entry_price` | `float \| null` | Position's weighted average entry price (exit rows only; `null` for entry rows) |
| `pnl_points` | `float \| null` | `(exit_price − avg_entry_price) × qty × sign`; `null` for entry rows |
| `pnl_dollars_net` | `float \| null` | `pnl_points × multiplier − effective_commission`; `null` for entry rows |

`sign` is `+1` for Long positions, `−1` for Short.

The endpoint already loads the parent position (to filter to the correct execution IDs); `entry_price` and `side` are read from that position object. `effective_commission` uses the helper from §1.

### Table columns

Replace current columns `ID / Time / Side / Qty / Price / Commission / Action / Reviewed` with:

`ID / Time / Side / Qty / Price / Avg Entry / Pts P&L / $ P&L (net) / Commission / Action`

- Reviewed column is removed from the table (it's already on the toggle above the table, so this is not a loss).
- Entry rows: Avg Entry, Pts P&L, $ P&L (net) show `—`.
- Exit rows: all three columns populated, Pts P&L and $ P&L (net) colored green/red.

---

## 3. Color-coded P&L in position header

In `renderHeader()` (`static/js/position_detail.js`), the "Points P&L" and "$ P&L" `<dd>` elements get a CSS class:

- `pnl-positive` (green) when value > 0
- `pnl-negative` (red) when value < 0
- no class when value == 0 or null

Add `.pnl-positive { color: #4caf50; font-weight: 600; }` and `.pnl-negative { color: #f44336; font-weight: 600; }` to the global stylesheet (or a `<style>` block in `base.html`).

---

## Affected files

| File | Change |
|---|---|
| `models/settings.py` | Add `commission_per_contract: float = 0.0` to `InstrumentConfig` |
| `services/instruments.py` | Add `effective_commission()` helper |
| `routes/settings.py` | Pass `commission_per_contract` through instruments CRUD |
| `routes/positions.py` | Enrich executions endpoint with `avg_entry_price`, `pnl_points`, `pnl_dollars_net` |
| `static/js/position_detail.js` | Render new columns; color-code header P&L |
| `templates/settings_instruments.html` | Add commission column + dialog field |
| `static/css/` or `base.html` | Add `.pnl-positive` / `.pnl-negative` styles |

---

## Out of scope

- Changing the position list page P&L display.
- Changing how `dollars_pnl` is computed in `build_positions` — the commission fallback affects only display/reporting, not the stored position model (positions are derived from raw executions which don't change).
- Per-exit commission in the position-level `commission` total — the position header still shows the sum of NT-reported commissions (unchanged).

---

## Acceptance criteria

1. Exit rows in the executions table show Avg Entry, Pts P&L, and $ P&L (net) with green/red color.
2. Entry rows show `—` in those three columns.
3. The instruments settings dialog has a "Commission per contract" field that saves and reloads correctly.
4. When an instrument has `commission_per_contract > 0` and NT reports $0, `effective_commission` is used in `pnl_dollars_net`.
5. Sim accounts (NT reports $0, no commission_per_contract configured) show $0 commission and P&L correctly.
6. Points P&L and $ P&L in the position header are green when positive, red when negative.
7. Input fields in the instrument settings dialog remain readable (white text on dark background).
