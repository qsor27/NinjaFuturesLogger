using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public enum GateIcon { NoLevel, Waiting, OutlineGreen, SolidGreen, Dead }

    /// <summary>Spec §9 icons and colours.</summary>
    public static class GateVisuals
    {
        public const string ExtremeColorHex = "#DCDCDC";

        public static GateIcon IconFor(SetupState state)
        {
            switch (state)
            {
                case SetupState.NoLevel: return GateIcon.NoLevel;
                case SetupState.OneClose: return GateIcon.OutlineGreen;
                case SetupState.Confirmed: return GateIcon.SolidGreen;
                case SetupState.Dead: return GateIcon.Dead;
                default: return GateIcon.Waiting;
            }
        }

        public static string ColorHex(GateTimeframe tf)
        {
            switch (tf)
            {
                case GateTimeframe.M1: return "#00BFFF";
                case GateTimeframe.M3: return "#BA55D3";
                case GateTimeframe.H1: return "#FFD700";
                default: return "#FF8C00";
            }
        }
    }

    /// <summary>One horizontal line the chart draws: a side's extreme or one timeframe's level.</summary>
    public sealed class ChartLine
    {
        public ChartLine(GateSide side, GateTimeframe? timeframe, double price, string label, string colorHex, bool isActiveSide)
        {
            Side = side;
            Timeframe = timeframe;
            Price = price;
            Label = label;
            ColorHex = colorHex;
            IsActiveSide = isActiveSide;
        }

        public GateSide Side { get; }

        /// <summary>Null for the side's low/high line.</summary>
        public GateTimeframe? Timeframe { get; }

        public bool IsExtreme => !Timeframe.HasValue;
        public double Price { get; }
        public string Label { get; }
        public string ColorHex { get; }

        /// <summary>False for the side the hourly trend doesn't allow; drawn dimmed.</summary>
        public bool IsActiveSide { get; }

        /// <summary>0 for the first line at this price, 1 for the next, … so labels never overprint.</summary>
        public int StackIndex { get; internal set; }
    }

    public static class ChartLines
    {
        public static IReadOnlyList<ChartLine> From(GateSnapshot snapshot)
        {
            var lines = new List<ChartLine>();
            if (snapshot == null) return lines;
            foreach (var side in new[] { snapshot.Long, snapshot.Short })
            {
                string arrow = side.Side == GateSide.Long ? "▲ " : "▼ ";
                if (side.Extreme.HasValue)
                {
                    string word = side.Side == GateSide.Long ? "LOW " : "HIGH ";
                    string mode = side.ExtremeMode == ExtremeMode.Auto ? " auto" : " pinned";
                    lines.Add(new ChartLine(side.Side, null, side.Extreme.Value,
                        arrow + word + InstrumentGate.FormatPrice(side.Extreme.Value) + mode, GateVisuals.ExtremeColorHex, side.IsActive));
                }
                foreach (var tf in side.Timeframes)
                {
                    if (!tf.LevelPrice.HasValue) continue;
                    lines.Add(new ChartLine(side.Side, tf.Timeframe, tf.LevelPrice.Value,
                        arrow + InstrumentGate.Label(tf.Timeframe) + " LVL " + InstrumentGate.FormatPrice(tf.LevelPrice.Value),
                        GateVisuals.ColorHex(tf.Timeframe), side.IsActive));
                }
            }

            var used = new Dictionary<long, int>();
            foreach (var line in lines)
            {
                long key = (long)Math.Round(line.Price * 1e6);
                int count;
                used.TryGetValue(key, out count);
                line.StackIndex = count;
                used[key] = count + 1;
            }
            return lines;
        }

        private const double LabelMarginPixels = 3;

        /// <summary>
        /// The line whose drawn label contains the point (with a small margin), or null. Only labels
        /// are grabbable, so clicks on the line elsewhere — where the trader's own stops, orders and
        /// drawings sit — always reach NinjaTrader.
        /// </summary>
        public static ChartLine LabelAt(IEnumerable<LabelBox> boxes, double x, double y)
        {
            foreach (var box in boxes)
            {
                if (x >= box.Left - LabelMarginPixels && x <= box.Right + LabelMarginPixels
                    && y >= box.Top - LabelMarginPixels && y <= box.Bottom + LabelMarginPixels)
                    return box.Line;
            }
            return null;
        }

        /// <summary>True when the point is inside the price panel (not a lower panel or an axis).</summary>
        public static bool IsInside(double x, double y, double left, double top, double width, double height) =>
            x >= left && x <= left + width && y >= top && y <= top + height;

        /// <summary>The line closest to y (pixels) within tolerance, or null — used to start a drag.</summary>
        public static ChartLine NearestWithin(IReadOnlyList<ChartLine> lines, Func<double, double> yOfPrice, double y, double tolerance)
        {
            ChartLine best = null;
            double bestDistance = double.MaxValue;
            foreach (var line in lines)
            {
                double distance = Math.Abs(yOfPrice(line.Price) - y);
                if (distance <= tolerance && distance < bestDistance)
                {
                    best = line;
                    bestDistance = distance;
                }
            }
            return best;
        }
    }

    /// <summary>A drawn label's rectangle in chart pixels; only labels are grabbable.</summary>
    public sealed class LabelBox
    {
        public LabelBox(ChartLine line, double left, double top, double right, double bottom)
        {
            Line = line; Left = left; Top = top; Right = right; Bottom = bottom;
        }

        public ChartLine Line { get; }
        public double Left { get; }
        public double Top { get; }
        public double Right { get; }
        public double Bottom { get; }
    }

    public enum ClickTarget { None, Level, Extreme }

    /// <summary>Spec §9: press Set Level / Set Low, then the next chart click places it.</summary>
    public sealed class ChartClickMode
    {
        public ClickTarget Target { get; private set; }
        public GateSide Side { get; private set; }
        public GateTimeframe Timeframe { get; private set; }

        public void BeginLevel(GateSide side, GateTimeframe tf)
        {
            Target = ClickTarget.Level;
            Side = side;
            Timeframe = tf;
        }

        public void BeginExtreme(GateSide side)
        {
            Target = ClickTarget.Extreme;
            Side = side;
        }

        public void Cancel() => Target = ClickTarget.None;

        /// <summary>
        /// A Set Level / Set Low press: starts click mode, or cancels it when the same button is
        /// pressed again (Esc may not reach the chart while Chart Trader has focus). Returns true
        /// when click mode is now on.
        /// </summary>
        public bool Press(ClickTarget target, GateSide side, GateTimeframe tf)
        {
            if (Target == target)
            {
                Cancel();
                return false;
            }
            if (target == ClickTarget.Level) BeginLevel(side, tf);
            else BeginExtreme(side);
            return true;
        }

        public string Prompt
        {
            get
            {
                if (Target == ClickTarget.Level)
                    return "Click the chart to place the " + Side.ToString().ToLowerInvariant() + " "
                        + InstrumentGate.Label(Timeframe) + " level — Esc cancels.";
                if (Target == ClickTarget.Extreme)
                    return "Click the chart to place the " + InstrumentGate.ExtremeWord(Side) + " — Esc cancels.";
                return null;
            }
        }
    }

    /// <summary>
    /// Spec §8: after Target 1 fills, move the remaining stops. The stop OCO-paired with the filled
    /// target is being cancelled by the ATM, so only stops from other OCO groups move.
    /// </summary>
    public static class BreakEvenTrigger
    {
        private static readonly Regex StopName = new Regex(@"^Stop\d+$");

        public static bool IsFirstTarget(string orderName) => orderName == "Target1";

        public static bool ShouldMoveStop(string stopName, string stopOco, string filledTargetOco) =>
            stopName != null && StopName.IsMatch(stopName) && !string.Equals(stopOco, filledTargetOco, StringComparison.Ordinal);
    }
}
