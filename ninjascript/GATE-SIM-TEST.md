# Setup Gate — Sim test script

Run every step on **Sim101** before gating a live or funded account. Tick each box; note anything
that differs. Times are your chart times.

## 0. Install and compile
- [ ] Close NinjaTrader's NinjaScript Editor if open. From `ninjascript\` run `.\install-gate.ps1 -WhatIf`,
      read the list, then run `.\install-gate.ps1`.
- [ ] NinjaTrader → New → NinjaScript Editor → **F5**. Expect "compiled successfully" (no errors).
- [ ] **Fully close and reopen NinjaTrader.**
- [ ] New → NinjaScript Output shows `Setup Gate started. Settings: …\setup_gate_settings.txt`.

## 1. Settings and accounts
- [ ] `Documents\NinjaFuturesLogger\setup_gate_settings.txt` has `GatedAccounts=Sim101` (the AddOn writes a
      template on first start if the file is missing, and the red alert window says so).
- [ ] Put a deliberate typo in the account (e.g. `sim101`) and restart: the red alert says "Gated account
      sim101 was not found … did you mean Sim101?". Fix it and restart.

## 2. Chart, tracking and the strip
- [ ] Open a 1-minute chart of the front month (e.g. `MNQ 12-26`) with Chart Trader shown. Add the
      **SetupGate** indicator (Indicators → SetupGate).
