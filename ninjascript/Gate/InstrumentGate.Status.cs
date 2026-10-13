using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed partial class InstrumentGate
    {
        public GateSnapshot Snapshot() =>
            new GateSnapshot(Instrument, Trend.Trend, NeedsTrendAnswer, Arm, StatusLine(),
                SideSnapshotFor(GateSide.Long), SideSnapshotFor(GateSide.Short));

        /// <summary>Spec §9: why an entry is or isn't possible right now, in plain English.</summary>
        public string StatusLine()
        {
            if (!OneMinuteFeedHealthy) return "1m data is down — entries are blocked.";
            if (Arm != null)
            {
                return Arm.Describe() + " — fires at the open after the second close."
                    + (NeedsTrendAnswer ? " Confirm the hourly trend to arm again." : "");
            }
            if (NeedsTrendAnswer) return "Confirm the hourly trend first.";
            if (GateEntryWorking) return "Gate entry working — cancel it to re-arm.";
            if (LeaderPositionQty != 0) return "In a position — exits only.";

            var side = SideMath.ActiveSide(Trend.Trend) ?? GateSide.Long;
            string sideWord = side.ToString().ToLowerInvariant();
            switch (Evaluate(side, GateTimeframe.M1).State)
            {
                case SetupState.NoLevel:
                    return "Set the " + sideWord + " 1m level.";
                case SetupState.WaitingForBreak:
                    return "Waiting for a new " + ExtremeWord(side) + ". You can arm now.";
                case SetupState.Broken:
                case SetupState.Reset:
                    return "Waiting for a 1m close back " + (side == GateSide.Long ? "above" : "below") + " the level. You can arm now.";
                case SetupState.OneClose:
                case SetupState.Strike:
                    return "Ready to arm " + sideWord + ".";
                case SetupState.Confirmed:
                    return "Confirmed without an arm — an arm now fires only after a close back past the level and a regain.";
                default:
                    return "1m setup is dead — needs a new " + ExtremeWord(side) + " and a new level.";
            }
        }

        private SideSnapshot SideSnapshotFor(GateSide side)
        {
            var track = TrackExtreme(side);
            var timeframes = new List<TimeframeSnapshot>();
            foreach (var tf in Timeframes)
            {
                LevelInput level;
                Inputs.For(side).Levels.TryGetValue(tf, out level);
                var state = SetupEngine.Evaluate(side, level, track, bars[tf]).State;
                timeframes.Add(new TimeframeSnapshot(tf, level != null ? level.Price : (double?)null, state));
            }
            bool active = SideMath.ActiveSide(Trend.Trend) == side;
            return new SideSnapshot(side, active,
                track != null ? track.Value : (double?)null,
                track != null ? track.Mode : (ExtremeMode?)null,
                timeframes);
        }
    }
}
