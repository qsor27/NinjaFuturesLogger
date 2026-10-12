#region Using declarations
using System;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>
    /// Plan B2 control surface (Control Center → New → Setup Gate): track an instrument, set the
    /// low/high and per-timeframe levels by typed price, arm and disarm, and read the status line.
    /// Plan C adds the chart and Chart Trader versions of the same commands. UI thread only.
    /// </summary>
    internal sealed class GateControlWindow : Window
    {
        private static GateControlWindow open;

        /// <summary>Called when the AddOn stops (e.g. F5 recompile) so no window outlives its runtime.</summary>
        public static void CloseAll()
        {
            if (open != null) open.Close();
        }

        private readonly ComboBox instruments = new ComboBox { Width = 170 };
        private readonly TextBox newInstrument = new TextBox { Width = 120 };
        private readonly ComboBox side = Choices("Long", "Short");
        private readonly ComboBox timeframe = Choices("1m", "3m", "1h", "4h");
        private readonly TextBox price = new TextBox { Width = 110 };
        private readonly ComboBox account = new ComboBox { Width = 170 };
        private readonly TextBox atmTemplate = new TextBox { Width = 170 };
        private readonly TextBox quantity = new TextBox { Width = 50, Text = "1" };
        private readonly TextBox limitPrice = new TextBox { Width = 110 };
        private readonly TextBlock status = TextLine(15, Colors.White, true);
        private readonly TextBlock states = TextLine(12, Colors.Gainsboro, false);
        private readonly TextBlock message = TextLine(12, Colors.Khaki, false);

        public static void ShowSingleton()
        {
            if (GateRuntime.Current == null)
            {
                GateAlertWindow.Raise("The Setup Gate AddOn is not running.");
                return;
            }
            if (open == null)
            {
                open = new GateControlWindow();
                open.Closed += (s, e) => open = null;
                open.Show();
            }
            else
            {
                open.Activate();
            }
        }

        private GateControlWindow()
        {
            Title = "Setup Gate";
            Width = 680;
            SizeToContent = SizeToContent.Height;
            Background = new SolidColorBrush(Color.FromRgb(30, 30, 30));

            var root = new StackPanel { Margin = new Thickness(12) };
            root.Children.Add(Row(Caption("Instrument"), instruments, newInstrument, MakeButton("Track", OnTrack)));
            root.Children.Add(status);
            root.Children.Add(states);
            root.Children.Add(Heading("Levels"));
            root.Children.Add(Row(side, timeframe, price, MakeButton("Set Level", OnSetLevel), MakeButton("Set Low / High", OnSetExtreme)));
            root.Children.Add(Heading("Entry"));
            root.Children.Add(Row(Caption("Account"), account, Caption("ATM"), atmTemplate, Caption("Qty"), quantity));
            root.Children.Add(Row(MakeButton("ARM MARKET", OnArmMarket), Caption("Limit"), limitPrice, MakeButton("ARM LIMIT", OnArmLimit),
                MakeButton("Disarm", OnDisarm), MakeButton("Hourly trend…", OnTrend)));
            root.Children.Add(message);
            Content = root;

            lock (Account.All)
            {
                foreach (Account a in Account.All) account.Items.Add(a.Name);
            }
            if (account.Items.Count > 0) account.SelectedIndex = 0;

            instruments.SelectionChanged += (s, e) => Refresh();
            ReloadInstruments(null);

            var runtime = GateRuntime.Current;
            runtime.GateChanged += OnGateChanged;
            Closed += (s, e) => runtime.GateChanged -= OnGateChanged;
        }

        private string Selected => instruments.SelectedItem as string;
        private GateSide SelectedSide => side.SelectedIndex == 1 ? GateSide.Short : GateSide.Long;
        private GateTimeframe SelectedTimeframe => (GateTimeframe)Math.Max(0, timeframe.SelectedIndex);

        private void OnGateChanged(string instrument)
        {
            Dispatcher.InvokeAsync(() =>
            {
                if (instrument == Selected) Refresh();
            });
        }

        private void OnTrack(object sender, RoutedEventArgs e)
        {
            var runtime = Runtime();
            if (runtime == null) return;
            string name = newInstrument.Text.Trim();
            string error = runtime.Track(name);
            message.Text = error ?? "Tracking " + name + ". Bars are loading.";
            if (error == null) ReloadInstruments(name);
        }

        private void OnSetLevel(object sender, RoutedEventArgs e)
        {
            double p;
            if (!HasInstrument()) return;
            if (!TryPrice(price.Text, out p))
            {
                message.Text = "Type the level price.";
                return;
            }
            var runtime = Runtime();
            if (runtime != null) Show(runtime.SetLevel(Selected, SelectedSide, SelectedTimeframe, p), "Level set.");
        }

        private void OnSetExtreme(object sender, RoutedEventArgs e)
        {
            double p;
            if (!HasInstrument()) return;
            if (!TryPrice(price.Text, out p))
            {
                message.Text = "Type the low (long) or high (short) price.";
                return;
            }
            var runtime = Runtime();
            if (runtime != null) Show(runtime.SetExtreme(Selected, SelectedSide, p), "Low / high set.");
        }

        private void OnArmMarket(object sender, RoutedEventArgs e) => Arm(EntryKind.Market, 0);

        private void OnArmLimit(object sender, RoutedEventArgs e)
        {
            double p;
            if (!TryPrice(limitPrice.Text, out p))
            {
                message.Text = "Type the limit price.";
                return;
            }
            Arm(EntryKind.Limit, p);
        }

        private void Arm(EntryKind kind, double limit)
        {
            if (!HasInstrument()) return;
            int qty;
            if (!int.TryParse(quantity.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out qty) || qty <= 0)
            {
                message.Text = "Quantity must be a whole number above 0.";
                return;
            }
            string acct = account.SelectedItem as string;
            string atm = atmTemplate.Text.Trim();
            if (string.IsNullOrEmpty(acct) || atm.Length == 0)
            {
                message.Text = "Choose an account and type the ATM template name exactly as it appears in Chart Trader.";
                return;
            }
            var runtime = Runtime();
            if (runtime != null) Show(runtime.Arm(Selected, new PendingArm(SelectedSide, kind, limit, atm, acct, qty)), "Armed.");
        }

        private void OnDisarm(object sender, RoutedEventArgs e)
        {
            if (!HasInstrument()) return;
            var runtime = Runtime();
            if (runtime != null) Show(runtime.Disarm(Selected), "Disarmed.");
        }

        private void OnTrend(object sender, RoutedEventArgs e)
        {
            if (HasInstrument()) GateTrendWindow.Prompt(Selected);
        }

        private GateRuntime Runtime()
        {
            var runtime = GateRuntime.Current;
            if (runtime == null) message.Text = "The Setup Gate isn't running — reopen it from Control Center → New → Setup Gate.";
            return runtime;
        }

        private bool HasInstrument()
        {
            if (Selected != null) return true;
            message.Text = "Track an instrument first.";
            return false;
        }

        private void Show(GateCommandResult result, string ok)
        {
            message.Text = result.Ok ? ok : result.Error;
            Refresh();
        }

        private void ReloadInstruments(string select)
        {
            var runtime = Runtime();
            if (runtime == null) return;
            string keep = select ?? Selected;
            instruments.Items.Clear();
            foreach (string name in runtime.TrackedInstruments()) instruments.Items.Add(name);
            string match = instruments.Items.Cast<string>()
                .FirstOrDefault(n => string.Equals(n, keep, StringComparison.OrdinalIgnoreCase));
            if (match != null) instruments.SelectedItem = match;
            else if (instruments.Items.Count > 0) instruments.SelectedIndex = 0;
            Refresh();
        }

        private void Refresh()
        {
            var runtime = GateRuntime.Current;
            var snapshot = runtime == null ? null : runtime.Snapshot(Selected);
            if (snapshot == null)
            {
                status.Text = "Track an instrument to start (e.g. MNQ 12-26).";
                states.Text = "";
                return;
            }
            status.Text = snapshot.StatusLine;
            var sb = new StringBuilder();
            sb.AppendLine("Hourly trend: " + (snapshot.Trend == GateTrend.Unconfirmed ? "not answered" : snapshot.Trend.ToString())
                + (snapshot.NeedsTrendAnswer ? " — answer needed" : ""));
            AppendSide(sb, snapshot.Long);
            AppendSide(sb, snapshot.Short);
            string cancel = runtime.LastCancel(Selected);
            if (cancel != null) sb.AppendLine("Last cancel: " + cancel);
            states.Text = sb.ToString().TrimEnd();
        }

        private static void AppendSide(StringBuilder sb, SideSnapshot s)
        {
            sb.Append(s.Side.ToString().ToUpperInvariant()).Append(s.IsActive ? " (active)" : " (inactive)")
              .Append(" — ").Append(InstrumentGate.ExtremeWord(s.Side)).Append(' ');
            sb.AppendLine(s.Extreme.HasValue
                ? InstrumentGate.FormatPrice(s.Extreme.Value) + (s.ExtremeMode == ExtremeMode.Auto ? " (auto)" : " (pinned)")
                : "not set");
            sb.Append("    ");
            foreach (var tf in s.Timeframes)
            {
                sb.Append(InstrumentGate.Label(tf.Timeframe)).Append(' ')
                  .Append(tf.LevelPrice.HasValue ? InstrumentGate.FormatPrice(tf.LevelPrice.Value) : "—").Append(' ')
                  .Append(tf.State).Append("    ");
            }
            sb.AppendLine();
        }

        private static bool TryPrice(string text, out double value)
        {
            string t = (text ?? "").Trim();
            if (double.TryParse(t, NumberStyles.Float, CultureInfo.CurrentCulture, out value) && value > 0) return true;
            return double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out value) && value > 0;
        }

        private static ComboBox Choices(params string[] items)
        {
            var box = new ComboBox { Width = 70 };
            foreach (string item in items) box.Items.Add(item);
            box.SelectedIndex = 0;
            return box;
        }

        private static TextBlock TextLine(double size, Color color, bool bold) =>
            new TextBlock
            {
                FontSize = size,
                Foreground = new SolidColorBrush(color),
                FontWeight = bold ? FontWeights.Bold : FontWeights.Normal,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 4, 0, 4),
            };

        private static TextBlock Caption(string text)
        {
            var block = TextLine(12, Colors.Gray, false);
            block.Text = text;
            block.VerticalAlignment = VerticalAlignment.Center;
            block.Margin = new Thickness(8, 0, 4, 0);
            return block;
        }

        private static TextBlock Heading(string text)
        {
            var block = TextLine(13, Colors.SkyBlue, true);
            block.Text = text;
            block.Margin = new Thickness(0, 10, 0, 2);
            return block;
        }

        private static Button MakeButton(string text, RoutedEventHandler onClick)
        {
            var button = new Button { Content = text, Margin = new Thickness(6, 0, 0, 0), Padding = new Thickness(8, 2, 8, 2) };
            button.Click += onClick;
            return button;
        }

        private static StackPanel Row(params UIElement[] children)
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 4) };
            foreach (var child in children) row.Children.Add(child);
            return row;
        }
    }
}
