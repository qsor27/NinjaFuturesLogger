using System;
using System.Collections.Generic;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    public class GateShellHelpersTests
    {
        private static readonly TimeZoneInfo Central = TimeZoneInfo.FindSystemTimeZoneById("Central Standard Time");

        [Test]
        public void ConvertsCentralTimeToUnixSeconds()
        {
            // 09:30 CDT (UTC-5) on 2026-10-12 and 09:30 CST (UTC-6) on 2026-12-14.
            long summer = GateTime.ToUnixSeconds(new DateTime(2026, 10, 12, 9, 30, 0), Central);
            long winter = GateTime.ToUnixSeconds(new DateTime(2026, 12, 14, 9, 30, 0), Central);
            Assert.That(summer, Is.EqualTo(new DateTimeOffset(2026, 10, 12, 14, 30, 0, TimeSpan.Zero).ToUnixTimeSeconds()));
            Assert.That(winter, Is.EqualTo(new DateTimeOffset(2026, 12, 14, 15, 30, 0, TimeSpan.Zero).ToUnixTimeSeconds()));
        }

        [Test]
        public void UtcTimesConvertDirectly()
        {
            var utc = new DateTime(2026, 10, 12, 14, 30, 0, DateTimeKind.Utc);
            Assert.That(GateTime.ToUnixSeconds(utc, Central),
                Is.EqualTo(new DateTimeOffset(utc).ToUnixTimeSeconds()));
        }

        [Test]
        public void FromUnixSecondsIsTheInverse()
        {
            var local = new DateTime(2026, 10, 12, 9, 30, 0);
            Assert.That(GateTime.FromUnixSeconds(GateTime.ToUnixSeconds(local, Central), Central), Is.EqualTo(local));
        }

        [Test]
        public void BarFromCloseUsesThePeriodForStartTime()
        {
            var bar = GateTime.BarFromClose(new DateTime(2026, 10, 12, 10, 0, 0), 60, 1, 4, 0.5, 3, Central);
            Assert.That(bar.EndTime - bar.StartTime, Is.EqualTo(3600));
            Assert.That(bar.High, Is.EqualTo(4));
            Assert.That(bar.Low, Is.EqualTo(0.5));
            Assert.That(bar.Close, Is.EqualTo(3));
        }

        [Test]
        public void MinutesOfEachTimeframe()
        {
            Assert.That(GateTime.MinutesOf(GateTimeframe.M1), Is.EqualTo(1));
            Assert.That(GateTime.MinutesOf(GateTimeframe.M3), Is.EqualTo(3));
            Assert.That(GateTime.MinutesOf(GateTimeframe.H1), Is.EqualTo(60));
            Assert.That(GateTime.MinutesOf(GateTimeframe.H4), Is.EqualTo(240));
        }

        [Test]
        public void ClosedBarCursor_NeverDeliversTheFormingBar()
        {
            var cursor = new ClosedBarCursor();
            Assert.That(cursor.Advance(1), Is.Empty);
            Assert.That(cursor.Advance(4), Is.EqualTo(new[] { 0, 1, 2 }));
            Assert.That(cursor.LastDelivered, Is.EqualTo(2));
        }

        [Test]
        public void ClosedBarCursor_DeliversEachClosedBarOnce()
        {
            var cursor = new ClosedBarCursor();
            cursor.Advance(4);
            Assert.That(cursor.Advance(4), Is.Empty);
            Assert.That(cursor.Advance(5), Is.EqualTo(new[] { 3 }));
        }

        [Test]
        public void ClosedBarCursor_ResetStartsOver()
        {
            var cursor = new ClosedBarCursor();
            cursor.Advance(4);
            cursor.Reset();
            Assert.That(cursor.LastDelivered, Is.EqualTo(-1));
            Assert.That(cursor.Advance(3), Is.EqualTo(new[] { 0, 1 }));
        }

        [Test]
        public void Tracker_FirstLiveUpdateIsASubmit()
        {
            var t = new OrderIntentTracker();
            var intent = t.Observe(1, OrderPhase.Live, true, 2, false, false);
            Assert.That(intent.IsChange, Is.False);
            Assert.That(intent.Quantity, Is.EqualTo(2));
            Assert.That(intent.IsBuy, Is.True);
        }

        [Test]
        public void Tracker_LaterLiveUpdatesAreNotRejudged()
        {
            var t = new OrderIntentTracker();
            t.Observe(1, OrderPhase.Live, true, 2, false, false);
            Assert.That(t.Observe(1, OrderPhase.Live, true, 2, false, false), Is.Null);
        }

        [Test]
        public void Tracker_ChangeCarriesThePreviousQuantity()
        {
            var t = new OrderIntentTracker();
            t.Observe(1, OrderPhase.Live, false, 2, false, true);
            var change = t.Observe(1, OrderPhase.Changing, false, 1, false, true);
            Assert.That(change.IsChange, Is.True);
            Assert.That(change.PreviousQuantity, Is.EqualTo(2));
            Assert.That(change.Quantity, Is.EqualTo(1));
            Assert.That(change.IsAtmBracket, Is.True);
        }

        [Test]
        public void Tracker_UnseenChangeIsJudgedAsASubmit()
        {
            var t = new OrderIntentTracker();
            Assert.That(t.Observe(7, OrderPhase.Changing, true, 1, false, false).IsChange, Is.False);
        }

        [Test]
        public void Tracker_DoneForgetsTheOrder_IgnoreReturnsNull()
        {
            var t = new OrderIntentTracker();
            t.Observe(1, OrderPhase.Live, true, 2, false, false);
            Assert.That(t.Observe(1, OrderPhase.Ignore, true, 2, false, false), Is.Null);
            Assert.That(t.Observe(1, OrderPhase.Done, true, 2, false, false), Is.Null);
            Assert.That(t.Observe(1, OrderPhase.Live, true, 2, false, false), Is.Not.Null);
        }

        [Test]
        public void RecognisesAtmBracketNames()
        {
            Assert.That(OrderIntentTracker.IsAtmBracket("Stop1"), Is.True);
            Assert.That(OrderIntentTracker.IsAtmBracket("Target2"), Is.True);
            Assert.That(OrderIntentTracker.IsAtmBracket("Entry"), Is.False);
            Assert.That(OrderIntentTracker.IsAtmBracket("Stop"), Is.False);
            Assert.That(OrderIntentTracker.IsAtmBracket(null), Is.False);
        }

        [Test]
        public void LeaderEntryLog_KeepsOnlyTheWindow()
        {
            var log = new LeaderEntryLog();
            log.Add(new LeaderEntry("MNQ 12-26", true, 100));
            log.Add(new LeaderEntry("MNQ 12-26", true, 103));
            var recent = log.Recent(106, 5);
            Assert.That(recent.Count, Is.EqualTo(1));
            Assert.That(recent[0].Time, Is.EqualTo(103));
        }

        [Test]
        public void AtmBracketAllowedWhileFlat()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 1, false, false, 0, true), 0).Allowed, Is.True);
        }

        [Test]
        public void AtmBracketThatAddsIsStillCancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(true, 1, false, false, 0, true), 2).Allowed, Is.False);
        }

        [Test]
        public void ManualOrderWhileFlatCancelled()
        {
            Assert.That(OrderGate.Decide(new OrderIntent(false, 1, false, false, 0, false), 0).Allowed, Is.False);
        }
    }
}
