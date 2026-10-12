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
        public static ExtremeTrack Track(GateSide side, ExtremeInput input, IList<GateBar> oneMinuteBars) =>
            input == null ? null : Track(side, new[] { input }, oneMinuteBars);

        /// <summary>
        /// Replays every edit of the extreme (ascending SetAt). Each edit pins the trader's price
        /// until a closed 1m bar trades beyond it; from then on the extreme follows the most
        /// extreme price traded. Breaks found under earlier edits are kept, so editing the
        /// extreme never erases the history a dead level was judged on. Bars closed at or before
        /// the first edit are ignored.
        /// </summary>
        public static ExtremeTrack Track(GateSide side, IReadOnlyList<ExtremeInput> edits, IList<GateBar> oneMinuteBars)
        {
            if (edits == null || edits.Count == 0) return null;

            double value = edits[0].Price;
            var mode = ExtremeMode.Pinned;
            int nextEdit = 1;
            var breaks = new List<long>();
            long lastEnd = long.MinValue;
            foreach (var bar in oneMinuteBars)
            {
                if (bar.EndTime <= edits[0].SetAt) continue;
                if (bar.EndTime <= lastEnd) continue; // duplicate or out-of-order bar
                lastEnd = bar.EndTime;
                while (nextEdit < edits.Count && edits[nextEdit].SetAt < bar.EndTime)
                {
                    value = edits[nextEdit].Price;
                    mode = ExtremeMode.Pinned;
                    nextEdit++;
                }
                double traded = SideMath.ExtremeOf(side, bar);
                if (SideMath.IsBeyond(side, traded, value))
                {
                    value = traded;
                    mode = ExtremeMode.Auto;
                    breaks.Add(bar.EndTime);
                }
            }
            if (nextEdit < edits.Count)
            {
                value = edits[edits.Count - 1].Price;
                mode = ExtremeMode.Pinned;
            }
            return new ExtremeTrack(value, mode, breaks);
        }
    }
}
