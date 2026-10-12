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
            }
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

        public void MarkGateEntry(long orderId)
        {
            lock (sync) gateEntryIds.Add(orderId);
        }

        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            try
            {
                var order = e.Order;
                if (order == null || order.Account == null || order.Instrument == null) return;
                string account = order.Account.Name;
                string instrument = order.Instrument.FullName;

                bool isGateEntry;
                lock (sync) isGateEntry = gateEntryIds.Contains(order.Id);
                if (isGateEntry) runtime.SetGateEntryWorking(instrument, order.Id, IsWorking(e.OrderState));

                var settings = runtime.Settings;
                bool leader = settings.IsGated(account);
                bool follower = settings.IsFollower(account);
                if (!leader && !follower) return;

                bool isBuy = order.OrderAction == OrderAction.Buy || order.OrderAction == OrderAction.BuyToCover;
                OrderIntent intent;
                lock (sync)
                {
                    intent = tracker.Observe(order.Id, PhaseOf(e.OrderState), isBuy, e.Quantity, isGateEntry,
                        OrderIntentTracker.IsAtmBracket(order.Name));
                }
                if (intent == null) return;

                int position = PositionOf(order.Account, instrument);
                long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                GateDecision decision;
                if (leader || position != 0 || intent.IsAtmBracket)
                {
                    decision = OrderGate.Decide(intent, position);
                    if (leader && decision.Allowed && isGateEntry && !intent.IsChange)
                    {
                        lock (sync) leaderEntries.Add(new LeaderEntry(instrument, isBuy, now));
                    }
                }
                else
                {
                    IReadOnlyList<LeaderEntry> recent;
                    lock (sync) recent = leaderEntries.Recent(now, settings.FollowerWindowSeconds);
                    decision = FollowerGate.Decide(instrument, isBuy, intent.Quantity, position, recent, now,
                        settings.FollowerWindowSeconds);
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

        private void OnPositionUpdate(object sender, PositionEventArgs e)
        {
            var position = e.Position;
            if (position == null || position.Account == null || position.Instrument == null) return;
            runtime.UpdatePosition(position.Account.Name, position.Instrument.FullName, Signed(e.MarketPosition, e.Quantity));
        }

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
