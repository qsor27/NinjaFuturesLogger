#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>
    /// Spec §7: judges every order submitted or changed on gated (leader) and copier-follower
    /// accounts and cancels the ones that break the rules. Exits are never blocked; nothing is
    /// ever flattened (Q18-D) — a fill that beats the cancel is reported as a slip-through.
    /// </summary>
    internal sealed class GateOrderEnforcer
    {
        private readonly object sync = new object();
        private readonly GateRuntime runtime;
        private readonly OrderIntentTracker tracker = new OrderIntentTracker();
        private readonly HashSet<long> gateEntryIds = new HashSet<long>();
        private readonly HashSet<long> cancelledIds = new HashSet<long>();
        private readonly LeaderEntryLog leaderEntries = new LeaderEntryLog();
        private readonly List<Account> subscribed = new List<Account>();
        private readonly List<KeyValuePair<Order, string>> gateEntryOrders = new List<KeyValuePair<Order, string>>();
        private readonly Dictionary<long, string> journaledOrderIds = new Dictionary<long, string>();
        private readonly GateEntryJournal journal = GateEntryJournal.Load(GateRuntime.JournalPath);

        public GateOrderEnforcer(GateRuntime runtime)
        {
            this.runtime = runtime;
        }

        /// <summary>Idempotent: call at start and whenever a connection comes up.</summary>
        public void SubscribeAll()
        {
            var fresh = new List<Account>();
            lock (Account.All)
            {
                foreach (Account account in Account.All)
                {
                    lock (sync)
                    {
                        if (account == null || subscribed.Contains(account)) continue;
                        subscribed.Add(account);
                    }
                    account.OrderUpdate += OnOrderUpdate;
                    account.ExecutionUpdate += OnExecutionUpdate;
                    account.PositionUpdate += OnPositionUpdate;
                    fresh.Add(account);
                }
            }
            foreach (var account in fresh)
            {
                foreach (Position position in account.Positions.ToArray())
                {
                    if (position.Instrument != null)
                        runtime.UpdatePosition(account.Name, position.Instrument.FullName, Signed(position.MarketPosition, position.Quantity));
                }
                // Orders that were already working before the gate subscribed: recognise journaled
                // gate entries; judge everything else as if it had just been submitted.
                foreach (Order order in account.Orders.ToArray())
                {
                    if (!IsLive(order.OrderState) || order.Instrument == null) continue;
                    string gateName;
                    bool known;
                    lock (sync) known = journal.TryGet(order.OrderId, out gateName);
                    if (known) Recover(order, gateName);
                    Judge(order, order.OrderState, order.Quantity);
                }
            }
        }

        public IReadOnlyList<string> AccountNames()
        {
            lock (sync) return subscribed.Select(a => a.Name).ToList();
        }

        public void Stop()
        {
            List<Account> accounts;
            lock (sync)
            {
                accounts = subscribed.ToList();
                subscribed.Clear();
            }
            foreach (var account in accounts)
            {
                account.OrderUpdate -= OnOrderUpdate;
                account.ExecutionUpdate -= OnExecutionUpdate;
                account.PositionUpdate -= OnPositionUpdate;
            }
        }

        /// <summary>
        /// Called before StartAtmStrategy submits the gate's entry. Remembers the order by id and by
        /// reference (in case NinjaTrader assigns the id later) and records the allowed leader entry
        /// before any copier can react to it.
        /// </summary>
        public void MarkGateEntry(Order order, string gateName, string instrument, bool isBuy)
        {
            lock (sync)
            {
                gateEntryIds.Add(order.Id);
                gateEntryOrders.Add(new KeyValuePair<Order, string>(order, gateName));
                leaderEntries.Add(new LeaderEntry(instrument, isBuy, DateTimeOffset.UtcNow.ToUnixTimeSeconds()));
            }
        }

        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            if (e.Order != null) Judge(e.Order, e.OrderState, e.Quantity);
        }

        private bool IsGateEntry(Order order)
        {
            lock (sync)
            {
                if (gateEntryIds.Contains(order.Id)) return true;
                foreach (var pair in gateEntryOrders)
                {
                    if (!ReferenceEquals(pair.Key, order)) continue;
                    gateEntryIds.Add(order.Id); // the id changed after CreateOrder: re-key the exporter tag too
                    GateEntryNames.RegisterName(order.Id.ToString(CultureInfo.InvariantCulture), pair.Value);
                    return true;
                }
                return false;
            }
        }

        private void Recover(Order order, string gateName)
        {
            lock (sync)
            {
                gateEntryIds.Add(order.Id);
                gateEntryOrders.Add(new KeyValuePair<Order, string>(order, gateName));
                journaledOrderIds[order.Id] = order.OrderId;
            }
            GateEntryNames.RegisterName(order.Id.ToString(CultureInfo.InvariantCulture), gateName);
        }

        /// <summary>Keeps gate_entries.txt in step with working gate entries (by broker order id).</summary>
        private void Journal(Order order, bool working)
        {
            bool changed = false;
            lock (sync)
            {
                string recorded;
                journaledOrderIds.TryGetValue(order.Id, out recorded);
                if (working && !string.IsNullOrEmpty(order.OrderId) && recorded != order.OrderId)
                {
                    string gateName = gateEntryOrders.Where(p => ReferenceEquals(p.Key, order)).Select(p => p.Value).FirstOrDefault();
                    if (recorded != null) journal.Forget(recorded);
                    journal.Record(order.OrderId, gateName);
                    journaledOrderIds[order.Id] = order.OrderId;
                    changed = true;
                }
                else if (!working && recorded != null)
                {
                    journal.Forget(recorded);
                    journaledOrderIds.Remove(order.Id);
                    changed = true;
                }
                if (changed)
                {
                    try
                    {
                        GateEntryJournal.Save(GateRuntime.JournalPath, journal);
                    }
                    catch (Exception ex)
                    {
                        runtime.Log(order.Instrument.FullName, order.Account.Name, GateEvents.Cancel, "gate_entries.txt not saved: " + ex.Message);
                    }
                }
            }
        }

        private void Judge(Order order, OrderState state, int quantity)
        {
            try
            {
                if (order.Account == null || order.Instrument == null) return;
                string account = order.Account.Name;
                string instrument = order.Instrument.FullName;

                bool isGateEntry = IsGateEntry(order);
                if (isGateEntry)
                {
                    bool working = IsWorking(state);
                    runtime.SetGateEntryWorking(instrument, order.Id, working);
                    Journal(order, working);
                }

                var settings = runtime.Settings;
                bool leader = settings.IsGated(account);
                bool follower = settings.IsFollower(account);
                if (!leader && !follower) return;

                bool isBuy = order.OrderAction == OrderAction.Buy || order.OrderAction == OrderAction.BuyToCover;
                OrderIntent intent;
                lock (sync)
                {
                    intent = tracker.Observe(order.Id, PhaseOf(state), isBuy, quantity, isGateEntry,
                        OrderIntentTracker.IsAtmBracket(order.Name));
                }
                if (intent == null) return;

                int position = PositionOf(order.Account, instrument);
                long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                GateDecision decision;
                if (leader)
                {
                    decision = OrderGate.Decide(intent, position);
                }
                else
                {
                    IReadOnlyList<LeaderEntry> recent;
                    lock (sync) recent = leaderEntries.Recent(now, settings.FollowerWindowSeconds);
                    decision = FollowerGate.Decide(intent, instrument, position, recent, now, settings.FollowerWindowSeconds);
                }
                if (decision.Allowed) return;

                lock (sync) cancelledIds.Add(order.Id);
                runtime.Log(instrument, account, GateEvents.Cancel,
                    decision.Reason + " (" + order.OrderAction + " " + intent.Quantity.ToString(CultureInfo.InvariantCulture) + ")");
                runtime.ReportCancel(instrument, decision.Reason);
                try
                {
                    order.Account.Cancel(new[] { order });
                }
                catch (Exception ex)
                {
                    runtime.RaiseAlert("Could not cancel " + order.OrderAction + " " + instrument + " on " + account + ": " + ex.Message);
                }
            }
            catch (Exception ex)
            {
                runtime.RaiseAlert("Setup gate order check failed: " + ex.Message);
            }
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            try
            {
                var order = e.Execution != null ? e.Execution.Order : null;
                if (order == null || order.Instrument == null || order.Account == null) return;
                if (BreakEvenTrigger.IsFirstTarget(order.Name) && runtime.Settings.IsGated(order.Account.Name))
                    MoveStopsToBreakEven(order, e.Price);
                if (IsGateEntry(order))
                {
                    // Copiers may copy on fill (limit entries can fill minutes later): restart the window.
                    bool buy = order.OrderAction == OrderAction.Buy || order.OrderAction == OrderAction.BuyToCover;
                    lock (sync) leaderEntries.Add(new LeaderEntry(order.Instrument.FullName, buy, DateTimeOffset.UtcNow.ToUnixTimeSeconds()));
                    return;
                }
                bool slipped;
                lock (sync) slipped = cancelledIds.Contains(order.Id);
                if (!slipped) return;

                string instrument = order.Instrument.FullName;
                string detail = order.OrderAction + " " + e.Quantity.ToString(CultureInfo.InvariantCulture) + " @ "
                    + e.Price.ToString(CultureInfo.InvariantCulture) + " filled before the gate's cancel landed.";
                runtime.Log(instrument, order.Account.Name, GateEvents.SlipThrough, detail);
                runtime.RaiseAlert("SLIP-THROUGH on " + order.Account.Name + ": " + instrument + " " + detail
                    + " Manage it by hand — the gate never flattens.");
            }
            catch (Exception ex)
            {
                runtime.RaiseAlert("Setup gate execution check failed: " + ex.Message);
            }
        }

        /// <summary>Spec §8: Target1 filled — move the other stops of this position past entry.</summary>
        private void MoveStopsToBreakEven(Order target, double fillPrice)
        {
            var account = target.Account;
            string instrument = target.Instrument.FullName;
            Position position = account.Positions.ToArray()
                .FirstOrDefault(p => p.Instrument != null && p.Instrument.FullName == instrument);
            if (position == null || position.MarketPosition == MarketPosition.Flat) return;

            GateSide side = position.MarketPosition == MarketPosition.Long ? GateSide.Long : GateSide.Short;
            var stopPrice = BreakEven.StopPrice(side, position.AveragePrice, runtime.Settings.BreakEvenTicks,
                target.Instrument.MasterInstrument.TickSize, fillPrice);

            foreach (Order stop in account.Orders.ToArray())
            {
                if (stop.Instrument == null || stop.Instrument.FullName != instrument || !IsLive(stop.OrderState)) continue;
                if (!BreakEvenTrigger.ShouldMoveStop(stop.Name, stop.Oco, target.Oco)) continue;
                bool alreadyBetter = side == GateSide.Long ? stop.StopPrice >= stopPrice.Price : stop.StopPrice <= stopPrice.Price;
                if (alreadyBetter) continue;

                stop.StopPriceChanged = stopPrice.Price;
                try
                {
                    account.Change(new[] { stop });
                    runtime.Log(instrument, account.Name, GateEvents.BreakEven,
                        stop.Name + " moved to " + InstrumentGate.FormatPrice(stopPrice.Price)
                        + (stopPrice.Adjusted ? " (one tick from price — break-even was already through)" : ""));
                    if (stopPrice.Adjusted)
                        runtime.RaiseAlert(instrument + ": price was already through break-even; " + stop.Name
                            + " placed one tick from price at " + InstrumentGate.FormatPrice(stopPrice.Price) + ".");
                }
                catch (Exception ex)
                {
                    runtime.RaiseAlert("Could not move " + stop.Name + " to break-even on " + instrument + ": " + ex.Message);
                }
            }
        }

        private void OnPositionUpdate(object sender, PositionEventArgs e)
        {
            var position = e.Position;
            if (position == null || position.Account == null || position.Instrument == null) return;
            int signed = Signed(e.MarketPosition, e.Quantity);
            runtime.UpdatePosition(position.Account.Name, position.Instrument.FullName, signed);
            if (signed == 0 && runtime.Settings.IsGated(position.Account.Name))
                CancelLeftovers(position.Account, position.Instrument.FullName);
        }

        /// <summary>
        /// The gated position went flat: any order still working on it (an ATM bracket orphaned by
        /// an exit outside the ATM, a leftover exit) would now open an unarmed position. Gate
        /// entries are kept.
        /// </summary>
        private void CancelLeftovers(Account account, string instrument)
        {
            foreach (Order order in account.Orders.ToArray())
            {
                if (order.Instrument == null || order.Instrument.FullName != instrument) continue;
                if (!IsLive(order.OrderState) || IsGateEntry(order)) continue;
                lock (sync) cancelledIds.Add(order.Id);
                string reason = "Leftover " + order.Name + " " + order.OrderAction
                    + " cancelled when the position went flat — it would open an unarmed position.";
                runtime.Log(instrument, account.Name, GateEvents.Cancel, reason);
                runtime.ReportCancel(instrument, reason);
                try
                {
                    account.Cancel(new[] { order });
                }
                catch (Exception ex)
                {
                    runtime.RaiseAlert("Could not cancel leftover " + order.Name + " on " + account.Name + ": " + ex.Message);
                }
            }
        }

        private static bool IsLive(OrderState state) =>
            state == OrderState.Submitted || state == OrderState.Accepted || state == OrderState.Working
            || state == OrderState.TriggerPending || state == OrderState.AcceptedByRisk
            || state == OrderState.ChangePending || state == OrderState.ChangeSubmitted || state == OrderState.PartFilled;

        private static int PositionOf(Account account, string instrument)
        {
            foreach (Position position in account.Positions.ToArray())
            {
                if (position.Instrument != null && position.Instrument.FullName == instrument)
                    return Signed(position.MarketPosition, position.Quantity);
            }
            return 0;
        }

        private static int Signed(MarketPosition marketPosition, int quantity)
        {
            if (marketPosition == MarketPosition.Long) return quantity;
            if (marketPosition == MarketPosition.Short) return -quantity;
            return 0;
        }

        private static OrderPhase PhaseOf(OrderState state)
        {
            switch (state)
            {
                case OrderState.Submitted:
                case OrderState.Accepted:
                case OrderState.Working:
                case OrderState.TriggerPending:
                case OrderState.AcceptedByRisk:
                case OrderState.PartFilled: // first seen part-filled: still judge and cancel the rest
                    return OrderPhase.Live;
                case OrderState.ChangePending:
                case OrderState.ChangeSubmitted:
                    return OrderPhase.Changing;
                case OrderState.Filled:
                case OrderState.Cancelled:
                case OrderState.Rejected:
                    return OrderPhase.Done;
                default:
                    return OrderPhase.Ignore;
            }
        }

        private static bool IsWorking(OrderState state) =>
            state != OrderState.Filled && state != OrderState.Cancelled
            && state != OrderState.Rejected && state != OrderState.Unknown;
    }
}
