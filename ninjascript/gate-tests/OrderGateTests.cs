using System.Collections.Generic;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class OrderGateTests
    {
        private static OrderIntent Manual(bool isBuy, int qty) => new OrderIntent(isBuy, qty, false, false, 0);

        [Test]
        public void Flat_ManualEntryCancelled()
        {
            var d = OrderGate.Decide(Manual(true, 1), 0);
            Assert.That(d.Allowed, Is.False);
            Assert.That(d.Reason, Does.Contain("armed setup"));
        }

        [Test]
        public void Flat_GateEntryAllowed()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(true, 2, true, false, 0), 0).Allowed, Is.True);
        }

        [Test]
        public void GateEntry_WhileInPosition_Cancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(true, 1, true, false, 0), 1).Allowed, Is.False);
        }

        [Test]
        public void GateEntry_PriceChangeAllowed_SizeChangeCancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(true, 2, true, true, 2), 0).Allowed, Is.True);
            var d = OrderGate.Decide(new OrderIntent(true, 3, true, true, 2), 0);
            Assert.That(d.Allowed, Is.False);
            Assert.That(d.Reason, Does.Contain("size"));
        }

        [Test]
        public void Long_BuyIsAddingAndCancelled()
        {
            var d = OrderGate.Decide(Manual(true, 1), 2);
            Assert.That(d.Allowed, Is.False);
            Assert.That(d.Reason, Does.Contain("Adding"));
        }

        [TestCase(1)]
        [TestCase(2)]
        public void Long_SellUpToPositionAllowed(int qty)
        {
            Assert.That(OrderGate.Decide(Manual(false, qty), 2).Allowed, Is.True);
        }

        [Test]
        public void Long_SellBeyondPositionIsReversalAndCancelled()
        {
            var d = OrderGate.Decide(Manual(false, 3), 2);
            Assert.That(d.Allowed, Is.False);
            Assert.That(d.Reason, Does.Contain("revers"));
        }

        [Test]
        public void Short_BuyToCoverAllowed_SellCancelled_OversizeCancelled()
        {
            Assert.That(OrderGate.Decide(Manual(true, 2), -2).Allowed, Is.True);
            Assert.That(OrderGate.Decide(Manual(false, 1), -2).Allowed, Is.False);
            Assert.That(OrderGate.Decide(Manual(true, 3), -2).Allowed, Is.False);
        }

        [Test]
        public void ExitChange_SizeAboveFilledPosition_Cancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 3, false, true, 2), 2).Allowed, Is.False);
            Assert.That(OrderGate.Decide(new OrderIntent(false, 2, false, true, 2), 2).Allowed, Is.True);
        }

        [Test]
        public void ExitPriceChange_AllowedEvenWhenPositionSnapshotIsSmaller()
        {
            // A 2-lot stop after a partial fill or a 1-lot manual reduce: dragging it must never cancel it.
            Assert.That(OrderGate.Decide(new OrderIntent(false, 2, false, true, 2), 1).Allowed, Is.True);
            Assert.That(OrderGate.Decide(new OrderIntent(true, 2, false, true, 2), -1).Allowed, Is.True);
        }

        [Test]
        public void ExitSizeReduction_Allowed()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 1, false, true, 3), 1).Allowed, Is.True);
        }

        [Test]
        public void ChangeInAddingDirection_Cancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(true, 1, false, true, 1), 2).Allowed, Is.False);
        }

        [Test]
        public void ChangeWhileFlat_Cancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 1, false, true, 1), 0).Allowed, Is.False);
        }

        [Test]
        public void NonPositiveQuantity_Cancelled()
        {
            Assert.That(OrderGate.Decide(Manual(false, 0), 2).Allowed, Is.False);
        }

        private static readonly List<LeaderEntry> Leader = new List<LeaderEntry>
        {
            new LeaderEntry("MNQ 12-26", true, 1000),
        };

        [Test]
        public void Follower_EntryMatchingLeaderWithinWindow_Allowed()
        {
            Assert.That(FollowerGate.Decide("MNQ 12-26", true, 1, 0, Leader, 1003, 5).Allowed, Is.True);
        }

        [Test]
        public void Follower_EntryOutsideWindowOrMismatched_Cancelled()
        {
            Assert.That(FollowerGate.Decide("MNQ 12-26", true, 1, 0, Leader, 1010, 5).Allowed, Is.False);
            Assert.That(FollowerGate.Decide("MNQ 12-26", false, 1, 0, Leader, 1001, 5).Allowed, Is.False);
            Assert.That(FollowerGate.Decide("MES 12-26", true, 1, 0, Leader, 1001, 5).Allowed, Is.False);
        }

        [Test]
        public void Follower_ExitsFollowReduceOnlyRule()
        {
            Assert.That(FollowerGate.Decide("MNQ 12-26", false, 1, 1, new List<LeaderEntry>(), 5000, 5).Allowed, Is.True);
            Assert.That(FollowerGate.Decide("MNQ 12-26", true, 1, 1, Leader, 1001, 5).Allowed, Is.False);
            Assert.That(FollowerGate.Decide("MNQ 12-26", false, 2, 1, new List<LeaderEntry>(), 5000, 5).Allowed, Is.False);
        }
    }
}
