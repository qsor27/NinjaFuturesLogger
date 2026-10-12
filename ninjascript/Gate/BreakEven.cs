using System;
using System.Globalization;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class BreakEvenResult
    {
        public BreakEvenResult(double price, bool adjusted)
        {
            Price = price;
            Adjusted = adjusted;
        }

        public double Price { get; }

        /// <summary>True when the break-even price was already marketable and was moved one tick from last.</summary>
        public bool Adjusted { get; }
    }

    /// <summary>Spec §8: move the remaining stop past entry after Target 1 fills.</summary>
    public static class BreakEven
    {
        public static BreakEvenResult StopPrice(GateSide side, double averageEntry, int offsetTicks,
            double tickSize, double lastPrice)
        {
            double offset = offsetTicks * tickSize;
            // Round away from a loss: up for a long's sell stop, down for a short's buy stop, so an
            // off-tick average entry never yields a "break-even" stop on the losing side of entry.
            double stop = side == GateSide.Long
                ? CeilToTick(averageEntry + offset, tickSize)
                : FloorToTick(averageEntry - offset, tickSize);

            if (side == GateSide.Long && stop >= lastPrice)
                return new BreakEvenResult(FloorToTick(lastPrice - tickSize, tickSize), true);
            if (side == GateSide.Short && stop <= lastPrice)
                return new BreakEvenResult(CeilToTick(lastPrice + tickSize, tickSize), true);
            return new BreakEvenResult(stop, false);
        }

        public static double RoundToTick(double price, double tickSize) =>
            Math.Round(price / tickSize, MidpointRounding.AwayFromZero) * tickSize;

        // The epsilon keeps prices already on the grid (e.g. 100.25 / 0.25) from moving a tick.
        private static double CeilToTick(double price, double tickSize) =>
            Math.Ceiling(price / tickSize - 1e-9) * tickSize;

        private static double FloorToTick(double price, double tickSize) =>
            Math.Floor(price / tickSize + 1e-9) * tickSize;

        /// <summary>Plain-language settings text, e.g. "entry + 1 tick ($0.50 on MNQ)".</summary>
        public static string Describe(int offsetTicks, double tickSize, double pointValue, string instrumentRoot)
        {
            double dollars = offsetTicks * tickSize * pointValue;
            string unit = offsetTicks == 1 ? "tick" : "ticks";
            return "entry + " + offsetTicks.ToString(CultureInfo.InvariantCulture) + " " + unit
                + " ($" + dollars.ToString("0.00", CultureInfo.InvariantCulture) + " on " + instrumentRoot + ")";
        }
    }
}
