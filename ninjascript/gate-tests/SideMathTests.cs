using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class SideMathTests
    {
        private static GateBar Bar(double low, double high) => new GateBar(0, 60, low, high, low, high);

        [Test]
        public void Long_BeyondMeansBelow()
        {
            Assert.That(SideMath.IsBeyond(GateSide.Long, 99.75, 100.0), Is.True);
            Assert.That(SideMath.IsBeyond(GateSide.Long, 100.0, 100.0), Is.False);
        }

        [Test]
        public void Short_BeyondMeansAbove()
        {
            Assert.That(SideMath.IsBeyond(GateSide.Short, 100.25, 100.0), Is.True);
            Assert.That(SideMath.IsBeyond(GateSide.Short, 100.0, 100.0), Is.False);
        }

        [Test]
        public void Long_RegainedMeansCloseStrictlyAbove()
        {
            Assert.That(SideMath.IsRegained(GateSide.Long, 105.25, 105.0), Is.True);
            Assert.That(SideMath.IsRegained(GateSide.Long, 105.0, 105.0), Is.False);
        }

        [Test]
        public void Short_RegainedMeansCloseStrictlyBelow()
        {
            Assert.That(SideMath.IsRegained(GateSide.Short, 94.75, 95.0), Is.True);
            Assert.That(SideMath.IsRegained(GateSide.Short, 95.0, 95.0), Is.False);
        }

        [Test]
        public void ExtremeOf_UsesLowForLongAndHighForShort()
        {
            Assert.That(SideMath.ExtremeOf(GateSide.Long, Bar(99, 101)), Is.EqualTo(99));
            Assert.That(SideMath.ExtremeOf(GateSide.Short, Bar(99, 101)), Is.EqualTo(101));
        }

        [Test]
        public void ActiveSide_FollowsTrend()
        {
            Assert.That(SideMath.ActiveSide(GateTrend.Up), Is.EqualTo(GateSide.Long));
            Assert.That(SideMath.ActiveSide(GateTrend.Down), Is.EqualTo(GateSide.Short));
            Assert.That(SideMath.ActiveSide(GateTrend.Unconfirmed), Is.Null);
        }
    }
}
