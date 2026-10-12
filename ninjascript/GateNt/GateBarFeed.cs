#region Using declarations
using System;
using System.Collections.Generic;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>
    /// One BarsRequest per instrument and timeframe. Delivers only closed bars: the last bar of a
    /// request is still forming, so a bar is delivered when the next one appears (its first tick)
    /// — the "open of the next candle" the spec fires entries on. Bars are handed to the runtime
    /// while this feed's lock is held so a later bar can never overtake an earlier one.
    /// </summary>
    internal sealed class GateBarFeed : IDisposable
    {
        private readonly object sync = new object();
        private readonly GateRuntime runtime;
        private readonly Instrument instrument;
        private readonly GateTimeframe timeframe;
        private readonly int historyDays;
        private readonly ClosedBarCursor cursor = new ClosedBarCursor();
        private BarsRequest request;
        private bool historyDelivered;

        public GateBarFeed(GateRuntime runtime, Instrument instrument, GateTimeframe timeframe, int historyDays)
        {
            this.runtime = runtime;
            this.instrument = instrument;
            this.timeframe = timeframe;
            this.historyDays = historyDays;
        }

        public void Start()
        {
            BarsRequest current;
            lock (sync)
            {
                cursor.Reset();
                historyDelivered = false;
                int minutes = GateTime.MinutesOf(timeframe);
                current = new BarsRequest(instrument, Math.Max(10, historyDays * 1440 / minutes));
                current.BarsPeriod = new BarsPeriod { BarsPeriodType = BarsPeriodType.Minute, Value = minutes };
                current.TradingHours = instrument.MasterInstrument.TradingHours;
                current.Update += OnUpdate;
                request = current;
            }
            current.Request((r, error, message) => OnLoaded(r, error, message));
        }

        public void Restart()
        {
            Dispose();
            Start();
        }

        public void Dispose()
        {
            lock (sync)
            {
                if (request == null) return;
                request.Update -= OnUpdate;
                request.Dispose();
                request = null;
            }
        }

        private void OnLoaded(BarsRequest loaded, ErrorCode error, string message)
        {
            if (error != ErrorCode.NoError)
            {
                runtime.OnFeedFailed(instrument.FullName, timeframe, string.IsNullOrEmpty(message) ? error.ToString() : message);
                return;
            }
            lock (sync)
            {
                if (loaded != request) return;
                var bars = TakeClosed(loaded.Bars);
                historyDelivered = true;
                runtime.OnBars(instrument.FullName, timeframe, bars, true);
            }
        }

        private void OnUpdate(object sender, BarsUpdateEventArgs e)
        {
            lock (sync)
            {
                if (!historyDelivered || request == null) return;
                var bars = TakeClosed(request.Bars);
                if (bars.Count > 0) runtime.OnBars(instrument.FullName, timeframe, bars, false);
            }
        }

        private List<GateBar> TakeClosed(Bars bars)
        {
            var closed = new List<GateBar>();
            if (bars == null) return closed;
            var zone = NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo;
            int minutes = GateTime.MinutesOf(timeframe);
            foreach (int i in cursor.Advance(bars.Count))
            {
                closed.Add(GateTime.BarFromClose(bars.GetTime(i), minutes,
                    bars.GetOpen(i), bars.GetHigh(i), bars.GetLow(i), bars.GetClose(i), zone));
            }
            return closed;
        }
    }
}
