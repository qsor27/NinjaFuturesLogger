using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>NinjaTrader timestamps are wall-clock times in the trader's configured zone.</summary>
    public static class GateTime
    {
        private static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        public static long ToUnixSeconds(DateTime time, TimeZoneInfo zone)
        {
            DateTime utc = time.Kind == DateTimeKind.Utc
                ? time
                : TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(time, DateTimeKind.Unspecified), zone);
            return (long)(utc - Epoch).TotalSeconds;
        }

        public static DateTime FromUnixSeconds(long seconds, TimeZoneInfo zone) =>
            TimeZoneInfo.ConvertTimeFromUtc(Epoch.AddSeconds(seconds), zone);

        /// <summary>NinjaTrader minute bars are stamped with their close time.</summary>
        public static GateBar BarFromClose(DateTime closeTime, int periodMinutes, double open, double high,
            double low, double close, TimeZoneInfo zone)
        {
            long end = ToUnixSeconds(closeTime, zone);
            return new GateBar(end - periodMinutes * 60L, end, open, high, low, close);
        }

        public static int MinutesOf(GateTimeframe tf)
        {
            switch (tf)
            {
                case GateTimeframe.M1: return 1;
                case GateTimeframe.M3: return 3;
                case GateTimeframe.H1: return 60;
                default: return 240;
            }
        }
    }

    /// <summary>
    /// Tracks which bars of a live bar series have been delivered. The last bar is still forming,
    /// so a bar is delivered only once a newer bar exists — i.e. at the next bar's first tick.
    /// </summary>
    public sealed class ClosedBarCursor
    {
        public int LastDelivered { get; private set; } = -1;

        public IReadOnlyList<int> Advance(int count)
        {
            var indexes = new List<int>();
            for (int i = LastDelivered + 1; i <= count - 2; i++) indexes.Add(i);
            if (count - 2 > LastDelivered) LastDelivered = count - 2;
            return indexes;
        }

        public void Reset() => LastDelivered = -1;
    }

    public enum OrderPhase { Live, Changing, Done, Ignore }

    /// <summary>Turns a stream of order updates into the submits and changes the gate must judge.</summary>
    public sealed class OrderIntentTracker
    {
        private static readonly Regex AtmBracketName = new Regex(@"^(Stop|Target)\d+$");
        private readonly Dictionary<long, int> judgedQuantity = new Dictionary<long, int>();

        public static bool IsAtmBracket(string orderName) => orderName != null && AtmBracketName.IsMatch(orderName);

        /// <summary>Returns the intent to judge, or null when this update needs no decision.</summary>
        public OrderIntent Observe(long orderId, OrderPhase phase, bool isBuy, int quantity, bool isGateEntry, bool isAtmBracket)
        {
            int previous;
            switch (phase)
            {
                case OrderPhase.Live:
                    if (judgedQuantity.ContainsKey(orderId)) return null;
                    judgedQuantity[orderId] = quantity;
                    return new OrderIntent(isBuy, quantity, isGateEntry, false, 0, isAtmBracket);
                case OrderPhase.Changing:
                    if (!judgedQuantity.TryGetValue(orderId, out previous))
                    {
                        judgedQuantity[orderId] = quantity;
                        return new OrderIntent(isBuy, quantity, isGateEntry, false, 0, isAtmBracket);
                    }
                    judgedQuantity[orderId] = quantity;
                    return new OrderIntent(isBuy, quantity, isGateEntry, true, previous, isAtmBracket);
                case OrderPhase.Done:
                    judgedQuantity.Remove(orderId);
                    return null;
                default:
                    return null;
            }
        }
    }

    /// <summary>Recently allowed leader entries that copier followers may mirror (spec §7).</summary>
    public sealed class LeaderEntryLog
    {
        private readonly List<LeaderEntry> entries = new List<LeaderEntry>();

        public void Add(LeaderEntry entry) => entries.Add(entry);

        public IReadOnlyList<LeaderEntry> Recent(long now, int windowSeconds)
        {
            entries.RemoveAll(e => now - e.Time > windowSeconds);
            return entries.ToArray();
        }
    }
}
