using System.Collections.Generic;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class TimeframeSnapshot
    {
        public TimeframeSnapshot(GateTimeframe timeframe, double? levelPrice, SetupState state)
        {
            Timeframe = timeframe;
            LevelPrice = levelPrice;
            State = state;
        }

        public GateTimeframe Timeframe { get; }
        public double? LevelPrice { get; }
        public SetupState State { get; }
    }

    public sealed class SideSnapshot
    {
        public SideSnapshot(GateSide side, bool isActive, double? extreme, ExtremeMode? extremeMode,
            IReadOnlyList<TimeframeSnapshot> timeframes)
        {
            Side = side;
            IsActive = isActive;
            Extreme = extreme;
            ExtremeMode = extremeMode;
            Timeframes = timeframes;
        }

        public GateSide Side { get; }

        /// <summary>The hourly trend's side; the other side is drawn dimmed (spec §3).</summary>
        public bool IsActive { get; }

        public double? Extreme { get; }
        public ExtremeMode? ExtremeMode { get; }

        /// <summary>Always 1m, 3m, 1h, 4h in that order.</summary>
        public IReadOnlyList<TimeframeSnapshot> Timeframes { get; }
    }

    /// <summary>Everything a UI needs to render one instrument's gate (spec §9).</summary>
    public sealed class GateSnapshot
    {
        public GateSnapshot(string instrument, GateTrend trend, bool needsTrendAnswer, PendingArm arm,
            string statusLine, SideSnapshot longSide, SideSnapshot shortSide)
        {
            Instrument = instrument;
            Trend = trend;
            NeedsTrendAnswer = needsTrendAnswer;
            Arm = arm;
            StatusLine = statusLine;
            Long = longSide;
            Short = shortSide;
        }

        public string Instrument { get; }
        public GateTrend Trend { get; }
        public bool NeedsTrendAnswer { get; }
        public PendingArm Arm { get; }
        public string StatusLine { get; }
        public SideSnapshot Long { get; }
        public SideSnapshot Short { get; }
    }
}
