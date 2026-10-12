using System.Collections.Generic;
using System.IO;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateSettingsTests
    {
        [Test]
        public void DefaultsGateNothing()
        {
            var s = GateSettings.Defaults();
            Assert.That(s.GatedAccounts, Is.Empty);
            Assert.That(s.FollowerAccounts, Is.Empty);
            Assert.That(s.BreakEvenTicks, Is.EqualTo(1));
            Assert.That(s.FollowerWindowSeconds, Is.EqualTo(5));
            Assert.That(s.HistoryDays, Is.EqualTo(5));
        }

        [Test]
        public void ParsesEveryKey()
        {
            var problems = new List<string>();
            var s = GateSettings.Parse(
                "# comment\nGatedAccounts=APEX1, Sim101\nFollowerAccounts=APEX2,APEX3\nBreakEvenTicks=2\nFollowerWindowSeconds=8\nHistoryDays=3\n",
                problems);
            Assert.That(problems, Is.Empty);
            Assert.That(s.GatedAccounts, Is.EqualTo(new[] { "APEX1", "Sim101" }));
            Assert.That(s.FollowerAccounts, Is.EqualTo(new[] { "APEX2", "APEX3" }));
            Assert.That(s.BreakEvenTicks, Is.EqualTo(2));
            Assert.That(s.FollowerWindowSeconds, Is.EqualTo(8));
            Assert.That(s.HistoryDays, Is.EqualTo(3));
        }

        [Test]
        public void BadNumbersFallBackAndAreReported()
        {
            var problems = new List<string>();
            var s = GateSettings.Parse("BreakEvenTicks=lots\nHistoryDays=0\n", problems);
            Assert.That(s.BreakEvenTicks, Is.EqualTo(1));
            Assert.That(s.HistoryDays, Is.EqualTo(5));
            Assert.That(problems.Count, Is.EqualTo(2));
            Assert.That(problems[0], Does.Contain("BreakEvenTicks"));
        }

        [Test]
        public void UnknownKeysAndJunkLinesAreReported()
        {
            var problems = new List<string>();
            GateSettings.Parse("Colour=red\njunk\n", problems);
            Assert.That(problems.Count, Is.EqualTo(2));
            Assert.That(problems[0], Does.Contain("Colour"));
        }

        [Test]
        public void AccountsAreTrimmedAndDeduplicated()
        {
            var s = GateSettings.Parse("GatedAccounts= APEX1 ,,APEX1, \n", new List<string>());
            Assert.That(s.GatedAccounts, Is.EqualTo(new[] { "APEX1" }));
            Assert.That(s.IsGated("APEX1"), Is.True);
            Assert.That(s.IsGated("apex1"), Is.False);
            Assert.That(s.IsGated(null), Is.False);
            Assert.That(s.IsFollower("APEX1"), Is.False);
        }

        [Test]
        public void SerializeRoundTrips()
        {
            var original = new GateSettings(new[] { "APEX1" }, new[] { "APEX2" }, 3, 7, 4);
            var problems = new List<string>();
            var copy = GateSettings.Parse(original.Serialize(), problems);
            Assert.That(problems, Is.Empty);
            Assert.That(copy.GatedAccounts, Is.EqualTo(original.GatedAccounts));
            Assert.That(copy.FollowerAccounts, Is.EqualTo(original.FollowerAccounts));
            Assert.That(copy.BreakEvenTicks, Is.EqualTo(3));
            Assert.That(copy.FollowerWindowSeconds, Is.EqualTo(7));
            Assert.That(copy.HistoryDays, Is.EqualTo(4));
        }

        [Test]
        public void LoadOrCreateWritesATemplateWhenMissing()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gate-settings-" + Path.GetRandomFileName());
            string path = Path.Combine(dir, "setup_gate_settings.txt");
            try
            {
                var problems = new List<string>();
                var s = GateSettings.LoadOrCreate(path, problems);
                Assert.That(File.Exists(path), Is.True);
                Assert.That(s.GatedAccounts, Is.Empty);
                Assert.That(problems.Count, Is.EqualTo(1));
                Assert.That(problems[0], Does.Contain("Created"));

                File.WriteAllText(path, "GatedAccounts=Sim101\n");
                Assert.That(GateSettings.LoadOrCreate(path, new List<string>()).IsGated("Sim101"), Is.True);
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }
    }
}
