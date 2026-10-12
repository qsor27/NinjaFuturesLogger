using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class SetupEvaluation
    {
        public SetupEvaluation(SetupState state, bool triggeredOnLastClose, long deadAt)
        {
            State = state;
            TriggeredOnLastClose = triggeredOnLastClose;
            DeadAt = deadAt;
        }

        public SetupState State { get; }

        /// <summary>The last close moved OneClose or Strike into Confirmed: an armed entry fires at the next open.</summary>
        public bool TriggeredOnLastClose { get; }

        /// <summary>EndTime of the close that killed the setup; 0 if not dead.</summary>
        public long DeadAt { get; }
    }

    /// <summary>
    /// Spec §4. State is derived by replaying closed bars against one timeframe's level; it is
    /// never stored. Only closes move the machine; breaks of the shared extreme come from the
    /// 1m ExtremeTrack and only move WaitingForBreak to Broken.
    /// </summary>
    public static class SetupEngine
    {
        private static readonly long[] NoBreaks = new long[0];

        public static SetupEvaluation Evaluate(GateSide side, LevelInput level, ExtremeTrack extreme, IList<GateBar> bars)
        {
            if (level == null) return new SetupEvaluation(SetupState.NoLevel, false, 0);

            IReadOnlyList<long> breaks = extreme != null ? extreme.BreakTimes : NoBreaks;

            var state = SetupState.WaitingForBreak;
            int next = 0;
            while (next < breaks.Count && breaks[next] <= level.SetAt)
            {
                if (breaks[next] > level.RequireBreakAfter) state = SetupState.Broken;
                next++;
            }

            bool triggered = false;
            long deadAt = 0;
            foreach (var bar in bars)
            {
                if (bar.EndTime <= level.SetAt) continue;

                while (next < breaks.Count && breaks[next] <= bar.EndTime)
                {
                    if (state == SetupState.WaitingForBreak) state = SetupState.Broken;
                    next++;
                }

                var after = Step(state, SideMath.IsRegained(side, bar.Close, level.Price));
                triggered = after == SetupState.Confirmed
                    && (state == SetupState.OneClose || state == SetupState.Strike);
                if (after == SetupState.Dead && state != SetupState.Dead) deadAt = bar.EndTime;
                state = after;
            }

            if (next < breaks.Count && state == SetupState.WaitingForBreak) state = SetupState.Broken;

            return new SetupEvaluation(state, triggered, deadAt);
        }

        public static SetupState Step(SetupState state, bool regained)
        {
            switch (state)
            {
                case SetupState.Broken: return regained ? SetupState.OneClose : SetupState.Broken;
                case SetupState.OneClose: return regained ? SetupState.Confirmed : SetupState.Reset;
                case SetupState.Reset: return regained ? SetupState.OneClose : SetupState.Dead;
                case SetupState.Confirmed: return regained ? SetupState.Confirmed : SetupState.Strike;
                case SetupState.Strike: return regained ? SetupState.Confirmed : SetupState.Dead;
                default: return state; // NoLevel, WaitingForBreak and Dead ignore closes.
            }
        }

        /// <summary>A Long level must sit above the low; a Short level below the high.</summary>
        public static bool IsValidLevel(GateSide side, double levelPrice, double extremeValue) =>
            side == GateSide.Long ? levelPrice > extremeValue : levelPrice < extremeValue;
    }
}
