using System;
using System.Collections.Generic;
using System.Globalization;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>
    /// Spec §§4–6 runtime model for one instrument contract. Holds closed bars per timeframe,
    /// derives every setup state from the trader's inputs (never stores it), owns the single arm,
    /// and turns each bar close or trader command into actions for the NinjaTrader shell. Pure:
    /// no clock, no IO, no NinjaTrader types.
    /// </summary>
    public sealed partial class InstrumentGate
    {
        private static readonly GateSide[] Sides = { GateSide.Long, GateSide.Short };
        private static readonly GateTimeframe[] Timeframes =
            { GateTimeframe.M1, GateTimeframe.M3, GateTimeframe.H1, GateTimeframe.H4 };

        private readonly Dictionary<GateTimeframe, List<GateBar>> bars = new Dictionary<GateTimeframe, List<GateBar>>();
        private readonly Dictionary<int, SetupState> lastStates = new Dictionary<int, SetupState>();
        private long latestHourEnd;
        private long promptedForHourEnd = -1;

        public InstrumentGate(string instrument, InstrumentInputs inputs)
        {
            Instrument = instrument;
            Inputs = inputs;
            foreach (var tf in Timeframes) bars[tf] = new List<GateBar>();
            Rebaseline();
        }

        public string Instrument { get; }
        public InstrumentInputs Inputs { get; }
        public TrendBook Trend { get; } = new TrendBook();
        public PendingArm Arm { get; private set; }

        /// <summary>Signed leader position for this instrument, kept current by the shell.</summary>
        public int LeaderPositionQty { get; set; }

        /// <summary>True while a gate entry order is working, kept current by the shell.</summary>
        public bool GateEntryWorking { get; set; }

        public long LatestHourEnd => latestHourEnd;
        public bool NeedsTrendAnswer => !Trend.IsConfirmed(latestHourEnd);

        /// <summary>True after a level or extreme changed; the shell saves state and calls MarkInputsSaved.</summary>
        public bool InputsChanged { get; private set; }

        public void MarkInputsSaved() => InputsChanged = false;

        public IReadOnlyList<GateBar> BarsFor(GateTimeframe tf) => bars[tf];

        public ExtremeTrack TrackExtreme(GateSide side) =>
            ExtremeTracker.Track(side, Inputs.For(side).ExtremeEdits, bars[GateTimeframe.M1]);

        public SetupEvaluation Evaluate(GateSide side, GateTimeframe tf)
        {
            LevelInput level;
            Inputs.For(side).Levels.TryGetValue(tf, out level);
            return SetupEngine.Evaluate(side, level, TrackExtreme(side), bars[tf]);
        }

        /// <summary>Startup or reconnect: append closed history without emitting any action.</summary>
        public void LoadHistory(GateTimeframe tf, IEnumerable<GateBar> history)
        {
            foreach (var bar in history) Append(tf, bar);
            if (tf == GateTimeframe.H1) promptedForHourEnd = Math.Max(promptedForHourEnd, latestHourEnd);
            Rebaseline();
        }

        public IReadOnlyList<GateAction> OnBarClosed(GateTimeframe tf, GateBar bar)
        {
            var actions = new List<GateAction>();
            if (!Append(tf, bar)) return actions;

            if (tf == GateTimeframe.H1 && !Trend.IsConfirmed(latestHourEnd) && promptedForHourEnd < latestHourEnd)
            {
                promptedForHourEnd = latestHourEnd;
                actions.Add(GateAction.Prompt());
            }

            // A 1m close can break the shared extreme, which moves every timeframe.
            var affected = tf == GateTimeframe.M1 ? Timeframes : new[] { tf };
            SetupEvaluation armedAfter = null;
            SetupState armedBefore = SetupState.NoLevel;
            foreach (var side in Sides)
            {
                foreach (var t in affected)
                {
                    var before = lastStates[Key(side, t)];
                    var after = Evaluate(side, t);
                    if (Arm != null && side == Arm.Side && t == GateTimeframe.M1)
                    {
                        armedBefore = before;
                        armedAfter = after;
                    }
                    if (after.State != before)
                    {
                        actions.Add(GateAction.LogEvent(GateEvents.Transition,
                            Describe(side, t) + ": " + before + " → " + after.State));
                    }
                    lastStates[Key(side, t)] = after.State;
                }
            }

            if (armedAfter != null)
            {
                switch (ArmRules.OnClose(armedBefore, armedAfter))
                {
                    case ArmAction.Fire:
                        actions.Add(GateAction.Fire(Arm));
                        Arm = null;
                        break;
                    case ArmAction.Cancel:
                        actions.Add(GateAction.CancelArmed(Arm,
                            "1m setup moved to " + armedAfter.State + " — re-arm to trade."));
                        Arm = null;
                        break;
                }
            }
            return actions;
        }

        public GateCommandResult ArmEntry(PendingArm arm)
        {
            if (arm == null) throw new ArgumentNullException(nameof(arm));
            if (arm.Quantity <= 0) return GateCommandResult.Rejected("Order quantity must be positive.");
            if (arm.Kind == EntryKind.Limit && !(arm.LimitPrice > 0)) return GateCommandResult.Rejected("Enter a limit price.");
            if (Arm != null) return GateCommandResult.Rejected("Already armed — disarm first.");

            string reason = ArmRules.CanArm(arm.Side, Trend.Trend, Trend.IsConfirmed(latestHourEnd),
                Evaluate(arm.Side, GateTimeframe.M1).State, LeaderPositionQty, GateEntryWorking);
            if (reason != null) return GateCommandResult.Rejected(reason);

            Arm = arm;
            return GateCommandResult.Done(new[] { GateAction.LogEvent(GateEvents.Arm, arm.Describe()) });
        }

        public GateCommandResult Disarm()
        {
            if (Arm == null) return GateCommandResult.Done();
            var arm = Arm;
            Arm = null;
            return GateCommandResult.Done(new[] { GateAction.LogEvent(GateEvents.Disarm, arm.Describe()) });
        }

        public GateCommandResult AnswerTrend(GateTrend trend)
        {
            if (trend == GateTrend.Unconfirmed) return GateCommandResult.Rejected("Choose Up or Down.");

            Trend.Answer(trend, latestHourEnd);
            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.TrendAnswer,
                    trend + " for the hour ending " + latestHourEnd.ToString(CultureInfo.InvariantCulture)),
            };
            if (Arm != null && SideMath.ActiveSide(trend) != Arm.Side)
            {
                actions.Add(GateAction.CancelArmed(Arm,
                    "Hourly trend is now " + trend + " — the " + Arm.Side + " arm was cancelled."));
                Arm = null;
            }
            return GateCommandResult.Done(actions);
        }

        public GateCommandResult SetLevel(GateSide side, GateTimeframe tf, double price, long now)
        {
            var inputs = Inputs.For(side);
            var track = TrackExtreme(side);
            if (track == null) return GateCommandResult.Rejected("Set the " + ExtremeWord(side) + " first.");
            if (!SetupEngine.IsValidLevel(side, price, track.Value))
            {
                return GateCommandResult.Rejected("A " + side.ToString().ToLowerInvariant() + " level must be "
                    + (side == GateSide.Long ? "above" : "below") + " the " + ExtremeWord(side)
                    + " (" + FormatPrice(track.Value) + ").");
            }

            LevelInput previous;
            inputs.Levels.TryGetValue(tf, out previous);
            SetupEvaluation previousEvaluation = previous == null
                ? null
                : SetupEngine.Evaluate(side, previous, track, bars[tf]);
            inputs.Levels[tf] = LevelInput.Replace(previous, previousEvaluation, price, now);
            InputsChanged = true;

            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.LevelSet, Describe(side, tf) + " level " + FormatPrice(price)),
            };
            if (Arm != null && Arm.Side == side && tf == GateTimeframe.M1)
            {
                actions.Add(GateAction.CancelArmed(Arm, "The 1m level changed — re-arm to trade."));
                Arm = null;
            }
            Rebaseline();
            return GateCommandResult.Done(actions);
        }

        public GateCommandResult SetExtreme(GateSide side, double price, long now)
        {
            var inputs = Inputs.For(side);
            foreach (var tf in Timeframes)
            {
                LevelInput level;
                if (inputs.Levels.TryGetValue(tf, out level) && !SetupEngine.IsValidLevel(side, level.Price, price))
                {
                    return GateCommandResult.Rejected("The " + ExtremeWord(side) + " must be "
                        + (side == GateSide.Long ? "below" : "above") + " every level ("
                        + Label(tf) + " level " + FormatPrice(level.Price) + ").");
                }
            }

            var last = inputs.Extreme;
            inputs.EditExtreme(new ExtremeInput(price, last != null && now < last.SetAt ? last.SetAt : now));
            InputsChanged = true;

            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.ExtremeSet, side + " " + ExtremeWord(side) + " " + FormatPrice(price)),
            };
            if (Arm != null && Arm.Side == side)
            {
                var state = Evaluate(side, GateTimeframe.M1).State;
                if (state != SetupState.OneClose && state != SetupState.Strike)
                {
                    actions.Add(GateAction.CancelArmed(Arm, "1m setup moved to " + state + " — re-arm to trade."));
                    Arm = null;
                }
            }
            Rebaseline();
            return GateCommandResult.Done(actions);
        }

        public static string Label(GateTimeframe tf)
        {
            switch (tf)
            {
                case GateTimeframe.M1: return "1m";
                case GateTimeframe.M3: return "3m";
                case GateTimeframe.H1: return "1h";
                default: return "4h";
            }
        }

        public static string ExtremeWord(GateSide side) => side == GateSide.Long ? "low" : "high";

        public static string FormatPrice(double price) => price.ToString("0.00##", CultureInfo.InvariantCulture);

        private bool Append(GateTimeframe tf, GateBar bar)
        {
            var list = bars[tf];
            if (list.Count > 0 && bar.EndTime <= list[list.Count - 1].EndTime) return false;
            list.Add(bar);
            if (tf == GateTimeframe.H1 && bar.EndTime > latestHourEnd) latestHourEnd = bar.EndTime;
            return true;
        }

        private void Rebaseline()
        {
            foreach (var side in Sides)
                foreach (var tf in Timeframes)
                    lastStates[Key(side, tf)] = Evaluate(side, tf).State;
        }

        private static int Key(GateSide side, GateTimeframe tf) => (int)side * 10 + (int)tf;

        private static string Describe(GateSide side, GateTimeframe tf) => side + " " + Label(tf);
    }
}
