using System.IO;
using System.Linq;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class RemoveLevelTests
    {
        private static GateBar M1(long end, double low, double high, double close) =>
            new GateBar(end - 60, end, close, high, low, close);

        private static InstrumentGate LongSetup()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            g.SetExtreme(GateSide.Long, 100.0, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.M1, 105.0, 0);
            g.SetLevel(GateSide.Long, GateTimeframe.H1, 107.0, 0);
            g.AnswerTrend(GateTrend.Up, g.LatestHourEnd);
            g.MarkInputsSaved();
            return g;
        }

        [Test]
        public void RemovesALevel()
        {
            var g = LongSetup();
            var r = g.RemoveLevel(GateSide.Long, GateTimeframe.H1, 50);
            Assert.That(r.Ok, Is.True);
            Assert.That(g.Inputs.Long.Levels.ContainsKey(GateTimeframe.H1), Is.False);
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.H1).State, Is.EqualTo(SetupState.NoLevel));
            Assert.That(g.InputsChanged, Is.True);
            Assert.That(r.Actions.Single().Event, Is.EqualTo(GateEvents.LevelRemoved));
        }

        [Test]
        public void RemovingAMissingLevelIsRejected()
        {
            Assert.That(LongSetup().RemoveLevel(GateSide.Long, GateTimeframe.M3, 50).Error, Does.Contain("no 3m level"));
        }

        [Test]
        public void RemovingADeadLevelKeepsItsNewLowRequirement()
        {
            var g = LongSetup();
            g.OnBarClosed(GateTimeframe.M1, M1(60, 99, 104, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(120, 103, 106, 106));
            g.OnBarClosed(GateTimeframe.M1, M1(180, 103, 106, 104));
            g.OnBarClosed(GateTimeframe.M1, M1(240, 103, 106, 104));
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.Dead));

            g.RemoveLevel(GateSide.Long, GateTimeframe.M1, 250);
            g.SetLevel(GateSide.Long, GateTimeframe.M1, 106, 300);
            Assert.That(g.Inputs.Long.Levels[GateTimeframe.M1].RequireBreakAfter, Is.EqualTo(240));
            Assert.That(g.Evaluate(GateSide.Long, GateTimeframe.M1).State, Is.EqualTo(SetupState.WaitingForBreak));
        }

        [Test]
        public void RemovingTheArmedOneMinuteLevelCancelsTheArm()
        {
            var g = LongSetup();
            g.ArmEntry(new PendingArm(GateSide.Long, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1));
            var r = g.RemoveLevel(GateSide.Long, GateTimeframe.M1, 50);
            Assert.That(r.Actions.Any(a => a.Kind == GateActionKind.CancelArm), Is.True);
            Assert.That(g.Arm, Is.Null);
        }

        [Test]
        public void RemovingTheExtremeClearsTheSide()
        {
            var g = LongSetup();
            g.ArmEntry(new PendingArm(GateSide.Long, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1));
            var r = g.RemoveExtreme(GateSide.Long, 50);
            Assert.That(r.Ok, Is.True);
            Assert.That(g.Inputs.Long.Extreme, Is.Null);
            Assert.That(g.Inputs.Long.Levels, Is.Empty);
            Assert.That(g.Arm, Is.Null);
            Assert.That(g.SetLevel(GateSide.Long, GateTimeframe.M1, 105, 60).Error, Does.Contain("Set the low first"));
        }

        [Test]
        public void RemovingAMissingExtremeIsRejected()
        {
            var g = new InstrumentGate("MNQ 12-26", new InstrumentInputs());
            Assert.That(g.RemoveExtreme(GateSide.Short, 0).Error, Does.Contain("no high"));
        }

        [Test]
        public void RemovedRequirementsArePersisted()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gate-remove-" + Path.GetRandomFileName());
            string path = Path.Combine(dir, "setup_gate_state.txt");
            try
            {
                var state = new GateStateFile();
                state.GetOrAdd("MNQ 12-26").Long.RemovedRequirements[GateTimeframe.M1] = 240;
                GateStateStore.Save(path, state);
                var loaded = GateStateStore.Load(path).State;
                Assert.That(loaded.Instruments["MNQ 12-26"].Long.RemovedRequirements[GateTimeframe.M1], Is.EqualTo(240));
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }
    }
}
