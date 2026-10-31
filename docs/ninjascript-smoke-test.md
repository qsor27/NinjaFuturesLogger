# NinjaScript consolidation — NT8 smoke test (final gate)

Plan executed 2026-08-07/08 (commits 899b848..6b8c98b). Everything below reviewed clean; this
checklist is the last gate. Step 4's expectation is CORRECTED from the original plan (see notes).

1. **Install**: copy `ExecutionExporter.cs` + `TradeFeedbackIndicator.cs` to
   `Documents\NinjaTrader 8\bin\Custom\Indicators\`, and `TradeFeedbackAddOn.cs` +
   `TradeValidationShared.cs` to `bin\Custom\AddOns\`. REMOVE all previously imported copies of
   these files first (stale copies re-create the CS0101 duplicate-class error). Do NOT copy
   `*Tests.cs`.
2. **Compile (F5)**: zero errors, specifically no CS0101.
3. **Expect duplicate panel entries — by design**: with all three components live, each Sim close
   produces 2-3 entries in the exporter's chart panel (one keyed at execution time with PnL $0.00
   from the exporter's always-track path, one or two keyed ~1s later; counts vary because
   same-second IDs merge first-wins). Validate ALL of them. This is the accepted no-dedupe design,
   not a bug.
4. **CSV join check (CORRECTED expectation)**: close a Sim trade, validate all its entries, then
   within 60 seconds place and fill one more small trade. The SECOND trade's CSV rows must show
   the validation value in the TradeValidation column. The first trade's own rows stay empty —
   rows are stamped at write time before you can click (pre-existing design; a follow-up plan
   could add rewrite-on-validate). Also confirm
   `Documents\NinjaFuturesLogger\trade_validation_state.txt` exists with `Valid` entries.
5. **Enforcement round-trip**: with an unvalidated close outstanding, place a manual order → the
   exporter cancels it ("ORDER CANCELLED" in output) AND the AddOn modal appears. Validate every
   entry → place the order again → goes through immediately.
6. **Combined IsAutomatedOrder rule safety**: (a) with an unvalidated close outstanding, an
   ATM-managed order's `Stop1`/`Target1` protective orders must NOT be cancelled (the old rule
   could cancel them — this fix was the rule change's point); (b) Chart Trader's Close button must
   flatten even while unvalidated (order named "Close" bypasses — intended fail-safe).
7. **Emergency override**: hold Ctrl+Shift while placing an order with unvalidated positions →
   passes without cancel or modal.
8. **State migration**: canonical state file exists; if `Documents\FuturesTradingLog\*.txt`
   existed, their entries are merged in and the legacy files are byte-untouched. (Note: exporter
   and indicator could never have compiled together pre-plan, so probably only one legacy file
   exists — whichever component you actually had installed.)
9. **Resubscribe fix**: remove TradeFeedbackIndicator from a chart, re-add it → the
   "Subscribed to events for account:" lines print again (old bug: they never did until NT restart).
10. **Task 7 live behavior (new!)**: close a LOSING Sim trade → the AddOn's tracker entry shows
    the real realized PnL (not $0.00). Winning closes don't trigger the AddOn's own validation
    requirement (the exporter's always-require entry still will).
11. Keep ExecutionExporter on exactly ONE chart (two instances contend for the CSV file —
    pre-existing limitation).

Known accepted quirks (disclosed, not bugs): simultaneous closes on two instruments merge into one
PnL delta (first absorbs both); a broker daily PnL reset can make the first close after
reconnect show a wrong PnL and demand one spurious validation; if the owning indicator instance is
removed while a second exists, indicator tracking naps until any instance is re-added; validation
clicks now persist immediately (crash-safe) — added in the final fix wave.
