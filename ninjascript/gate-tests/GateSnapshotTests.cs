using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateSnapshotTests
    {
        private static GateBar M1(long end, double low, double high, double close) =>
            new GateBar(end - 60, end, close, high, low, close);

        private static InstrumentGate LongSetup()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            g.SetExtreme(GateSide.Long, 100.0, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.M1, 105.0, 0);
            g.AnswerTrend(GateTrend.Up);
            return g;
        }

        [Test]
        public void StatusAsksForTheTrendFirst()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            Assert.That(g.StatusLine(), Is.EqualTo("Confirm the hourly trend first."));
        }

        [Test]
        public void StatusWaitsForANewLow()
        {
            Assert.That(LongSetup().StatusLine(), Is.EqualTo("Waiting for a new low."));
        }

        [Test]
        public void StatusWaitsForACloseBackAbove()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            Assert.That(g.StatusLine(), Is.EqualTo("Waiting for a 1m close back above the level."));
        }

        [Test]
        public void StatusReadyToArm_ThenArmed()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            Assert.That(g.StatusLine(), Is.EqualTo("Ready to arm long."));

            g.ArmEntry(new PendingArm(GateSide.Long, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1));
            Assert.That(g.StatusLine(),
                Is.EqualTo("ARMED MKT · 4ptSL-20ptTP · 1 ct — fires at the open after the second close."));
        }

        [Test]
        public void StatusInAPosition()
        {
            var g = LongSetup();
            g.LeaderPositionQty = 2;
            Assert.That(g.StatusLine(), Is.EqualTo("In a position — exits only."));
        }

        [Test]
        public void StatusGateEntryWorking()
        {
            var g = LongSetup();
            g.GateEntryWorking = true;
            Assert.That(g.StatusLine(), Is.EqualTo("Gate entry working — cancel it to re-arm."));
        }

        [Test]
        public void StatusDead()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            g.OnBarClosed(GateTimeframe.M1, M1(180, 103, 106, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(240, 103, 106, 104));
            Assert.That(g.StatusLine(), Is.EqualTo("1m setup is dead — needs a new low and a new level."));
        }

        [Test]
        public void SnapshotDescribesBothSides()
        {
            var s = LongSetup().Snapshot();
            Assert.That(s.Instrument, Is.EqualTo("MNQ 12-26"));
            Assert.That(s.Trend, Is.EqualTo(GateTrend.Up));
            Assert.That(s.NeedsTrendAnswer, Is.False);
            Assert.That(s.StatusLine, Is.EqualTo("Waiting for a new low."));

            Assert.That(s.Long.IsActive, Is.True);
            Assert.That(s.Long.Extreme, Is.EqualTo(100.0));
            Assert.That(s.Long.ExtremeMode, Is.EqualTo(ExtremeMode.Pinned));
            Assert.That(s.Long.Timeframes[0].Timeframe, Is.EqualTo(GateTimeframe.M1));
            Assert.That(s.Long.Timeframes[0].LevelPrice, Is.EqualTo(105.0));
            Assert.That(s.Long.Timeframes[0].State, Is.EqualTo(SetupState.WaitingForBreak));
            Assert.That(s.Long.Timeframes[1].LevelPrice, Is.Null);
            Assert.That(s.Long.Timeframes[1].State, Is.EqualTo(SetupState.NoLevel));

            Assert.That(s.Short.IsActive, Is.False);
            Assert.That(s.Short.Extreme, Is.Null);
            Assert.That(s.Short.ExtremeMode, Is.Null);
        }
    }
}
