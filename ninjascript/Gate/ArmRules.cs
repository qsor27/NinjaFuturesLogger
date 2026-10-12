using System;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public enum ArmAction { Keep, Fire, Cancel }

    /// <summary>Spec §6: when an entry may be armed, and what each 1m close does to an arm.</summary>
    public static class ArmRules
    {
        /// <summary>Null when arming is allowed; otherwise the reason shown in the panel.</summary>
        public static string CanArm(GateSide side, GateTrend trend, bool trendConfirmedThisHour,
            SetupState oneMinuteState, int leaderPositionQty, bool gateEntryWorking)
        {
            if (trend == GateTrend.Unconfirmed || !trendConfirmedThisHour)
                return "Confirm the hourly trend first.";
            if (SideMath.ActiveSide(trend) != side)
                return "Only the side of the hourly trend can be armed.";
            if (oneMinuteState != SetupState.OneClose && oneMinuteState != SetupState.Strike)
                return "Arming opens after the first 1m close back past the level.";
            if (leaderPositionQty != 0)
                return "Already in a position — adding isn't allowed.";
            if (gateEntryWorking)
                return "A gate entry order is already working.";
            return null;
        }

        /// <summary>Applied after every 1m close while an arm exists.</summary>
        public static ArmAction OnClose(SetupState before, SetupEvaluation after)
        {
            if (after.TriggeredOnLastClose) return ArmAction.Fire;
            if (after.State != before) return ArmAction.Cancel;
            return ArmAction.Keep;
        }
    }

    /// <summary>Spec §5: the trader's hourly trend, valid only for the latest closed hour.</summary>
    public sealed class TrendBook
    {
        public GateTrend Trend { get; private set; } = GateTrend.Unconfirmed;

        /// <summary>EndTime of the 60-minute bar the last answer covered.</summary>
        public long ConfirmedForHourEnd { get; private set; }

        public void Answer(GateTrend trend, long latestHourBarEnd)
        {
            if (trend == GateTrend.Unconfirmed)
                throw new ArgumentException("An hourly answer must be Up or Down.", nameof(trend));
            Trend = trend;
            ConfirmedForHourEnd = latestHourBarEnd;
        }

        public bool IsConfirmed(long latestHourBarEnd) =>
            Trend != GateTrend.Unconfirmed && ConfirmedForHourEnd >= latestHourBarEnd;
    }
}
