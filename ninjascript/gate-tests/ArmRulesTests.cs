using System;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class ArmRulesTests
    {
        private static string Can(GateSide side = GateSide.Long, GateTrend trend = GateTrend.Up,
            bool confirmed = true, SetupState state = SetupState.OneClose, int pos = 0, bool working = false) =>
            ArmRules.CanArm(side, trend, confirmed, state, pos, working);

        [Test]
        public void AllowsArmAtOneCloseOrStrike()
        {
            Assert.That(Can(), Is.Null);
            Assert.That(Can(state: SetupState.Strike), Is.Null);
            Assert.That(Can(side: GateSide.Short, trend: GateTrend.Down), Is.Null);
        }

        [Test]
        public void RejectsUnconfirmedTrend()
        {
            Assert.That(Can(trend: GateTrend.Unconfirmed), Does.Contain("hourly trend"));
            Assert.That(Can(confirmed: false), Does.Contain("hourly trend"));
        }

        [Test]
        public void RejectsCounterTrendSide()
        {
            Assert.That(Can(side: GateSide.Short, trend: GateTrend.Up), Does.Contain("trend"));
        }

        [TestCase(SetupState.WaitingForBreak)]
        [TestCase(SetupState.Broken)]
        [TestCase(SetupState.Reset)]
        [TestCase(SetupState.Confirmed)]
        public void AllowsArmingAnyTimeALevelIsSet(SetupState state)
        {
            Assert.That(Can(state: state), Is.Null);
        }

        [Test]
        public void RejectsWithoutALevelOrOnADeadSetup()
        {
            Assert.That(Can(state: SetupState.NoLevel), Does.Contain("1m level"));
            Assert.That(Can(state: SetupState.Dead), Does.Contain("dead"));
        }

        [Test]
        public void RejectsWhenInPositionOrEntryWorking()
        {
            Assert.That(Can(pos: 1), Does.Contain("position"));
            Assert.That(Can(pos: -2), Does.Contain("position"));
            Assert.That(Can(working: true), Does.Contain("working"));
        }

        [Test]
        public void OnClose_TriggerFires()
        {
            var after = new SetupEvaluation(SetupState.Confirmed, true, 0);
            Assert.That(ArmRules.OnClose(SetupState.OneClose, after), Is.EqualTo(ArmAction.Fire));
            Assert.That(ArmRules.OnClose(SetupState.Strike, after), Is.EqualTo(ArmAction.Fire));
        }

        [Test]
        public void OnClose_KeepsWaitingThroughTheSetup()
        {
            Assert.That(ArmRules.OnClose(SetupState.WaitingForBreak, new SetupEvaluation(SetupState.Broken, false, 0)),
                Is.EqualTo(ArmAction.Keep));
            Assert.That(ArmRules.OnClose(SetupState.Broken, new SetupEvaluation(SetupState.OneClose, false, 0)),
                Is.EqualTo(ArmAction.Keep));
            Assert.That(ArmRules.OnClose(SetupState.OneClose, new SetupEvaluation(SetupState.Reset, false, 0)),
                Is.EqualTo(ArmAction.Keep));
            Assert.That(ArmRules.OnClose(SetupState.Confirmed, new SetupEvaluation(SetupState.Strike, false, 0)),
                Is.EqualTo(ArmAction.Keep));
        }

        [Test]
        public void OnClose_DeathCancels()
        {
            Assert.That(ArmRules.OnClose(SetupState.Reset, new SetupEvaluation(SetupState.Dead, false, 60)),
                Is.EqualTo(ArmAction.Cancel));
            Assert.That(ArmRules.OnClose(SetupState.Strike, new SetupEvaluation(SetupState.Dead, false, 60)),
                Is.EqualTo(ArmAction.Cancel));
        }

        [Test]
        public void OnClose_NoChangeKeeps()
        {
            Assert.That(ArmRules.OnClose(SetupState.Confirmed, new SetupEvaluation(SetupState.Confirmed, false, 0)),
                Is.EqualTo(ArmAction.Keep));
        }

        [Test]
        public void TrendBook_StartsUnconfirmed()
        {
            var book = new TrendBook();
            Assert.That(book.Trend, Is.EqualTo(GateTrend.Unconfirmed));
            Assert.That(book.IsConfirmed(3600), Is.False);
        }

        [Test]
        public void TrendBook_AnswerCoversOnlyThatHour()
        {
            var book = new TrendBook();
            book.Answer(GateTrend.Up, 3600);
            Assert.That(book.IsConfirmed(3600), Is.True);
            Assert.That(book.IsConfirmed(7200), Is.False);
            Assert.That(book.Trend, Is.EqualTo(GateTrend.Up));
        }

        [Test]
        public void TrendBook_RejectsUnconfirmedAnswer()
        {
            Assert.Throws<ArgumentException>(() => new TrendBook().Answer(GateTrend.Unconfirmed, 3600));
        }
    }
}
