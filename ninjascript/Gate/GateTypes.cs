namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    // Pure Setup Gate core (spec: docs/superpowers/specs/2026-10-12-setup-gate-design.md).
    // Nothing under ninjascript/Gate/ may reference NinjaTrader types, so the same files
    // compile inside NT8 and in ninjascript/gate-tests/.

    public enum GateSide { Long, Short }

    public enum GateTimeframe { M1, M3, H1, H4 }

    public enum GateTrend { Unconfirmed, Up, Down }

    public enum SetupState { NoLevel, WaitingForBreak, Broken, OneClose, Reset, Confirmed, Strike, Dead }

    public enum ExtremeMode { Pinned, Auto }

    /// <summary>A closed bar. Times are Unix seconds; EndTime is the bar's close time.</summary>
    public sealed class GateBar
    {
        public GateBar(long startTime, long endTime, double open, double high, double low, double close)
        {
            StartTime = startTime;
            EndTime = endTime;
            Open = open;
            High = high;
            Low = low;
            Close = close;
        }

        public long StartTime { get; }
        public long EndTime { get; }
        public double Open { get; }
        public double High { get; }
        public double Low { get; }
        public double Close { get; }
    }

    /// <summary>The trader's low (Long side) or high (Short side), entered at SetAt.</summary>
    public sealed class ExtremeInput
    {
        public ExtremeInput(double price, long setAt)
        {
            Price = price;
            SetAt = setAt;
        }

        public double Price { get; }
        public long SetAt { get; }
    }

    /// <summary>
    /// The trader's level for one timeframe. A break of the extreme only counts toward this
    /// level if it happened after RequireBreakAfter: the previous level's death time when the
    /// level replaced a dead one, otherwise 0.
    /// </summary>
    public sealed class LevelInput
    {
        public LevelInput(double price, long setAt, long requireBreakAfter)
        {
            Price = price;
            SetAt = setAt;
            RequireBreakAfter = requireBreakAfter;
        }

        public double Price { get; }
        public long SetAt { get; }
        public long RequireBreakAfter { get; }
    }

    /// <summary>Direction helpers so every rule is written once for both sides.</summary>
    public static class SideMath
    {
        /// <summary>Long: price traded below the reference. Short: above it.</summary>
        public static bool IsBeyond(GateSide side, double price, double reference) =>
            side == GateSide.Long ? price < reference : price > reference;

        /// <summary>Long: closed strictly above the level. Short: strictly below. Equal is not a regain.</summary>
        public static bool IsRegained(GateSide side, double close, double level) =>
            side == GateSide.Long ? close > level : close < level;

        public static double ExtremeOf(GateSide side, GateBar bar) =>
            side == GateSide.Long ? bar.Low : bar.High;

        /// <summary>The side the hourly trend allows to trade; null while unconfirmed.</summary>
        public static GateSide? ActiveSide(GateTrend trend)
        {
            if (trend == GateTrend.Up) return GateSide.Long;
            if (trend == GateTrend.Down) return GateSide.Short;
            return null;
        }
    }
}
