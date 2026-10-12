using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>The shared low (Long) or high (Short) after replaying 1m bars.</summary>
    public sealed class ExtremeTrack
    {
        public ExtremeTrack(double value, ExtremeMode mode, IReadOnlyList<long> breakTimes)
        {
            Value = value;
            Mode = mode;
            BreakTimes = breakTimes;
        }

        public double Value { get; }
        public ExtremeMode Mode { get; }

        /// <summary>EndTime of every 1m bar that made a new extreme, ascending.</summary>
        public IReadOnlyList<long> BreakTimes { get; }
    }

    public static class ExtremeTracker
    {
        /// <summary>
        /// The trader's price is pinned until a closed 1m bar trades beyond it; from then on the
        /// extreme follows the most extreme price traded. Bars closed at or before SetAt are ignored.
        /// </summary>
        public static ExtremeTrack Track(GateSide side, ExtremeInput input, IList<GateBar> oneMinuteBars)
        {
            if (input == null) return null;

            double value = input.Price;
            var mode = ExtremeMode.Pinned;
            var breaks = new List<long>();
            foreach (var bar in oneMinuteBars)
            {
                if (bar.EndTime <= input.SetAt) continue;
                double traded = SideMath.ExtremeOf(side, bar);
                if (SideMath.IsBeyond(side, traded, value))
                {
                    value = traded;
                    mode = ExtremeMode.Auto;
                    breaks.Add(bar.EndTime);
                }
            }
            return new ExtremeTrack(value, mode, breaks);
        }
    }
}
