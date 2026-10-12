using System.Globalization;
using System.IO;
using System.Threading;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateStateStoreTests
    {
        private string dir;
        private string path;

        [SetUp]
        public void SetUp()
        {
            dir = Path.Combine(Path.GetTempPath(), "gate-state-" + Path.GetRandomFileName());
            Directory.CreateDirectory(dir);
            path = Path.Combine(dir, "setup_gate_state.txt");
        }

        [TearDown]
        public void TearDown()
        {
            foreach (var f in Directory.GetFiles(dir, "*", SearchOption.AllDirectories))
                File.SetAttributes(f, FileAttributes.Normal);
            Directory.Delete(dir, true);
        }

        private static GateStateFile Sample()
        {
            var s = new GateStateFile();
            var mnq = s.GetOrAdd("MNQ 12-26");
            mnq.Long.EditExtreme(new ExtremeInput(30868.75, 1760000000));
            mnq.Long.Levels[GateTimeframe.M1] = new LevelInput(30888.5, 1760000060, 0);
            mnq.Long.Levels[GateTimeframe.H1] = new LevelInput(30905.0, 1760000120, 1759990000);
            mnq.Short.Levels[GateTimeframe.H4] = new LevelInput(31000.25, 1760000180, 0);
            s.GetOrAdd("MES 12-26").Short.EditExtreme(new ExtremeInput(6800.5, 1760000200));
            return s;
        }

        [Test]
        public void RoundTrips()
        {
            GateStateStore.Save(path, Sample());
            var load = GateStateStore.Load(path);

            Assert.That(load.WasCorrupt, Is.False);
            var mnq = load.State.Instruments["MNQ 12-26"];
            Assert.That(mnq.Long.Extreme.Price, Is.EqualTo(30868.75));
            Assert.That(mnq.Long.Extreme.SetAt, Is.EqualTo(1760000000));
            Assert.That(mnq.Long.Levels[GateTimeframe.H1].RequireBreakAfter, Is.EqualTo(1759990000));
            Assert.That(mnq.Long.Levels[GateTimeframe.M1].Price, Is.EqualTo(30888.5));
            Assert.That(mnq.Short.Levels[GateTimeframe.H4].Price, Is.EqualTo(31000.25));
            Assert.That(mnq.Short.Extreme, Is.Null);
            Assert.That(load.State.Instruments["MES 12-26"].Short.Extreme.Price, Is.EqualTo(6800.5));
        }

        [Test]
        public void RoundTripsUnderCommaDecimalCulture()
        {
            var saved = Thread.CurrentThread.CurrentCulture;
            Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
            try
            {
                GateStateStore.Save(path, Sample());
                var load = GateStateStore.Load(path);
                Assert.That(load.State.Instruments["MNQ 12-26"].Long.Extreme.Price, Is.EqualTo(30868.75));
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = saved;
            }
        }

        [Test]
        public void ExtremeEditHistoryRoundTrips()
        {
            var s = new GateStateFile();
            s.GetOrAdd("MNQ 12-26").Long.EditExtreme(new ExtremeInput(100.0, 10));
            s.GetOrAdd("MNQ 12-26").Long.EditExtreme(new ExtremeInput(97.25, 20));
            GateStateStore.Save(path, s);

            var edits = GateStateStore.Load(path).State.Instruments["MNQ 12-26"].Long.ExtremeEdits;
            Assert.That(edits.Count, Is.EqualTo(2));
            Assert.That(edits[0].Price, Is.EqualTo(100.0));
            Assert.That(edits[1].Price, Is.EqualTo(97.25));
        }

        [Test]
        public void EditExtreme_RejectsEditsOlderThanTheLast()
        {
            var side = new SideInputs();
            side.EditExtreme(new ExtremeInput(100.0, 20));
            Assert.Throws<System.ArgumentException>(() => side.EditExtreme(new ExtremeInput(99.0, 10)));
            Assert.That(side.Extreme.Price, Is.EqualTo(100.0));
        }

        [Test]
        public void LockedFile_ReportsFailureWithoutThrowing()
        {
            GateStateStore.Save(path, Sample());
            using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                var load = GateStateStore.Load(path);
                Assert.That(load.Error, Is.Not.Null);
                Assert.That(load.State.Instruments, Is.Empty);
            }
        }

        [Test]
        public void CorruptWithReadOnlyBackup_FallsBackToTimestampedBackup()
        {
            File.WriteAllText(path + ".bad", "old");
            File.SetAttributes(path + ".bad", FileAttributes.ReadOnly);
            File.WriteAllText(path, "garbage");

            var load = GateStateStore.Load(path);
            Assert.That(load.WasCorrupt, Is.True);
            Assert.That(load.BackupPath, Is.Not.Null);
            Assert.That(load.BackupPath, Is.Not.EqualTo(path + ".bad"));
            Assert.That(File.ReadAllText(load.BackupPath), Is.EqualTo("garbage"));
        }

        [Test]
        public void MissingFile_IsEmptyAndNotCorrupt()
        {
            var load = GateStateStore.Load(path);
            Assert.That(load.WasCorrupt, Is.False);
            Assert.That(load.State.Instruments, Is.Empty);
        }

        [Test]
        public void CorruptFile_BackedUpAndEmpty()
        {
            File.WriteAllText(path, "# NinjaFuturesLogger setup-gate state v1\nL|MNQ 12-26|Long|M1|not-a-number|1|0\n");
            var load = GateStateStore.Load(path);

            Assert.That(load.WasCorrupt, Is.True);
            Assert.That(load.State.Instruments, Is.Empty);
            Assert.That(File.Exists(path), Is.False);
            Assert.That(File.Exists(path + ".bad"), Is.True);
            Assert.That(load.BackupPath, Is.EqualTo(path + ".bad"));
        }

        [Test]
        public void SecondCorruption_ReplacesOldBackup()
        {
            File.WriteAllText(path + ".bad", "old");
            File.WriteAllText(path, "garbage");
            var load = GateStateStore.Load(path);
            Assert.That(load.WasCorrupt, Is.True);
            Assert.That(File.ReadAllText(path + ".bad"), Is.EqualTo("garbage"));
        }

        [Test]
        public void SaveOverwritesAndLeavesNoTempFile()
        {
            GateStateStore.Save(path, Sample());
            var smaller = new GateStateFile();
            smaller.GetOrAdd("MNQ 12-26").Long.EditExtreme(new ExtremeInput(1.25, 5));
            GateStateStore.Save(path, smaller);

            var load = GateStateStore.Load(path);
            Assert.That(load.State.Instruments.Count, Is.EqualTo(1));
            Assert.That(load.State.Instruments["MNQ 12-26"].Long.Extreme.Price, Is.EqualTo(1.25));
            Assert.That(File.Exists(path + ".tmp"), Is.False);
        }

        [Test]
        public void SaveCreatesMissingDirectory()
        {
            string nested = Path.Combine(dir, "a", "b", "state.txt");
            GateStateStore.Save(nested, Sample());
            Assert.That(File.Exists(nested), Is.True);
        }
    }
}
