using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>
    /// Spec §§4–6 runtime model for one instrument contract. Holds closed bars per timeframe,
    /// derives every setup state from the trader's inputs (never stores it), owns the single arm,
    /// and turns each bar close or trader command into actions for the NinjaTrader shell. Pure:
    /// no clock, no IO, no NinjaTrader types. Not thread-safe: the shell must serialize every call
    /// (bar updates, order events and UI commands arrive on different NinjaTrader threads).
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

        /// <summary>False while the shell's 1m feed is disconnected or reloading.</summary>
        public bool OneMinuteFeedHealthy { get; private set; } = true;

        public GateCommandResult SetOneMinuteFeed(bool healthy)
        {
            OneMinuteFeedHealthy = healthy;
            if (healthy || Arm == null) return GateCommandResult.Done();
            var arm = Arm;
            Arm = null;
            return GateCommandResult.Done(new[] { GateAction.CancelArmed(arm, "1m data is down — the arm was cancelled.") });
        }
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

        /// <summary>
        /// Startup or reconnect: append closed history (any order) without transition logs. Filling
        /// in 1m bars while armed cancels the arm — the fire/cancel decision for those closes was
        /// never made live (spec §11, fail closed). Prompts for the trend if the latest hour is
        /// unanswered and hasn't been prompted yet.
        /// </summary>
        public IReadOnlyList<GateAction> LoadHistory(GateTimeframe tf, IEnumerable<GateBar> history)
        {
            var actions = new List<GateAction>();
            int appended = 0;
            foreach (var bar in history.OrderBy(b => b.EndTime))
            {
                if (Append(tf, bar)) appended++;
            }
            if (tf == GateTimeframe.M1 && appended > 0 && Arm != null)
            {
                actions.Add(GateAction.CancelArmed(Arm, "1m bars were filled in after a data gap — re-arm to trade."));
                Arm = null;
            }
            Rebaseline();
            AddPromptIfNeeded(actions);
            return actions;
        }

        public IReadOnlyList<GateAction> OnBarClosed(GateTimeframe tf, GateBar bar)
        {
            var actions = new List<GateAction>();
            var oneMinute = bars[GateTimeframe.M1];
            long previousOneMinuteEnd = tf == GateTimeframe.M1 && oneMinute.Count > 0
                ? oneMinute[oneMinute.Count - 1].EndTime
                : long.MinValue;
            if (!Append(tf, bar)) return actions;

            // A 1m bar that starts after the previous close means closes are missing (dropped feed,
            // session break, weekend): never fire on that, cancel instead (spec §11, fail closed).
            bool oneMinuteGap = previousOneMinuteEnd != long.MinValue && bar.StartTime > previousOneMinuteEnd;

            if (tf == GateTimeframe.H1) AddPromptIfNeeded(actions);

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

            if (armedAfter != null && oneMinuteGap)
            {
                actions.Add(GateAction.CancelArmed(Arm, "1m bars are missing before this close — re-arm to trade."));
                Arm = null;
            }
            else if (armedAfter != null)
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
            if (!OneMinuteFeedHealthy) return GateCommandResult.Rejected("1m data is down — entries are blocked.");

            string reason = ArmRules.CanArm(arm.Side, Trend.Trend, Trend.IsConfirmed(latestHourEnd),
                Evaluate(arm.Side, GateTimeframe.M1).State, LeaderPositionQty, GateEntryWorking, arm.CounterTrend);
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

        public GateCommandResult AnswerTrend(GateTrend trend, long forHourEnd)
        {
            if (trend == GateTrend.Unconfirmed) return GateCommandResult.Rejected("Choose Up or Down.");
            if (forHourEnd != latestHourEnd)
                return GateCommandResult.Rejected("A new hour closed — answer for the latest hour.");
            if (Trend.IsConfirmed(latestHourEnd) && Trend.Trend != trend)
            {
                return GateCommandResult.Rejected("This hour is already " + Trend.Trend
                    + " — the trend can change at the next hourly close.");
            }

            Trend.Answer(trend, latestHourEnd);
            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.TrendAnswer,
                    trend + " for the hour ending " + latestHourEnd.ToString(CultureInfo.InvariantCulture)),
            };
            // A with-trend arm that the new answer makes counter-trend is cancelled (re-arming asks
            // for confirmation); an arm already confirmed as counter-trend stays.
            if (Arm != null && SideMath.ActiveSide(trend) != Arm.Side && !Arm.CounterTrend)
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
            long removedRequirement;
            if (previous == null && inputs.RemovedRequirements.TryGetValue(tf, out removedRequirement))
                previous = new LevelInput(price, now, removedRequirement); // carries a removed level's requirement
            inputs.Levels[tf] = LevelInput.Replace(previous, previousEvaluation, price, now);
            inputs.RemovedRequirements.Remove(tf);
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

        /// <summary>
        /// Deletes one timeframe's level. Its "new extreme after death" requirement is kept for the
        /// next level on that timeframe. Removing the armed side's 1m level cancels the arm.
        /// </summary>
        public GateCommandResult RemoveLevel(GateSide side, GateTimeframe tf, long now)
        {
            var inputs = Inputs.For(side);
            LevelInput level;
            if (!inputs.Levels.TryGetValue(tf, out level))
                return GateCommandResult.Rejected("There's no " + Label(tf) + " level to remove.");

            var evaluation = SetupEngine.Evaluate(side, level, TrackExtreme(side), bars[tf]);
            long requirement = level.RequireBreakAfter;
            if (evaluation.State == SetupState.Dead)
                requirement = Math.Max(requirement, evaluation.DeadAt > 0 ? evaluation.DeadAt : now);
            inputs.Levels.Remove(tf);
            if (requirement > 0) inputs.RemovedRequirements[tf] = requirement;
            else inputs.RemovedRequirements.Remove(tf);
            InputsChanged = true;

            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.LevelRemoved, Describe(side, tf) + " level " + FormatPrice(level.Price) + " removed"),
            };
            if (Arm != null && Arm.Side == side && tf == GateTimeframe.M1)
            {
                actions.Add(GateAction.CancelArmed(Arm, "The 1m level was removed — the arm was cancelled."));
                Arm = null;
            }
            Rebaseline();
            return GateCommandResult.Done(actions);
        }

        /// <summary>Deletes the side's low/high together with its levels (levels need an extreme).</summary>
        public GateCommandResult RemoveExtreme(GateSide side, long now)
        {
            var inputs = Inputs.For(side);
            if (inputs.Extreme == null)
                return GateCommandResult.Rejected("There's no " + ExtremeWord(side) + " to remove.");

            inputs.ClearExtreme();
            inputs.Levels.Clear();
            inputs.RemovedRequirements.Clear();
            InputsChanged = true;

            var actions = new List<GateAction>
            {
                GateAction.LogEvent(GateEvents.LevelRemoved, side + " " + ExtremeWord(side) + " and its levels removed"),
            };
            if (Arm != null && Arm.Side == side)
            {
                actions.Add(GateAction.CancelArmed(Arm, "The " + ExtremeWord(side) + " was removed — the arm was cancelled."));
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
                if (state == SetupState.Dead || state == SetupState.NoLevel)
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

        private void AddPromptIfNeeded(List<GateAction> actions)
        {
            if (!NeedsTrendAnswer || promptedForHourEnd >= latestHourEnd) return;
            promptedForHourEnd = latestHourEnd;
            actions.Add(GateAction.Prompt());
        }

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
