#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>
    /// Spec §5 hourly trend dialog: one window, one row per instrument, latest hour only. The row
    /// draws the last 24 hourly candles so the trader has to look at the 1h chart to answer.
    /// UI thread only.
    /// </summary>
    internal sealed class GateTrendWindow : Window
    {
        private const double ChartWidth = 500;
        private const double ChartHeight = 170;

        private static GateTrendWindow open;
        private readonly StackPanel rows = new StackPanel();
        private readonly Dictionary<string, FrameworkElement> rowByInstrument =
            new Dictionary<string, FrameworkElement>(StringComparer.Ordinal);

        public static void Prompt(string instrument)
        {
            var runtime = GateRuntime.Current;
            if (runtime == null || instrument == null) return;
            if (open == null)
            {
                open = new GateTrendWindow();
                open.Closed += (s, e) => open = null;
                open.Show();
            }
            open.AddOrReplace(runtime, instrument);
            open.Activate();
        }

        private GateTrendWindow()
        {
            Title = "Setup Gate — confirm the hourly trend";
            Width = 560;
            SizeToContent = SizeToContent.Height;
            Topmost = true;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            Background = new SolidColorBrush(Color.FromRgb(30, 30, 30));
            Content = new ScrollViewer
            {
                Content = rows,
                MaxHeight = 820,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            };
        }

        private void AddOrReplace(GateRuntime runtime, string instrument)
        {
            FrameworkElement existing;
            if (rowByInstrument.TryGetValue(instrument, out existing)) rows.Children.Remove(existing);
            var row = BuildRow(runtime, instrument);
            rowByInstrument[instrument] = row;
            rows.Children.Add(row);
        }

        private FrameworkElement BuildRow(GateRuntime runtime, string instrument)
        {
            var snapshot = runtime.Snapshot(instrument);
            long hourEnd = runtime.LatestHourEnd(instrument);
            string hour = hourEnd > 0
                ? GateTime.FromUnixSeconds(hourEnd, NinjaTrader.Core.Globals.GeneralOptions.TimeZoneInfo)
                    .ToString("ddd HH:mm", CultureInfo.InvariantCulture)
                : "startup";

            var panel = new StackPanel { Margin = new Thickness(12, 10, 12, 10) };
            panel.Children.Add(Caption(instrument + " — hour ending " + hour, 15, Colors.White, true));
            string last = snapshot == null || snapshot.Trend == GateTrend.Unconfirmed ? "none yet" : snapshot.Trend.ToString();
            panel.Children.Add(Caption("Last answer: " + last, 12, Colors.Gray, false));
            panel.Children.Add(MiniChart(runtime.RecentHourlyBars(instrument, 24), snapshot));

            var error = Caption("", 12, Colors.OrangeRed, false);
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 6, 0, 0) };
            buttons.Children.Add(AnswerButton("▲  Up", GateTrend.Up, runtime, instrument, hourEnd, panel, error));
            buttons.Children.Add(AnswerButton("▼  Down", GateTrend.Down, runtime, instrument, hourEnd, panel, error));
            panel.Children.Add(buttons);
            panel.Children.Add(error);
            return panel;
        }

        private Button AnswerButton(string text, GateTrend trend, GateRuntime runtime, string instrument,
            long hourEnd, FrameworkElement row, TextBlock error)
        {
            var button = new Button
            {
                Content = text,
                Width = 120,
                Height = 32,
                Margin = new Thickness(0, 0, 10, 0),
                FontSize = 14,
            };
            button.Click += (s, e) =>
            {
                var result = runtime.AnswerTrend(instrument, trend, hourEnd);
                if (!result.Ok)
                {
                    error.Text = result.Error;
                    return;
                }
                rows.Children.Remove(row);
                rowByInstrument.Remove(instrument);
                if (rows.Children.Count == 0) Close();
            };
            return button;
        }

        private static Canvas MiniChart(IReadOnlyList<GateBar> bars, GateSnapshot snapshot)
        {
            var canvas = new Canvas
            {
                Width = ChartWidth,
                Height = ChartHeight,
                Background = new SolidColorBrush(Color.FromRgb(18, 18, 18)),
                Margin = new Thickness(0, 6, 0, 6),
            };
            if (bars.Count == 0)
            {
                canvas.Children.Add(Caption("No hourly bars yet.", 12, Colors.Gray, false));
                return canvas;
            }

            var levels = new List<KeyValuePair<double, bool>>();
            if (snapshot != null)
            {
                foreach (var side in new[] { snapshot.Long, snapshot.Short })
                {
                    var hourly = side.Timeframes.First(t => t.Timeframe == GateTimeframe.H1);
                    if (hourly.LevelPrice.HasValue) levels.Add(new KeyValuePair<double, bool>(hourly.LevelPrice.Value, side.IsActive));
                }
            }

            double high = bars.Max(b => b.High);
            double low = bars.Min(b => b.Low);
            foreach (var level in levels)
            {
                high = Math.Max(high, level.Key);
                low = Math.Min(low, level.Key);
            }
            if (high <= low) high = low + 1;
            Func<double, double> y = price => (high - price) / (high - low) * (ChartHeight - 12) + 6;

            double slot = ChartWidth / bars.Count;
            for (int i = 0; i < bars.Count; i++)
            {
                var bar = bars[i];
                double x = i * slot + slot / 2;
                Brush brush = bar.Close >= bar.Open ? Brushes.LimeGreen : Brushes.Red;
                canvas.Children.Add(new System.Windows.Shapes.Line { X1 = x, X2 = x, Y1 = y(bar.High), Y2 = y(bar.Low), Stroke = brush, StrokeThickness = 1 });
                double bodyWidth = Math.Max(2, slot * 0.6);
                var body = new System.Windows.Shapes.Rectangle
                {
                    Width = bodyWidth,
                    Height = Math.Max(1, Math.Abs(y(bar.Open) - y(bar.Close))),
                    Fill = brush,
                };
                Canvas.SetLeft(body, x - bodyWidth / 2);
                Canvas.SetTop(body, Math.Min(y(bar.Open), y(bar.Close)));
                canvas.Children.Add(body);
            }

            foreach (var level in levels)
            {
                canvas.Children.Add(new System.Windows.Shapes.Line
                {
                    X1 = 0,
                    X2 = ChartWidth,
                    Y1 = y(level.Key),
                    Y2 = y(level.Key),
                    Stroke = level.Value ? Brushes.Gold : new SolidColorBrush(Color.FromArgb(90, 255, 215, 0)),
                    StrokeThickness = level.Value ? 1.5 : 1,
                    StrokeDashArray = level.Value ? null : new DoubleCollection { 4, 3 },
                });
            }
            return canvas;
        }

        private static TextBlock Caption(string text, double size, Color color, bool bold) =>
            new TextBlock
            {
                Text = text,
                FontSize = size,
                Foreground = new SolidColorBrush(color),
                FontWeight = bold ? FontWeights.Bold : FontWeights.Normal,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 2, 0, 2),
            };
    }
}
