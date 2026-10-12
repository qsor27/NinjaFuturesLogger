using System.Globalization;
using System.Threading;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class BreakEvenTests
    {
        [Test]
        public void Long_EntryPlusTicks()
        {
            var r = BreakEven.StopPrice(GateSide.Long, 100.0, 1, 0.25, 102.0);
            Assert.That(r.Price, Is.EqualTo(100.25).Within(1e-9));
            Assert.That(r.Adjusted, Is.False);
        }

        [Test]
        public void Short_EntryMinusTicks()
        {
            var r = BreakEven.StopPrice(GateSide.Short, 100.0, 2, 0.25, 98.0);
            Assert.That(r.Price, Is.EqualTo(99.5).Within(1e-9));
            Assert.That(r.Adjusted, Is.False);
        }

        [Test]
        public void Long_MarketableStop_OneTickBelowLast()
        {
            var r = BreakEven.StopPrice(GateSide.Long, 100.0, 1, 0.25, 100.25);
            Assert.That(r.Price, Is.EqualTo(100.0).Within(1e-9));
            Assert.That(r.Adjusted, Is.True);
        }

        [Test]
        public void Short_MarketableStop_OneTickAboveLast()
        {
            var r = BreakEven.StopPrice(GateSide.Short, 100.0, 1, 0.25, 99.75);
            Assert.That(r.Price, Is.EqualTo(100.0).Within(1e-9));
            Assert.That(r.Adjusted, Is.True);
        }

        [Test]
        public void ZeroTicks_IsExactBreakEven()
        {
            var r = BreakEven.StopPrice(GateSide.Long, 30880.5, 0, 0.25, 30890.0);
            Assert.That(r.Price, Is.EqualTo(30880.5).Within(1e-9));
        }

        [Test]
        public void RoundToTick_SnapsToGrid()
        {
            Assert.That(BreakEven.RoundToTick(30880.63, 0.25), Is.EqualTo(30880.75).Within(1e-9));
        }

        [Test]
        public void Describe_PluralAndDollarsInvariantCulture()
        {
            var saved = Thread.CurrentThread.CurrentCulture;
            Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
            try
            {
                Assert.That(BreakEven.Describe(1, 0.25, 2.0, "MNQ"), Is.EqualTo("entry + 1 tick ($0.50 on MNQ)"));
                Assert.That(BreakEven.Describe(2, 0.25, 2.0, "MNQ"), Is.EqualTo("entry + 2 ticks ($1.00 on MNQ)"));
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = saved;
            }
        }
    }
}
