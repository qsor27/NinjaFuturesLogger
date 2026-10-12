using System;
using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class GateDecision
    {
        private GateDecision(bool allowed, string reason)
        {
            Allowed = allowed;
            Reason = reason;
        }

        public bool Allowed { get; }
        public string Reason { get; }

        public static GateDecision Allow() => new GateDecision(true, null);
        public static GateDecision Cancel(string reason) => new GateDecision(false, reason);
    }

    /// <summary>An order seen on submit (IsChange false) or on change (IsChange true).</summary>
    public sealed class OrderIntent
    {
        public OrderIntent(bool isBuy, int quantity, bool isGateEntry, bool isChange, int previousQuantity)
        {
            IsBuy = isBuy;
            Quantity = quantity;
            IsGateEntry = isGateEntry;
            IsChange = isChange;
            PreviousQuantity = previousQuantity;
        }

        public bool IsBuy { get; }
        public int Quantity { get; }
        public bool IsGateEntry { get; }
        public bool IsChange { get; }
        public int PreviousQuantity { get; }
    }

    /// <summary>Spec §7 order table for a gated leader account.</summary>
    public static class OrderGate
    {
        public static GateDecision Decide(OrderIntent order, int positionQty)
        {
            if (order.Quantity <= 0) return GateDecision.Cancel("Order quantity must be positive.");

            if (order.IsGateEntry)
            {
                if (order.IsChange)
                {
                    return order.Quantity == order.PreviousQuantity
                        ? GateDecision.Allow()
                        : GateDecision.Cancel("The size of an armed entry can't be changed.");
                }
                return positionQty == 0
                    ? GateDecision.Allow()
                    : GateDecision.Cancel("Already in a position — adding isn't allowed.");
            }

            if (positionQty == 0) return GateDecision.Cancel("Entries are only allowed through an armed setup.");
            return CheckExit(order.IsBuy, order.Quantity, positionQty);
        }

        /// <summary>Reduce-only rule for a non-flat position: opposite direction, at most the position's size.</summary>
        public static GateDecision CheckExit(bool isBuy, int quantity, int positionQty)
        {
            if (quantity <= 0) return GateDecision.Cancel("Order quantity must be positive.");
            bool reduces = positionQty > 0 ? !isBuy : isBuy;
            if (!reduces) return GateDecision.Cancel("Adding to a position isn't allowed.");
            int held = Math.Abs(positionQty);
            if (quantity > held)
                return GateDecision.Cancel(
                    "Exit size " + quantity + " is larger than the position (" + held + ") — reversing isn't allowed.");
            return GateDecision.Allow();
        }
    }

    /// <summary>A leader entry the gate allowed; followers may copy it within the window.</summary>
    public sealed class LeaderEntry
    {
        public LeaderEntry(string instrument, bool isBuy, long time)
        {
            Instrument = instrument;
            IsBuy = isBuy;
            Time = time;
        }

        public string Instrument { get; }
        public bool IsBuy { get; }
        public long Time { get; }
    }

    /// <summary>Spec §7 "Trade copier": follower accounts mirror allowed leader entries only.</summary>
    public static class FollowerGate
    {
        public static GateDecision Decide(string instrument, bool isBuy, int quantity, int followerPositionQty,
            IEnumerable<LeaderEntry> allowedLeaderEntries, long now, int windowSeconds)
        {
            if (quantity <= 0) return GateDecision.Cancel("Order quantity must be positive.");
            if (followerPositionQty != 0) return OrderGate.CheckExit(isBuy, quantity, followerPositionQty);

            foreach (var e in allowedLeaderEntries)
            {
                if (e.Instrument == instrument && e.IsBuy == isBuy && Math.Abs(now - e.Time) <= windowSeconds)
                    return GateDecision.Allow();
            }
            return GateDecision.Cancel(
                "No matching leader entry in the last " + windowSeconds + " s — follower entry cancelled.");
        }
    }
}
