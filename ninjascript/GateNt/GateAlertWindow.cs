#region Using declarations
using System;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>Spec §7/§11 "large alert": one topmost window, newest message first. UI thread only.</summary>
    internal sealed class GateAlertWindow : Window
    {
        private static GateAlertWindow open;

        /// <summary>Called when the AddOn stops (e.g. F5 recompile) so no window outlives its runtime.</summary>
        public static void CloseAll()
        {
            if (open != null) open.Close();
        }
        private readonly StackPanel lines = new StackPanel();

        public static void Raise(string message)
        {
            if (open == null)
            {
                open = new GateAlertWindow();
                open.Closed += (s, e) => open = null;
                open.Show();
            }
            open.lines.Children.Insert(0, new TextBlock
            {
                Text = DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + "  " + message,
                Foreground = Brushes.White,
                FontSize = 14,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 8),
            });
            open.Activate();
        }

        private GateAlertWindow()
        {
            Title = "Setup Gate — alerts";
            Width = 560;
            Height = 280;
            Topmost = true;
            Background = new SolidColorBrush(Color.FromRgb(120, 20, 20));
            Content = new ScrollViewer
            {
                Content = lines,
                Margin = new Thickness(12),
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            };
        }
    }
}