- [ ] Top-left of the chart shows the status strip: the TREND line, the **Lines** checkbox, and LONG and
      SHORT rows of 1m/3m/1h/4h icons. Chart Trader shows a **SETUP GATE · <instrument>** panel under
      its normal controls (if it isn't there it appears bottom-right on the chart instead — note which).
      If the strip itself is missing, tell me — the GATE OFFLINE banner lives in the same place.
- [ ] With two tabs in one chart window (e.g. MNQ and ES, SetupGate on both), switching tabs swaps
      Chart Trader's SETUP GATE panel to the selected tab's instrument.
- [ ] The hourly trend window opens for this instrument with ~24 hourly candles.
- [ ] After any F5 recompile, the strip shows "offline" and the red **GATE OFFLINE** banner for at most a
      second or two, then recovers by itself.

## 3. Hourly trend
- [ ] Nothing is pre-selected. Click **Up**. The row disappears; the strip shows `TREND ▲ UP`.
- [ ] Wait for the next hourly close: the trend window reappears **once** for the new hour; the strip
      shows "(answer needed)" until you answer.

## 4. Manual entries are blocked
- [ ] With Sim101 flat, click **Buy Mkt** in Chart Trader. The order is cancelled; the panel's status
      shows "Last cancel: … Entries are only allowed through an armed setup."
- [ ] `Documents\NinjaFuturesLogger\gate_log.csv` has a `Cancel` row. If the market order filled anyway,
      the alert window shows **SLIP-THROUGH** — note it; the gate does not flatten.

## 5. Levels on the chart
- [ ] In the panel choose **Long**, press **Set** on the **Low** row (it changes to "Click chart"),
      click the chart at the swing low: a grey `▲ LOW … pinned` line appears where you clicked.
- [ ] Press **Set** on the **1m** row and click above the low: a blue `▲ 1m LVL …` line appears. Do the
      same on the **3m**, **1h** and **4h** rows: purple, gold and orange lines appear, each labelled
      with its own timeframe. A level clicked below the low is refused with the reason in the panel.
- [ ] Press **Set** on the 1h row, then **Set** on the 4h row: the 4h row is now the one waiting
      ("Click chart"); your click places the 4h line.
- [ ] Drag the 1m line **by its label** (right side) up a few ticks: it follows the mouse and stays at
      the new price; the panel's 1m box shows it. Clicking the line away from its label does nothing
      (NinjaTrader handles that click as usual).
- [ ] With an ATM stop sitting just under the LOW line, drag the stop: the stop moves, the LOW line
      does not.
- [ ] Click into the Low box, wait for a new low to move the auto low, then click into the 1m box
      without typing: the low stays **auto** (nothing is saved unless you typed).
- [ ] Type a price into the 3m box and press Enter: a purple `▲ 3m LVL` line appears. Put a 1h level at
      the same price as the 1m level: both labels show, stacked.
- [ ] Press **✕** on the 1h row: the 1h line disappears and `gate_log.csv` has a LevelRemoved row. Clear
      the 3m box and press **Enter**: the 3m line is removed (clearing a box and just clicking away
      restores it instead).
- [ ] Let the 1m setup die (two closes below in a row), press **✕** on the 1m row, then **Set** a new 1m
      level: its icon waits for a **new low** (removing a dead level doesn't skip that rule).
- [ ] Press **✕** on the Low row: a Yes/No box asks to remove the low and every long level; **Yes**
      clears the long side.
- [ ] Untick **Lines**: lines disappear; tick it: they return. Press a row's **Set** then **Esc** (or
      press the same **Set** again, or switch Long/Short): the prompt says "Placement cancelled." and the
      next click is an ordinary chart click.
- [ ] In click mode, clicking a lower panel (e.g. Volume) or the price axis does nothing.
- [ ] Watch the 1m icon as candles close: red → green outline after one close above → solid green after
      two; the panel status line explains each step ("Waiting for a new low." → "Waiting for a 1m close
      back above the level." → "Ready to arm long.").

## 6. Arm and fire (market)
- [ ] With **no ATM strategy** selected in Chart Trader, press **ARM MARKET**: refused ("Choose an ATM
      strategy in Chart Trader…").
- [ ] Counter-trend: with the trend DOWN and the panel on Long, the status says "Trend is DOWN: arming
      LONG is counter-trend and asks for confirmation". Press ARM: a Yes/No box asks to arm against
      the hourly trend. **No** → "Not armed". **Yes** → armed, description ends "· counter-trend", and
      `gate_log.csv` has an Arm row saying counter-trend. Answering the next hour's trend doesn't cancel it.
- [ ] Select account Sim101, your ATM template and quantity 1 in Chart Trader. Press **ARM MARKET** any
      time after setting the 1m level (even before the new low — status says "You can arm now"): the message says "Armed LONG on Sim101." and the strip's LONG row and the
      panel show "ARMED MKT · <template> · 1 ct".
- [ ] On the second consecutive 1m close above the level, a market buy fills at the next candle's first
      tick with the ATM's stop and target attached (Stop1/Target1 are **not** cancelled).
- [ ] The gate's own entry is **not** cancelled: `gate_log.csv` has a `Fire` row and no `Cancel` row for
      it. (This proves NinjaTrader keeps the order's Id from creation to submission.)
- [ ] Repeat with quantity 2 and an ATM with two targets: both stops/targets survive while fills arrive.
- [ ] While long: Chart Trader **Buy Mkt** is cancelled ("Adding to a position isn't allowed."); a
      **Sell** larger than the position is cancelled; dragging the stop either way is allowed; closing
      the position is allowed.
- [ ] Exit the position outside the ATM (DOM **Close** / Sell Mkt): any ATM bracket still working is
      cancelled with "Leftover … cancelled when the position went flat".

## 7. Strike, re-arm, death
- [ ] Armed after one close above, let one 1m candle close back below: the arm stays (still ARMED).
      A second close below in a row → the arm is cancelled ("1m setup moved to Dead").
- [ ] Two consecutive closes below after a close above → the 1m icon shows a red ✕ and the status says
      "1m setup is dead — needs a new low and a new level."; arming is refused.

## 8. Limit entry and the logger tag
- [ ] Type your price next to **ARM LIMIT @** in the panel and press it; on confirmation a Gtc limit
      order is placed and stays working until you cancel it.
- [ ] Drag the working gate limit's price: allowed. Restart NinjaTrader while it is still working: it is
      recognised again (status "Gate entry working"), dragging it is still allowed, and arming a second
      entry is refused.
- [ ] After a gate entry fills, the exporter CSV row for the entry has `GateMktNextOpen` or
      `GateLmtNextOpen` in the Name column, and after import NinjaFuturesLogger's Statistics → By Entry
      Method shows it.

## 8b. Auto break-even
- [ ] With `BreakEvenTicks=1` and an ATM with two targets, take a 2-contract gate entry. When Target1
      fills, the remaining stop jumps to entry + 1 tick (`gate_log.csv` has a `BreakEven` row). A stop
      already beyond that is left alone.
- [ ] With a one-target ATM, Target1 closing the whole position produces no BreakEven row and no alert.

## 9. Copier (only if you use one)
- [ ] Add the follower to `FollowerAccounts=` and restart. A gate entry is copied; a manual entry on the
      follower alone is cancelled; dragging the follower's copied stop is allowed.
- [ ] Fire a gate **limit** entry and drag its price after 30 s: the copier's follower order follows and
      is not cancelled. Note whether your copier copies limit entries on submission or on fill.
- [ ] With several connections up, disconnect one that does not provide your chart data: entries are
      **not** blocked.

## 10. Restart and reconnect
- [ ] With levels set, restart NinjaTrader: the lines come back, the setup state is replayed, the trend
      is asked again, and any arm is gone.
- [ ] Disconnect the data connection: the alert says entries are blocked and the status reads "1m data
      is down"; reconnect: bars reload and the status recovers.
