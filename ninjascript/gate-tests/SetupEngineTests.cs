using System.Collections.Generic;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class SetupEngineTests
    {
        // Long fixture: low 100 entered at t=0, level 105.
        private static GateBar Bar(long end, double low, double high, double close) =>
            new GateBar(end - 60, end, close, high, low, close);

        private static SetupEvaluation RunLong(LevelInput level, params GateBar[] bars)
        {
            var list = new List<GateBar>(bars);
            var track = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), list);
            return SetupEngine.Evaluate(GateSide.Long, level, track, list);
        }

        private static LevelInput Level(long setAt = 0, long requireBreakAfter = 0) =>
            new LevelInput(105.0, setAt, requireBreakAfter);

        private static readonly GateBar Break60 = Bar(60, 99, 104, 104); // new low, closes below level

        [Test]
        public void NoLevel_WhenLevelMissing()
        {
            Assert.That(RunLong(null, Break60).State, Is.EqualTo(SetupState.NoLevel));
        }

        [Test]
        public void WaitsForBreak_ClosesAboveDoNothingYet()
        {
            var e = RunLong(Level(), Bar(60, 101, 107, 106), Bar(120, 101, 107, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.WaitingForBreak));
            Assert.That(e.TriggeredOnLastClose, Is.False);
        }

        [Test]
        public void BreakThenTwoClosesAbove_Confirms()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107));
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.True);
        }

        [Test]
        public void OneCloseAbove_IsOneClose()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
            Assert.That(e.TriggeredOnLastClose, Is.False);
        }

        [Test]
        public void SweepAndReclaimInSameBar_IsOneClose()
        {
            var e = RunLong(Level(), Bar(60, 99, 106, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
        }

        [Test]
        public void CloseExactlyAtLevel_IsNotARegain()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 105.5, 105.0));
            Assert.That(e.State, Is.EqualTo(SetupState.Broken));
        }

        [Test]
        public void ClosesBelowBeforeFirstRegain_NeverKill()
        {
            var e = RunLong(Level(), Break60, Bar(120, 101, 104, 103), Bar(180, 101, 104, 103));
            Assert.That(e.State, Is.EqualTo(SetupState.Broken));
        }

        [Test]
        public void CBC_DoesNotConfirm()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104), Bar(240, 103, 107, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
            Assert.That(e.TriggeredOnLastClose, Is.False);
        }

        [Test]
        public void CBCC_Confirms()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104),
                Bar(240, 103, 107, 106), Bar(300, 105, 108, 107));
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.True);
        }

        [Test]
        public void CB_IsReset()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104));
            Assert.That(e.State, Is.EqualTo(SetupState.Reset));
        }

        [Test]
        public void CBB_IsDead()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104), Bar(240, 103, 106, 104));
            Assert.That(e.State, Is.EqualTo(SetupState.Dead));
            Assert.That(e.DeadAt, Is.EqualTo(240));
        }

        [Test]
        public void ConfirmedThenClose_StaysConfirmedWithoutNewTrigger()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107), Bar(240, 106, 109, 108));
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.False);
        }

        [Test]
        public void ConfirmedThenBelow_IsStrike()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107), Bar(240, 103, 107, 104));
            Assert.That(e.State, Is.EqualTo(SetupState.Strike));
        }

        [Test]
        public void StrikeThenAbove_Retriggers()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107),
                Bar(240, 103, 107, 104), Bar(300, 103, 107, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.True);
        }

        [Test]
        public void StrikeThenBelow_IsDead()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107),
                Bar(240, 103, 107, 104), Bar(300, 103, 107, 104));
            Assert.That(e.State, Is.EqualTo(SetupState.Dead));
            Assert.That(e.DeadAt, Is.EqualTo(300));
        }

        [Test]
        public void DeadIgnoresLaterClosesAndNewLows()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104), Bar(240, 103, 106, 104),
                Bar(300, 97, 104, 98), Bar(360, 98, 107, 106), Bar(420, 105, 108, 107));
            Assert.That(e.State, Is.EqualTo(SetupState.Dead));
        }

        [Test]
        public void BreakBeforeLevelWasSet_StartsBroken()
        {
            var e = RunLong(Level(setAt: 100), Break60);
            Assert.That(e.State, Is.EqualTo(SetupState.Broken));
        }

        [Test]
        public void LevelSetMidBar_CountsThatBarsClose()
        {
            var e = RunLong(Level(setAt: 90), Break60, Bar(120, 103, 106, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
        }

        [Test]
        public void ReplacementLevel_IgnoresBreaksBeforeTheDeath()
        {
            // The previous level died at t=200; a break at t=60 no longer counts.
            var e = RunLong(Level(setAt: 300, requireBreakAfter: 200), Break60);
            Assert.That(e.State, Is.EqualTo(SetupState.WaitingForBreak));
        }

        [Test]
        public void ReplacementLevel_NewLowAfterDeath_Breaks()
        {
            var e = RunLong(Level(setAt: 300, requireBreakAfter: 200), Break60, Bar(360, 98, 104, 104));
            Assert.That(e.State, Is.EqualTo(SetupState.Broken));
        }

        [Test]
        public void HigherTimeframe_UsesOneMinuteBreaks()
        {
            var oneMinute = new List<GateBar> { Bar(1800, 99, 101, 100) };
            var track = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), oneMinute);
            var hourly = new List<GateBar> { new GateBar(0, 3600, 102, 107, 99, 106) };
            var e = SetupEngine.Evaluate(GateSide.Long, Level(), track, hourly);
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
        }

        [Test]
        public void Short_MirrorsLong()
        {
            var bars = new List<GateBar> { Bar(60, 194, 201, 194), Bar(120, 192, 196, 193) };
            var track = ExtremeTracker.Track(GateSide.Short, new ExtremeInput(200.0, 0), bars);
            var e = SetupEngine.Evaluate(GateSide.Short, new LevelInput(195.0, 0, 0), track, bars);
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.True);
        }

        [Test]
        public void EditingTheLowNeverRevivesADeadLevel()
        {
            var bars = new List<GateBar> { Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104), Bar(240, 103, 106, 104),
                Bar(360, 96, 104, 104), Bar(420, 103, 107, 106), Bar(480, 105, 108, 107) };
            var edits = new List<ExtremeInput> { new ExtremeInput(100.0, 0), new ExtremeInput(97.0, 290) };
            var track = ExtremeTracker.Track(GateSide.Long, edits, bars);
            var e = SetupEngine.Evaluate(GateSide.Long, Level(), track, bars);
            Assert.That(e.State, Is.EqualTo(SetupState.Dead));
            Assert.That(e.DeadAt, Is.EqualTo(240));
        }

        [Test]
        public void EditingTheLowKeepsALiveSetup()
        {
            var bars = new List<GateBar> { Break60, Bar(120, 103, 106, 106), Bar(180, 105, 108, 107) };
            var edits = new List<ExtremeInput> { new ExtremeInput(100.0, 0), new ExtremeInput(98.0, 150) };
            var track = ExtremeTracker.Track(GateSide.Long, edits, bars);
            var e = SetupEngine.Evaluate(GateSide.Long, Level(), track, bars);
            Assert.That(e.State, Is.EqualTo(SetupState.Confirmed));
            Assert.That(e.TriggeredOnLastClose, Is.True);
        }

        [Test]
        public void DuplicateBarIsCountedOnce()
        {
            var e = RunLong(Level(), Break60, Bar(120, 103, 106, 106), Bar(120, 103, 106, 106));
            Assert.That(e.State, Is.EqualTo(SetupState.OneClose));
            Assert.That(e.TriggeredOnLastClose, Is.False);
        }

        [Test]
        public void ReplacingAReplacementLevelKeepsTheDeathRequirement()
        {
            var bars = new List<GateBar> { Break60, Bar(120, 103, 106, 106), Bar(180, 103, 106, 104), Bar(240, 103, 106, 104),
                Bar(390, 103, 107, 106), Bar(450, 104, 108, 107) };
            var track = ExtremeTracker.Track(GateSide.Long, new ExtremeInput(100.0, 0), bars);
            var l1 = Level();
            var e1 = SetupEngine.Evaluate(GateSide.Long, l1, track, bars);
            Assert.That(e1.DeadAt, Is.EqualTo(240));

            var l2 = LevelInput.Replace(l1, e1, 106.0, 300);
            Assert.That(l2.RequireBreakAfter, Is.EqualTo(240));
            var e2 = SetupEngine.Evaluate(GateSide.Long, l2, track, bars);

            var l3 = LevelInput.Replace(l2, e2, 105.5, 330);
            Assert.That(l3.RequireBreakAfter, Is.EqualTo(240));
            Assert.That(SetupEngine.Evaluate(GateSide.Long, l3, track, bars).State, Is.EqualTo(SetupState.WaitingForBreak));
        }

        [Test]
        public void ReplacingADeadLevelWithoutReplayData_RequiresBreakAfterNow()
        {
            var l2 = LevelInput.Replace(Level(), new SetupEvaluation(SetupState.Dead, false, 0), 106.0, 500);
            Assert.That(l2.RequireBreakAfter, Is.EqualTo(500));
            Assert.That(l2.SetAt, Is.EqualTo(500));
            Assert.That(l2.Price, Is.EqualTo(106.0));
        }

        [Test]
        public void ReplacingALiveLevelKeepsItsRequirement()
        {
            var l2 = LevelInput.Replace(new LevelInput(105.0, 0, 77), new SetupEvaluation(SetupState.Broken, false, 0), 106.0, 300);
            Assert.That(l2.RequireBreakAfter, Is.EqualTo(77));
            Assert.That(LevelInput.Replace(null, null, 106.0, 300).RequireBreakAfter, Is.EqualTo(0));
        }

        [Test]
        public void IsValidLevel_LongAboveExtreme_ShortBelow()
        {
            Assert.That(SetupEngine.IsValidLevel(GateSide.Long, 105, 100), Is.True);
            Assert.That(SetupEngine.IsValidLevel(GateSide.Long, 100, 100), Is.False);
            Assert.That(SetupEngine.IsValidLevel(GateSide.Short, 195, 200), Is.True);
            Assert.That(SetupEngine.IsValidLevel(GateSide.Short, 201, 200), Is.False);
        }
    }
}
