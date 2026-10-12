using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class InstrumentGateTests
    {
        private static GateBar M1(long end, double low, double high, double close) =>
            new GateBar(end - 60, end, close, high, low, close);

        private static GateBar H1(long end) => new GateBar(end - 3600, end, 100, 101, 99, 100);

        private static PendingArm MarketArm(GateSide side = GateSide.Long) =>
            new PendingArm(side, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1);

        private static bool Has(IReadOnlyList<GateAction> actions, GateActionKind kind) =>
            actions.Any(a => a.Kind == kind);

        /// Low 100, 1m level 105, trend Up confirmed (for hour 0).
        private static InstrumentGate LongSetup()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            Assert.That(g.SetExtreme(GateSide.Long, 100.0, 0).Ok, Is.True);
            Assert.That(g.SetLevel(GateSide.Long, GateTimeframe.M1, 105.0, 0).Ok, Is.True);
            Assert.That(g.AnswerTrend(GateTrend.Up).Ok, Is.True);
            return g;
        }

        /// LongSetup, then a new low at 60 and one close above at 120 (1m = OneClose).
        private static InstrumentGate LongAtOneClose()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.OneClose));
            return g;
        }

        [Test]
        public void SetLevelRequiresAnExtreme()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            var r = g.SetLevel(GateSide.Long, GateTimeframe.M1, 105, 0);
            Assert.That(r.Error, Does.Contain("Set the low first"));
        }

        [Test]
        public void SetLevelRejectsALongLevelBelowTheLow()
        {
            var g = LongSetup();
            var r = g.SetLevel(GateSide.Long, GateTimeframe.M1, 99.75, 10);
            Assert.That(r.Error, Does.Contain("above the low (100.00)"));
            Assert.That(g.InputsChanged, Is.True);
        }

        [Test]
        public void SetExtremeRejectsALowAboveALevel()
        {
            var g = LongSetup();
            var r = g.SetExtreme(GateSide.Long, 106, 5);
            Assert.That(r.Error, Does.Contain("below every level"));
            Assert.That(r.Error, Does.Contain("1m level 105.00"));
        }

        [Test]
        public void ArmFiresOnTheSecondClose()
        {
            var g = LongAtOneClose();
            Assert.That(g.ArmEntry(MarketArm()).Ok, Is.True);

            var actions = g.OnBarClosed(GateTimeframe.M1, M1(180, 105, 108, 107));
            var fire = actions.Single(a => a.Kind == GateActionKind.FireEntry);
            Assert.That(fire.Arm.Kind, Is.EqualTo(EntryKind.Market));
            Assert.That(g.Arm, Is.Null);
        }

        [Test]
        public void CloseBackBelowCancelsTheArm()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var actions = g.OnBarClosed(GateTimeframe.M1, M1(180, 103, 106, 104));
            var cancel = actions.Single(a => a.Kind == GateActionKind.CancelArm);
            Assert.That(cancel.Detail, Does.Contain("Reset"));
            Assert.That(g.Arm, Is.Null);
        }

        [Test]
        public void ArmRejectedBeforeTheFirstClose()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            Assert.That(g.ArmEntry(MarketArm()).Error, Does.Contain("Arming opens after"));
        }

        [Test]
        public void ArmRejectedWithoutAConfirmedTrend()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            g.SetExtreme(GateSide.Long, 100, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.M1, 105, 0);
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            Assert.That(g.ArmEntry(MarketArm()).Error, Does.Contain("hourly trend"));
        }

        [Test]
        public void ArmRejectedAgainstTheTrend()
        {
            var g = LongAtOneClose();
            Assert.That(g.ArmEntry(MarketArm(GateSide.Short)).Error, Does.Contain("side of the hourly trend"));
        }

        [Test]
        public void ArmRejectedWhileInAPosition()
        {
            var g = LongAtOneClose();
            g.LeaderPositionQty = 1;
            Assert.That(g.ArmEntry(MarketArm()).Error, Does.Contain("position"));
        }

        [Test]
        public void ArmRejectedWhenAlreadyArmed()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            Assert.That(g.ArmEntry(MarketArm()).Error, Does.Contain("Already armed"));
        }

        [Test]
        public void LimitArmNeedsAPrice()
        {
            var g = LongAtOneClose();
            var arm = new PendingArm(GateSide.Long, EntryKind.Limit, 0, "4ptSL-20ptTP", "Sim101", 1);
            Assert.That(g.ArmEntry(arm).Error, Does.Contain("limit price"));
        }

        [Test]
        public void DisarmClearsTheArmAndLogs()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var r = g.Disarm();
            Assert.That(g.Arm, Is.Null);
            Assert.That(r.Actions.Single().Event, Is.EqualTo(GateEvents.Disarm));
        }

        [Test]
        public void AnsweringTheOppositeTrendCancelsTheArm()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var r = g.AnswerTrend(GateTrend.Down);
            Assert.That(Has(r.Actions, GateActionKind.CancelArm), Is.True);
            Assert.That(g.Arm, Is.Null);
        }

        [Test]
        public void AnsweringTheSameTrendKeepsTheArm()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var r = g.AnswerTrend(GateTrend.Up);
            Assert.That(Has(r.Actions, GateActionKind.CancelArm), Is.False);
            Assert.That(g.Arm, Is.Not.Null);
        }

        [Test]
        public void ArmSurvivesAnUnansweredNewHourAndFires()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(3480, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(3540, 103, 106, 106));
            Assert.That(g.ArmEntry(MarketArm()).Ok, Is.True);

            var hour = g.OnBarClosed(GateTimeframe.H1, H1(3600));
            Assert.That(Has(hour, GateActionKind.PromptTrend), Is.True);
            Assert.That(g.NeedsTrendAnswer, Is.True);

            var close = g.OnBarClosed(GateTimeframe.M1, M1(3660, 105, 108, 107));
            Assert.That(Has(close, GateActionKind.FireEntry), Is.True);
        }

        [Test]
        public void PromptsOncePerUnansweredHour()
        {
            var g = LongSetup();
            Assert.That(Has(g.OnBarClosed(GateTimeframe.H1, H1(3600)), GateActionKind.PromptTrend), Is.True);
            Assert.That(g.OnBarClosed(GateTimeframe.H1, H1(3600)), Is.Empty);
            Assert.That(Has(g.OnBarClosed(GateTimeframe.H1, H1(7200)), GateActionKind.PromptTrend), Is.True);

            g.AnswerTrend(GateTrend.Up);
            Assert.That(g.NeedsTrendAnswer, Is.False);
            Assert.That(Has(g.OnBarClosed(GateTimeframe.H1, H1(10800)), GateActionKind.PromptTrend), Is.True);
        }

        [Test]
        public void TransitionsAreLogged()
        {
            var g = LongSetup();
            var actions = g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            var log = actions.Single(a => a.Kind == GateActionKind.Log);
            Assert.That(log.Event, Is.EqualTo(GateEvents.Transition));
            Assert.That(log.Detail, Is.EqualTo("Long 1m: WaitingForBreak → Broken"));
        }

        [Test]
        public void OneMinuteBreakMovesHigherTimeframes()
        {
            var g = LongSetup();
            g.SetLevel(GateSide.Long, GateTimeframe.H1, 105, 0);
            var actions = g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            Assert.That(actions.Any(a => a.Detail == "Long 1h: WaitingForBreak → Broken"), Is.True);
        }

        [Test]
        public void DuplicateBarProducesNoActions()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            Assert.That(g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104)), Is.Empty);
            Assert.That(g.OnBarClosed(GateTimeframe.M1, M1(30, 90, 104, 104)), Is.Empty);
            Assert.That(g.BarsFor(GateTimeframe.M1).Count, Is.EqualTo(1));
        }

        [Test]
        public void LoadHistoryEmitsNothingAndBaselines()
        {
            var g = LongSetup();
            g.LoadHistory(GateTimeframe.M1, new[] { M1(60, 99, 104, 104), M1(120, 103, 106, 106) });
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.OneClose));

            var actions = g.OnBarClosed(GateTimeframe.M1, M1(180, 105, 108, 107));
            Assert.That(actions.Single(a => a.Kind == GateActionKind.Log).Detail, Is.EqualTo("Long 1m: OneClose → Confirmed"));
        }

        [Test]
        public void ChangingTheArmedOneMinuteLevelCancelsTheArm()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var r = g.SetLevel(GateSide.Long, GateTimeframe.M1, 105.5, 200);
            Assert.That(Has(r.Actions, GateActionKind.CancelArm), Is.True);
            Assert.That(g.Arm, Is.Null);
        }

        [Test]
        public void EditingTheExtremeKeepsAnArmableArm()
        {
            var g = LongAtOneClose();
            g.ArmEntry(MarketArm());
            var r = g.SetExtreme(GateSide.Long, 99.5, 200);
            Assert.That(r.Ok, Is.True);
            Assert.That(Has(r.Actions, GateActionKind.CancelArm), Is.False);
            Assert.That(g.Arm, Is.Not.Null);
        }

        [Test]
        public void ReplacingADeadLevelNeedsANewLow()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            g.OnBarClosed(GateTimeframe.M1, M1(180, 103, 106, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(240, 103, 106, 104));
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.Dead));

            g.SetLevel(GateSide.Long, GateTimeframe.M1, 106, 300);
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.WaitingForBreak));

            g.OnBarClosed(GateTimeframe.M1, M1(360, 98, 104, 104));
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.Broken));
        }

        [Test]
        public void AnswerTrendRejectsUnconfirmed()
        {
            var g = LongSetup();
            Assert.That(g.AnswerTrend(GateTrend.Unconfirmed).Error, Does.Contain("Up or Down"));
        }
    }
}
