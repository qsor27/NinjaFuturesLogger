#region Using declarations
using System;
using System.Windows;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>
    /// Setup Gate (spec docs/superpowers/specs/2026-10-12-setup-gate-design.md): blocks entries
    /// that don't follow the trader's level-regain setup and fires armed entries at the next
    /// candle's open. Levels and arming live on the chart (the Setup Gate indicator + Chart
    /// Trader panel); this AddOn only hosts the runtime and the windows that have no chart
    /// context — the hourly trend prompt and alerts.
    /// </summary>
    public class SetupGateAddOn : AddOnBase
    {
        private GateRuntime runtime;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "SetupGateAddOn";
                Description = "Setup Gate: entries only from an armed level-regain setup in the hourly trend direction.";
            }
            else if (State == State.Active)
            {
                // AddOns use the Active state; they never pass through DataLoaded/Historical/Realtime.
                if (runtime != null) return;
                runtime = new GateRuntime(Print);
                runtime.TrendPromptRequested += instrument => OnUi(() => GateTrendWindow.Prompt(instrument));
                runtime.AlertRaised += message => OnUi(() => GateAlertWindow.Raise(message));
                runtime.Start();
                Print("Setup Gate started. Settings: " + GateRuntime.SettingsPath);
            }
            else if (State == State.Terminated)
            {
                if (runtime != null) runtime.Stop();
                runtime = null;
                OnUi(GateTrendWindow.CloseAll);
            }
        }

        private static void OnUi(Action action)
        {
            var app = Application.Current;
            if (app != null) app.Dispatcher.InvokeAsync(action);
        }
    }
}
