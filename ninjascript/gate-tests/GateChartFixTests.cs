using System.Collections.Generic;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    /// Plan C final-review fixes: grab only by the label, respect panel bounds, toggle click mode.
    public class GateChartFixTests
    {
        private static readonly ChartLine Low = new ChartLine(GateSide.Long, null, 100, "▲ LOW 100.00 pinned", "#DCDCDC", true);
        private static readonly ChartLine OneMinute = new ChartLine(GateSide.Long, GateTimeframe.M1, 105, "▲ 1m LVL 105.00", "#00BFFF", true);

        private static List<LabelBox> Boxes() => new List<LabelBox>
        {
            new LabelBox(Low, 800, 486, 900, 500),
            new LabelBox(OneMinute, 810, 436, 900, 450),
        };

        [Test]
        public void GrabsOnlyInsideALabel()
        {
            Assert.That(ChartLines.LabelAt(Boxes(), 850, 440), Is.SameAs(OneMinute));
            Assert.That(ChartLines.LabelAt(Boxes(), 850, 495), Is.SameAs(Low));
            // On the line itself, far from its label (where the trader's own stop or drawings sit): no grab.
            Assert.That(ChartLines.LabelAt(Boxes(), 300, 450), Is.Null);
            Assert.That(ChartLines.LabelAt(Boxes(), 300, 500), Is.Null);
        }

        [Test]
        public void LabelHitAllowsASmallMargin()
        {
            Assert.That(ChartLines.LabelAt(Boxes(), 808, 434), Is.SameAs(OneMinute));
            Assert.That(ChartLines.LabelAt(Boxes(), 805, 430), Is.Null);
        }

        [Test]
        public void PointsOutsideThePricePanelAreRejected()
        {
            Assert.That(ChartLines.IsInside(10, 10, 0, 0, 900, 600), Is.True);
            Assert.That(ChartLines.IsInside(10, 650, 0, 0, 900, 600), Is.False);   // lower indicator panel
            Assert.That(ChartLines.IsInside(950, 10, 0, 0, 900, 600), Is.False);   // price axis
            Assert.That(ChartLines.IsInside(10, -1, 0, 0, 900, 600), Is.False);
        }

        [Test]
        public void PressingTheSameSetButtonAgainCancels()
        {
            var mode = new ChartClickMode();
            Assert.That(mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.M1), Is.True);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.Level));
            Assert.That(mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.M1), Is.False);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.None));
        }

        [Test]
        public void PressingAnotherTimeframesSetButtonSwitchesToIt()
        {
            var mode = new ChartClickMode();
            mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.M1);
            Assert.That(mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.H1), Is.True);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.Level));
            Assert.That(mode.Timeframe, Is.EqualTo(GateTimeframe.H1));
            Assert.That(mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.H1), Is.False);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.None));
        }

        [Test]
        public void IsPendingIdentifiesTheRowWaitingForAClick()
        {
            var mode = new ChartClickMode();
            mode.Press(ClickTarget.Level, GateSide.Short, GateTimeframe.M3);
            Assert.That(mode.IsPending(ClickTarget.Level, GateSide.Short, GateTimeframe.M3), Is.True);
            Assert.That(mode.IsPending(ClickTarget.Level, GateSide.Short, GateTimeframe.M1), Is.False);
            Assert.That(mode.IsPending(ClickTarget.Extreme, GateSide.Short, GateTimeframe.M3), Is.False);
            mode.Press(ClickTarget.Extreme, GateSide.Short, GateTimeframe.M1);
            Assert.That(mode.IsPending(ClickTarget.Extreme, GateSide.Short, GateTimeframe.H4), Is.True);
        }

        [Test]
        public void PressingTheOtherSetButtonSwitches()
        {
            var mode = new ChartClickMode();
            mode.Press(ClickTarget.Level, GateSide.Long, GateTimeframe.M1);
            Assert.That(mode.Press(ClickTarget.Extreme, GateSide.Short, GateTimeframe.M1), Is.True);
            Assert.That(mode.Target, Is.EqualTo(ClickTarget.Extreme));
            Assert.That(mode.Side, Is.EqualTo(GateSide.Short));
        }
    }
}
