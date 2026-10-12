#region Using declarations
using System;
using System.Windows;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>
    /// Setup Gate (spec docs/superpowers/specs/2026-10-12-setup-gate-design.md): blocks entries
    /// that don't follow the trader's level-regain setup and fires armed entries at the next
    /// candle's open. Adds Control Center → New → Setup Gate.
    /// </summary>
    public class SetupGateAddOn : AddOnBase
    {
        private GateRuntime runtime;
        private NTMenuItem newMenu;
        private NTMenuItem menuItem;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "SetupGateAddOn";
                Description = "Setup Gate: entries only from an armed level-regain setup in the hourly trend direction.";
            }
            else if (State == State.DataLoaded)
            {
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
            }
        }

        protected override void OnWindowCreated(Window window)
        {
            var controlCenter = window as ControlCenter;
            if (controlCenter == null) return;
            newMenu = controlCenter.FindFirst("ControlCenterMenuItemNew") as NTMenuItem;
            if (newMenu == null) return;
            menuItem = new NTMenuItem
            {
                Header = "Setup Gate",
                Style = Application.Current.TryFindResource("MainMenuItem") as Style,
            };
            menuItem.Click += OnMenuClick;
            newMenu.Items.Add(menuItem);
        }

        protected override void OnWindowDestroyed(Window window)
        {
            if (!(window is ControlCenter) || menuItem == null) return;
            if (newMenu != null && newMenu.Items.Contains(menuItem)) newMenu.Items.Remove(menuItem);
            menuItem.Click -= OnMenuClick;
            menuItem = null;
        }

        private void OnMenuClick(object sender, RoutedEventArgs e) => GateControlWindow.ShowSingleton();

        private static void OnUi(Action action)
        {
            var app = Application.Current;
            if (app != null) app.Dispatcher.InvokeAsync(action);
        }
    }
}
