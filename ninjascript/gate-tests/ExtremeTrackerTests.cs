using System.Collections.Generic;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class ExtremeTrackerTests
    {
        private static GateBar Bar(long end, double low, double high) =>
            new GateBar(end - 60, end, low, high, low, high);

        [Test]
        public void StaysPinnedUntilBreached()
        {
            var bars = new List<GateBar> { Bar(60, 100.25, 101), Bar(120, 100.0, 101) };
            var t = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), bars);
            Assert.That(t.Value, Is.EqualTo(100.0));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Pinned));
            Assert.That(t.BreakTimes, Is.Empty);
        }

        [Test]
        public void BreachSwitchesToAutoAndFollowsNewLows()
        {
            var bars = new List<GateBar> { Bar(60, 99.0, 101), Bar(120, 98.5, 100), Bar(180, 99.5, 100) };
            var t = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), bars);
            Assert.That(t.Value, Is.EqualTo(98.5));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Auto));
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 60, 120 }));
        }

        [Test]
        public void IgnoresBarsClosedAtOrBeforeSetAt()
        {
            var bars = new List<GateBar> { Bar(60, 90.0, 95), Bar(120, 91.0, 95), Bar(180, 101, 102) };
            var t = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 120), bars);
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Pinned));
            Assert.That(t.BreakTimes, Is.Empty);
        }

        [Test]
        public void TraderEditRepinsUntilPriceTradesBeyondIt()
        {
            var bars = new List<GateBar> { Bar(60, 98.0, 99), Bar(240, 98.75, 99), Bar(300, 98.25, 99) };
            var t = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(98.5, 200), bars);
            Assert.That(t.Value, Is.EqualTo(98.25));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Auto));
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 300 }));
        }

        [Test]
        public void Short_TracksHighs()
        {
            var bars = new List<GateBar> { Bar(60, 199, 200.0), Bar(120, 199, 201.5), Bar(180, 199, 201.0) };
            var t = ExtremeTracker.Track(GateSide.Short, new ExtremeInput(200.0, 0), bars);
            Assert.That(t.Value, Is.EqualTo(201.5));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Auto));
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 120 }));
        }

        [Test]
        public void EditHistoryKeepsEarlierBreaks()
        {
            var bars = new List<GateBar> { Bar(60, 99.0, 101), Bar(360, 96.0, 99) };
            var edits = new List<ExtremeInput> { new ExtremeInput(100.0, 0), new ExtremeInput(97.0, 290) };
            var t = ExtremeTracker.Track(GateSide.Long, edits, bars);
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 60, 360 }));
            Assert.That(t.Value, Is.EqualTo(96.0));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Auto));
        }

        [Test]
        public void EditRepinsWithoutAddingABreak()
        {
            var bars = new List<GateBar> { Bar(60, 99.0, 101), Bar(360, 98.0, 99) };
            var edits = new List<ExtremeInput> { new ExtremeInput(100.0, 0), new ExtremeInput(97.0, 290) };
            var t = ExtremeTracker.Track(GateSide.Long, edits, bars);
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 60 }));
            Assert.That(t.Value, Is.EqualTo(97.0));
            Assert.That(t.Mode, Is.EqualTo(ExtremeMode.Pinned));
        }

        [Test]
        public void DuplicateAndOutOfOrderBarsAreSkipped()
        {
            var bars = new List<GateBar> { Bar(60, 99.0, 101), Bar(60, 98.0, 101), Bar(30, 97.0, 101) };
            var t = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), bars);
            Assert.That(t.BreakTimes, Is.EqualTo(new long[] { 60 }));
            Assert.That(t.Value, Is.EqualTo(99.0));
        }

        [Test]
        public void NullInputReturnsNull()
        {
            Assert.That(ExtremeTracker.Track(GateSide.Long, (ExtremeInput)null, new List<GateBar>()), Is.Null);
        }
    }
}
