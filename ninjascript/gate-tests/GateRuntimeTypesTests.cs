using System;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateRuntimeTypesTests
    {
        [SetUp]
        public void SetUp() => GateEntryNames.Clear();

        [Test]
        public void EntryNamesMatchTheLogger()
        {
            Assert.That(GateEntryNames.NameFor(EntryKind.Market), Is.EqualTo("GateMktNextOpen"));
            Assert.That(GateEntryNames.NameFor(EntryKind.Limit), Is.EqualTo("GateLmtNextOpen"));
        }

        [Test]
        public void RegisteredOrderResolvesToItsName()
        {
            GateEntryNames.Register("order-1", EntryKind.Limit);
            string name;
            Assert.That(GateEntryNames.TryResolve("order-1", out name), Is.True);
            Assert.That(name, Is.EqualTo("GateLmtNextOpen"));
        }

        [Test]
        public void CounterTrendEntriesCarryACtSuffix()
        {
            Assert.That(GateEntryNames.NameFor(EntryKind.Market, true), Is.EqualTo("GateMktNextOpenCT"));
            Assert.That(GateEntryNames.NameFor(EntryKind.Limit, true), Is.EqualTo("GateLmtNextOpenCT"));
            GateEntryNames.Register("order-ct", EntryKind.Market, true);
            string name;
            Assert.That(GateEntryNames.TryResolve("order-ct", out name), Is.True);
            Assert.That(name, Is.EqualTo("GateMktNextOpenCT"));
        }

        [Test]
        public void RecognisesGateNames()
        {
            Assert.That(GateEntryNames.IsGateName("GateMktNextOpen"), Is.True);
            Assert.That(GateEntryNames.IsGateName("GateLmtNextOpenCT"), Is.True);
            Assert.That(GateEntryNames.IsGateName("Entry"), Is.False);
            Assert.That(GateEntryNames.IsGateName(null), Is.False);
        }

        [Test]
        public void UnknownOrderDoesNotResolve()
        {
            string name;
            Assert.That(GateEntryNames.TryResolve("nope", out name), Is.False);
            Assert.That(GateEntryNames.TryResolve(null, out name), Is.False);
            Assert.That(name, Is.Null);
        }

        [Test]
        public void RegisterRejectsEmptyKey()
        {
            Assert.Throws<ArgumentException>(() => GateEntryNames.Register("", EntryKind.Market));
        }

        [Test]
        public void DescribesMarketArm()
        {
            var arm = new PendingArm(GateSide.Long, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1);
            Assert.That(arm.Describe(), Is.EqualTo("ARMED MKT · 4ptSL-20ptTP · 1 ct"));
        }

        [Test]
        public void DescribesCounterTrendArm()
        {
            var arm = new PendingArm(GateSide.Long, EntryKind.Market, 0, "4ptSL-20ptTP", "Sim101", 1, true);
            Assert.That(arm.CounterTrend, Is.True);
            Assert.That(arm.Describe(), Is.EqualTo("ARMED MKT · 4ptSL-20ptTP · 1 ct · counter-trend"));
        }

        [Test]
        public void DescribesLimitArm()
        {
            var arm = new PendingArm(GateSide.Short, EntryKind.Limit, 30880.25, "4ptSL-20ptTP", "Sim101", 2);
            Assert.That(arm.Describe(), Is.EqualTo("ARMED LMT @ 30880.25 · 4ptSL-20ptTP · 2 ct"));
        }

        [Test]
        public void CommandResults()
        {
            Assert.That(GateCommandResult.Done().Ok, Is.True);
            Assert.That(GateCommandResult.Done().Actions, Is.Empty);
            var rejected = GateCommandResult.Rejected("no");
            Assert.That(rejected.Ok, Is.False);
            Assert.That(rejected.Error, Is.EqualTo("no"));
            Assert.That(rejected.Actions, Is.Empty);
        }
    }
}
