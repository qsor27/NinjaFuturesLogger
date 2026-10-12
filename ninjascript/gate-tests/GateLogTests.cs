using System;
using System.IO;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateLogTests
    {
        [Test]
        public void Escape_QuotesOnlyWhenNeeded()
        {
            Assert.That(GateLog.Escape("plain"), Is.EqualTo("plain"));
            Assert.That(GateLog.Escape(null), Is.EqualTo(""));
            Assert.That(GateLog.Escape("a,b"), Is.EqualTo("\"a,b\""));
            Assert.That(GateLog.Escape("say \"hi\""), Is.EqualTo("\"say \"\"hi\"\"\""));
            Assert.That(GateLog.Escape("two\nlines"), Is.EqualTo("\"two\nlines\""));
        }

        [Test]
        public void FormatRow_IsoUtcAndEscapedFields()
        {
            var row = GateLog.FormatRow(new DateTime(2026, 10, 12, 14, 30, 5, DateTimeKind.Utc),
                "MNQ 12-26", "APEX1", GateEvents.Cancel, "Adding to a position isn't allowed, sorry");
            Assert.That(row, Is.EqualTo(
                "2026-10-12T14:30:05Z,MNQ 12-26,APEX1,Cancel,\"Adding to a position isn't allowed, sorry\""));
        }

        [Test]
        public void Append_WritesHeaderOnceThenRows()
        {
            string dir = Path.Combine(Path.GetTempPath(), "gate-log-" + Path.GetRandomFileName());
            string path = Path.Combine(dir, "gate_log.csv");
            try
            {
                GateLog.Append(path, "r1");
                GateLog.Append(path, "r2");
                var lines = File.ReadAllLines(path);
                Assert.That(lines, Is.EqualTo(new[] { GateLog.Header, "r1", "r2" }));
            }
            finally
            {
                if (Directory.Exists(dir)) Directory.Delete(dir, true);
            }
        }
    }
}
