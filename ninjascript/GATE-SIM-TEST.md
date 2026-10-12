# Setup Gate — Sim test script (Plan B2)

Run every step on **Sim101** before gating a live or funded account. Tick each box; note anything
that differs. NinjaTrader times below are your chart times.

## 0. Install and compile
- [ ] Close NinjaTrader's NinjaScript Editor if open. From the repo root run
      `powershell -ExecutionPolicy Bypass -File ninjascript\install-gate.ps1 -WhatIf`, read the list, then run it without `-WhatIf`.
- [ ] NinjaTrader → New → NinjaScript Editor → **F5**. Expect "compiled successfully" (no errors).
- [ ] Restart NinjaTrader.

## 1. First start
- [ ] A red **Setup Gate — alerts** window says it created `setup_gate_settings.txt` and that no gated accounts are set.
- [ ] Edit `Documents\NinjaFuturesLogger\setup_gate_settings.txt`: `GatedAccounts=Sim101`. Restart NinjaTrader. No "no gated accounts" alert.

- [ ] Put a deliberate typo in the case of the account name (e.g. `sim101`) and restart: the alert says "Gated account sim101 was not found … did you mean Sim101?". Fix it and restart.

## 2. Control window and tracking
- [ ] Control Center → **New → Setup Gate** opens the control window.
- [ ] Type the front-month contract (e.g. `MNQ 12-26`) → **Track**. Status reads "Confirm the hourly trend first." and the **hourly trend** window opens with ~24 hourly candles.

## 3. Hourly trend
- [ ] Nothing is pre-selected. Click **Up**. The row disappears; status changes.
- [ ] Wait for the next hourly close: the trend window reappears **once** for the new hour.
- [ ] With the hour already answered Up, open "Hourly trend…" and click **Down** → the row shows "This hour is already Up…".

## 4. Manual entries are blocked
- [ ] With Sim101 flat, click **Buy Mkt** in Chart Trader. The order is cancelled; the control window shows "Last cancel: … Entries are only allowed through an armed setup."
- [ ] `Documents\NinjaFuturesLogger\gate_log.csv` has a `Cancel` row. If the market order filled anyway, the alert window shows **SLIP-THROUGH** — note it; the gate does not flatten.

## 5. Levels and the 1m setup
- [ ] Side Long, type the current swing low → **Set Low / High**. Timeframe 1m, type the level above it → **Set Level**. A level below the low is refused with a reason.
- [ ] Watch the status line as 1m candles close: "Waiting for a new low." → after a new low "Waiting for a 1m close back above the level." → after one close above "Ready to arm long."

## 6. Arm and fire (market)
- [ ] At "Ready to arm long.": choose Sim101, type your ATM template name exactly (e.g. `4ptSL-20ptTP`), Qty 1 → **ARM MARKET**. Status shows "ARMED MKT · … — fires at the open after the second close."
- [ ] Arming with a misspelt ATM template name is refused ("ATM template … was not found").
- [ ] On the second consecutive 1m close above the level, a market buy fills at the next candle's first tick with the ATM's stop and target attached (Stop1/Target1 are **not** cancelled).
- [ ] The gate's own entry is **not** cancelled: `gate_log.csv` has a `Fire` row and no `Cancel` row for it. (This proves NinjaTrader keeps the order's Id from creation to submission.)
- [ ] Repeat with Qty 2 using an ATM that has two targets: both stops/targets survive while the fills arrive.
- [ ] Exit the position outside the ATM (DOM **Close**/Sell Mkt): any ATM bracket still working is cancelled with "Leftover … cancelled when the position went flat".
- [ ] While long: Chart Trader **Buy Mkt** is cancelled ("Adding to a position isn't allowed."); a **Sell** larger than the position is cancelled; dragging the stop either way is allowed; closing the position is allowed.

## 7. Strike, re-arm, death
- [ ] Arm, then let a 1m candle close back below the level → the arm is cancelled ("1m setup moved to …").
- [ ] Two consecutive closes below after a close above → status "1m setup is dead — needs a new low and a new level."; arming is refused.

## 8. Limit entry and the logger tag
- [ ] Arm a **LIMIT** at your price; on confirmation a Gtc limit order is placed and stays working until you cancel it.
- [ ] Drag the working gate limit's price: allowed. Restart NinjaTrader while it is still working: it is recognised again (status "Gate entry working"), dragging it is still allowed, and arming a second entry is refused.
- [ ] After a gate entry fills, the exporter CSV row for the entry has `GateMktNextOpen` or `GateLmtNextOpen` in the Name column, and after import NinjaFuturesLogger's Statistics → By Entry Method shows it.

## 9. Copier (only if you use one)
- [ ] Add the follower to `FollowerAccounts=` and restart. A gate entry is copied; a manual entry on the follower alone is cancelled; dragging the follower's copied stop is allowed.
- [ ] Fire a gate **limit** entry and drag its price after 30 s: the copier's follower order follows and is not cancelled. Note whether your copier copies limit entries on submission or on fill.
- [ ] With several connections up, disconnect one that does not provide your chart data: entries are **not** blocked.

## 10. Restart and reconnect
- [ ] With a level set and price beyond it, restart NinjaTrader: levels come back, the setup state is replayed, the trend is asked again, and any arm is gone.
- [ ] Disconnect the data connection: the alert says entries are blocked and status reads "1m data is down"; reconnect: bars reload and status recovers.
