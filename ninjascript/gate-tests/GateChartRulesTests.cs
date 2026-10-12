using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateChartRulesTests
    {
        private static GateSnapshot LongSetupSnapshot(bool shortLevelAtSamePrice = false)
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            g.SetExtreme(GateSide.Long, 100.0, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.M1, 105.0, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.H1, 105.0, 0);
            g.SetExtreme(GateSide.Short, 110.0, 0);
            g.SetLevel(GateSide.Short, GateTimeframe.M3, shortLevelAtSamePrice ? 105.0 : 107.0, 0);
            g.AnswerTrend(GateTrend.Up, g.LatestHourEnd);
            return g.Snapshot();
        }

        [TestCase(SetupState.NoLevel, GateIcon.NoLevel)]
        [TestCase(SetupState.WaitingForBreak, GateIcon.Waiting)]
        [TestCase(SetupState.Broken, GateIcon.Waiting)]
        [TestCase(SetupState.Reset, GateIcon.Waiting)]
        [TestCase(SetupState.Strike, GateIcon.Waiting)]
        [TestCase(SetupState.OneClose, GateIcon.OutlineGreen)]
        [TestCase(SetupState.Confirmed, GateIcon.SolidGreen)]
        [TestCase(SetupState.Dead, GateIcon.Dead)]
        public void IconForEveryState(SetupState state, GateIcon icon)
        {
            Assert.That(GateVisuals.IconFor(state), Is.EqualTo(icon));
        }

        [Test]
        public void EachTimeframeHasItsOwnColour()
        {
            var colours = new[] { GateTimeframe.M1, GateTimeframe.M3, GateTimeframe.H1, GateTimeframe.H4 }
                .Select(GateVisuals.ColorHex).Concat(new[] { GateVisuals.ExtremeColorHex }).ToList();
            Assert.That(colours.Distinct().Count(), Is.EqualTo(5));
        }

        [Test]
        public void LinesCoverBothSidesWithLabels()
        {
            var lines = ChartLines.From(LongSetupSnapshot());
            Assert.That(lines.Count, Is.EqualTo(5));

            var low = lines.Single(l => l.IsExtreme && l.Side == GateSide.Long);
            Assert.That(low.Label, Is.EqualTo("▲ LOW 100.00 pinned"));
            Assert.That(low.IsActiveSide, Is.True);
            Assert.That(low.Timeframe, Is.Null);

            var oneMinute = lines.Single(l => l.Timeframe == GateTimeframe.M1);
            Assert.That(oneMinute.Label, Is.EqualTo("▲ 1m LVL 105.00"));
            Assert.That(oneMinute.ColorHex, Is.EqualTo(GateVisuals.ColorHex(GateTimeframe.M1)));

            var shortLevel = lines.Single(l => l.Side == GateSide.Short && !l.IsExtreme);
            Assert.That(shortLevel.Label, Is.EqualTo("▼ 3m LVL 107.00"));
            Assert.That(shortLevel.IsActiveSide, Is.False);
            Assert.That(lines.Single(l => l.Side == GateSide.Short && l.IsExtreme).Label, Is.EqualTo("▼ HIGH 110.00 pinned"));
        }

        [Test]
        public void CoincidentLinesStackTheirLabels()
        {
            var lines = ChartLines.From(LongSetupSnapshot(shortLevelAtSamePrice: true));
            var at105 = lines.Where(l => l.Price == 105.0).OrderBy(l => l.StackIndex).ToList();
            Assert.That(at105.Count, Is.EqualTo(3));
            Assert.That(at105.Select(l => l.StackIndex), Is.EqualTo(new[] { 0, 1, 2 }));
            Assert.That(lines.Single(l => l.Price == 100.0).StackIndex, Is.EqualTo(0));
        }

        [Test]
        public void NearestLineWithinTolerance()
        {
            var lines = ChartLines.From(LongSetupSnapshot());
            // 10 px per point, price 100 at y=500 (prices increase upward).
            var hit = ChartLines.NearestWithin(lines, p => 500 - (p - 100) * 10, 452, 6);
            Assert.That(hit, Is.Not.Null);
            Assert.That(hit.Price, Is.EqualTo(105.0));
            Assert.That(ChartLines.NearestWithin(lines, p => 500 - (p - 100) * 10, 470, 6), Is.Null);
        }

        [Test]
        public void ClickModeLevelAndExtreme()
        {
            var mode = new ChartClickMode();
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.None));
            Assert.That(mode.Prompt, Is.Null);

            mode.BeginLevel(GateSide.Short, GateTimeframe.H1);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.Level));
            Assert.That(mode.Side, Is.EqualTo(GateSide.Short));
            Assert.That(mode.Timeframe, Is.EqualTo(GateTimeframe.H1));
            Assert.That(mode.Prompt, Is.EqualTo("Click the chart to place the short 1h level — Esc cancels."));

            mode.BeginExtreme(GateSide.Long);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.Extreme));
            Assert.That(mode.Prompt, Is.EqualTo("Click the chart to place the low — Esc cancels."));

            mode.Cancel();
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.None));
        }

        [Test]
        public void BreakEvenOnlyOnTheFirstTarget()
        {
            Assert.That(BreakEvenTrigger.IsFirstTarget("Target1"), Is.True);
            Assert.That(BreakEvenTrigger.IsFirstTarget("Target2"), Is.False);
            Assert.That(BreakEvenTrigger.IsFirstTarget(null), Is.False);
        }

        [Test]
        public void BreakEvenMovesOnlyStopsNotPairedWithTheFilledTarget()
        {
            Assert.That(BreakEvenTrigger.ShouldMoveStop("Stop2", "oco-2", "oco-1"), Is.True);
            Assert.That(BreakEvenTrigger.ShouldMoveStop("Stop1", "oco-1", "oco-1"), Is.False);
            Assert.That(BreakEvenTrigger.ShouldMoveStop("Target2", "oco-2", "oco-1"), Is.False);
            Assert.That(BreakEvenTrigger.ShouldMoveStop("Stop2", null, "oco-1"), Is.True);
        }
    }
}
