using System.Collections.Generic;
using System.IO;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    /// Plan B2 final-review fixes: bracket sizing races, orphaned brackets, copier timing,
    /// unmatched account names and the gate-entry journal.
    public class GateReviewFixTests
    {
        private static readonly List<LeaderEntry> LeaderBuyAt1000 = new List<LeaderEntry>
        {
            new LeaderEntry("MNQ 12-26", true, 1000),
        };

        [Test]
        public void BracketLargerThanALaggingPositionIsAllowed()
        {
            // 2-lot entry filled 1+1; ATM grows Stop1 to 2 while the position still reads 1.
            Assert.That(OrderGate.Decide(new OrderIntent(false, 2, false, true, 1, true), 1).Allowed, Is.True);
            Assert.That(OrderGate.Decide(new OrderIntent(false, 2, false, false, 0, true), 1).Allowed, Is.True);
        }

        [Test]
        public void OrphanedBracketChangedWhileFlatIsCancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 1, false, true, 1, true), 0).Allowed, Is.False);
        }

        [Test]
        public void FollowerChangeOfACopiedOrderWhileFlatIsAllowed()
        {
            var limitDrag = new OrderIntent(true, 1, false, true, 1);
            Assert.That(FollowerGate.Decide(limitDrag, "MNQ 12-26", 0, new List<LeaderEntry>(), 5000, 5).Allowed, Is.True);
        }

        [Test]
        public void FollowerChangeThatGrowsWhileFlatIsCancelled()
        {
            var grow = new OrderIntent(true, 2, false, true, 1);
            Assert.That(FollowerGate.Decide(grow, "MNQ 12-26", 0, new List<LeaderEntry>(), 5000, 5).Allowed, Is.False);
        }

        [Test]
        public void FollowerCopiedEntryWithinTheWindowIsAllowed()
        {
            var entry = new OrderIntent(true, 1, false, false, 0);
            Assert.That(FollowerGate.Decide(entry, "MNQ 12-26", 0, LeaderBuyAt1000, 1003, 5).Allowed, Is.True);
            Assert.That(FollowerGate.Decide(entry, "MNQ 12-26", 0, LeaderBuyAt1000, 1010, 5).Allowed, Is.False);
        }

        [Test]
        public void FollowerProtectiveOrderRacingItsFillIsAllowed()
        {
            // Opposite direction to the leader entry, follower still reads flat.
            var stop = new OrderIntent(false, 1, false, false, 0);
            Assert.That(FollowerGate.Decide(stop, "MNQ 12-26", 0, LeaderBuyAt1000, 1002, 5).Allowed, Is.True);
            Assert.That(FollowerGate.Decide(stop, "MNQ 12-26", 0, new List<LeaderEntry>(), 1002, 5).Allowed, Is.False);
        }

        [Test]
        public void FollowerInAPositionUsesTheLeaderRules()
        {
            Assert.That(FollowerGate.Decide(new OrderIntent(false, 1, false, false, 0), "MNQ 12-26", 1,
                new List<LeaderEntry>(), 5000, 5).Allowed, Is.True);
            Assert.That(FollowerGate.Decide(new OrderIntent(true, 1, false, false, 0), "MNQ 12-26", 1,
                new List<LeaderEntry>(), 5000, 5).Allowed, Is.False);
        }

        [Test]
        public void UnmatchedAccountsAreReportedWithANearMatch()
        {
            var settings = new GateSettings(new[] { "apex-1", "Ghost", "Sim101" }, new[] { "APEX-9" }, 1, 5, 5);
            var problems = settings.UnmatchedAccounts(new[] { "APEX-1", "Sim101" });
            Assert.That(problems.Count, Is.EqualTo(3));
            Assert.That(problems[0], Does.Contain("apex-1").And.Contain("did you mean APEX-1"));
            Assert.That(problems[1], Does.Contain("Ghost"));
            Assert.That(problems[2], Does.Contain("Follower account APEX-9"));
        }

        [Test]
        public void JournalRoundTripsAndForgets()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gate-journal-" + Path.GetRandomFileName());
            string path = Path.Combine(dir, "gate_entries.txt");
            try
            {
                var journal = new GateEntryJournal();
                journal.Record("B123", "GateLmtNextOpenCT");
                journal.Record("B124", "GateMktNextOpen");
                journal.Forget("B124");
                GateEntryJournal.Save(path, journal);

                var loaded = GateEntryJournal.Load(path);
                string name;
                Assert.That(loaded.TryGet("B123", out name), Is.True);
                Assert.That(name, Is.EqualTo("GateLmtNextOpenCT"));
                Assert.That(loaded.TryGet("B124", out name), Is.False);
                Assert.That(loaded.Count, Is.EqualTo(1));
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }

        [Test]
        public void JournalLoadNeverThrows()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gate-journal-" + Path.GetRandomFileName());
            string path = Path.Combine(dir, "gate_entries.txt");
            try
            {
                Assert.That(GateEntryJournal.Load(path).Count, Is.EqualTo(0));
                Directory.CreateDirectory(dir);
                // Old journals stored the kind ("Market"/"Limit"); they still load as gate names.
                File.WriteAllText(path, "garbage\nB9|Sideways\nB10|Market\nB11|GateLmtNextOpenCT\n");
                var loaded = GateEntryJournal.Load(path);
                Assert.That(loaded.Count, Is.EqualTo(2));
                string name;
                Assert.That(loaded.TryGet("B10", out name), Is.True);
                Assert.That(name, Is.EqualTo("GateMktNextOpen"));
                Assert.That(loaded.TryGet("B11", out name), Is.True);
                Assert.That(name, Is.EqualTo("GateLmtNextOpenCT"));
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }

        [Test]
        public void JournalRejectsEmptyOrderIds()
        {
            var journal = new GateEntryJournal();
            journal.Record("", "GateMktNextOpen");
            journal.Record(null, "GateMktNextOpen");
            journal.Record("B1", "Entry");
            Assert.That(journal.Count, Is.EqualTo(0));
        }
    }
}
