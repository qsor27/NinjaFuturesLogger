#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using NinjaTrader.Gui.Chart;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt;
#endregion

namespace NinjaTrader.NinjaScript.Indicators
{
    /// <summary>
    /// Setup Gate on the chart (spec §9): labelled level and low/high lines (click to place, drag
    /// to move), the status strip with per-timeframe icons and the Lines checkbox, the GATE OFFLINE
    /// banner, and the Setup Gate panel in Chart Trader. Arming reads the account, ATM template and
    /// quantity Chart Trader shows. All state comes from GateRuntime; this is only the view.
    /// </summary>
    public class SetupGate : Indicator
    {
        private const double DragTolerancePixels = 6;
        private static readonly GateTimeframe[] AllTimeframes =
            { GateTimeframe.M1, GateTimeframe.M3, GateTimeframe.H1, GateTimeframe.H4 };

        private readonly ChartClickMode clickMode = new ChartClickMode();
        private readonly Dictionary<GateTimeframe, RadioButton> timeframeButtons = new Dictionary<GateTimeframe, RadioButton>();
        private readonly Dictionary<GateTimeframe, TextBox> levelBoxes = new Dictionary<GateTimeframe, TextBox>();
        private readonly List<RowDefinition> traderRows = new List<RowDefinition>();

        private string instrumentName;
        private GateRuntime runtime;
        private GateSnapshot snapshot;
        private IReadOnlyList<ChartLine> chartLines = new ChartLine[0];
        private ChartScale lastScale;
        private ChartLine dragging;
        private double dragPrice;
        private bool showLines = true;
        private bool uiBuilt;
        private ChartControl hostControl;

        private DispatcherTimer timer;
        private Grid chartGrid;
        private Grid traderGrid;
        private Border strip;
        private TextBlock stripTrend;
        private StackPanel stripLong;
        private StackPanel stripShort;
        private TextBlock banner;
        private Border gatePanel;
        private RadioButton longButton;
        private RadioButton shortButton;
        private TextBlock extremeCaption;
        private TextBox extremeBox;
        private TextBox limitBox;
        private TextBlock statusText;
        private TextBlock messageText;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "SetupGate";
                Description = "Setup Gate on the chart: level lines, status icons and the Chart Trader arming panel.";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;
                DisplayInDataBox = false;
                DrawOnPricePanel = true;
                PaintPriceMarkers = false;
                IsSuspendedWhileInactive = false;
            }
            else if (State == State.DataLoaded)
            {
                instrumentName = Instrument != null ? Instrument.FullName : null;
            }
            else if (State == State.Historical)
            {
                var control = ChartControl;
                if (control != null) control.Dispatcher.InvokeAsync(() => BuildUi(control));
            }
            else if (State == State.Terminated)
            {
                var control = hostControl;
                if (control != null) control.Dispatcher.InvokeAsync(TearDownUi);
            }
        }

        protected override void OnBarUpdate()
        {
        }

        protected override void OnRender(ChartControl chartControl, ChartScale chartScale)
        {
            base.OnRender(chartControl, chartScale);
            lastScale = chartScale;
            if (!showLines || chartLines.Count == 0 || RenderTarget == null) return;

            float left = ChartPanel.X;
            float right = ChartPanel.X + ChartPanel.W;
            foreach (var line in chartLines)
            {
                double price = ReferenceEquals(line, dragging) ? dragPrice : line.Price;
                float y = chartScale.GetYByValue(price);
                using (var brush = new SharpDX.Direct2D1.SolidColorBrush(RenderTarget, ToColor(line.ColorHex, line.IsActiveSide ? 1f : 0.35f)))
                using (var format = new SharpDX.DirectWrite.TextFormat(NinjaTrader.Core.Globals.DirectWriteFactory, "Arial", 11f))
                using (var layout = new SharpDX.DirectWrite.TextLayout(NinjaTrader.Core.Globals.DirectWriteFactory, line.Label, format, 320f, 14f))
                {
                    RenderTarget.DrawLine(new SharpDX.Vector2(left, y), new SharpDX.Vector2(right, y), brush, line.IsExtreme ? 2f : 1f);
                    float x = right - layout.Metrics.Width - 6f;
                    RenderTarget.DrawTextLayout(new SharpDX.Vector2(x, y - 14f - line.StackIndex * 13f), layout, brush);
                }
            }
        }

        // ---------------- runtime attachment ----------------

        private void Attach()
        {
            var current = GateRuntime.Current;
            if (!ReferenceEquals(current, runtime))
            {
                if (runtime != null) runtime.GateChanged -= OnGateChanged;
                runtime = current;
                if (runtime != null && instrumentName != null)
                {
                    runtime.GateChanged += OnGateChanged;
                    string error = runtime.Track(instrumentName);
                    if (error != null) messageText.Text = error;
                }
            }
            RefreshSnapshot();
        }

        private void OnGateChanged(string instrument)
        {
            if (instrument != instrumentName) return;
            var control = hostControl;
            if (control != null) control.Dispatcher.InvokeAsync(RefreshSnapshot);
        }

        private void RefreshSnapshot()
        {
            if (!uiBuilt) return;
            snapshot = runtime != null && instrumentName != null ? runtime.Snapshot(instrumentName) : null;
            chartLines = ChartLines.From(snapshot);
            banner.Visibility = runtime == null ? Visibility.Visible : Visibility.Collapsed;
            UpdateStrip();
            UpdatePanel();
            ForceRefresh();
        }

        // ---------------- UI construction ----------------

        private void BuildUi(ChartControl control)
        {
            if (uiBuilt) return;
            uiBuilt = true;
            hostControl = control;
            chartGrid = control.Parent as Grid;

            BuildStrip();
            BuildBanner();
            BuildPanel();
            PlacePanel(control);

            control.PreviewMouseLeftButtonDown += OnMouseDown;
            control.PreviewMouseMove += OnMouseMove;
            control.PreviewMouseLeftButtonUp += OnMouseUp;
            control.PreviewKeyDown += OnKeyDown;

            timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            timer.Tick += (s, e) => Attach();
            timer.Start();
            Attach();
        }

        private void TearDownUi()
        {
            if (!uiBuilt) return;
            uiBuilt = false;
            if (timer != null) timer.Stop();
            if (runtime != null) runtime.GateChanged -= OnGateChanged;
            runtime = null;

            var control = hostControl;
            if (control != null)
            {
                control.PreviewMouseLeftButtonDown -= OnMouseDown;
                control.PreviewMouseMove -= OnMouseMove;
                control.PreviewMouseLeftButtonUp -= OnMouseUp;
                control.PreviewKeyDown -= OnKeyDown;
            }
            if (chartGrid != null)
            {
                chartGrid.Children.Remove(strip);
                chartGrid.Children.Remove(banner);
                chartGrid.Children.Remove(gatePanel);
            }
            if (traderGrid != null)
            {
                traderGrid.Children.Remove(gatePanel);
                foreach (var row in traderRows) traderGrid.RowDefinitions.Remove(row);
                traderRows.Clear();
            }
        }

        private void BuildStrip()
        {
            stripTrend = Text("", 12, Colors.White, true);
            var linesBox = new CheckBox
            {
                Content = "Lines",
                IsChecked = true,
                Foreground = Brushes.White,
                Margin = new Thickness(12, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
            };
            linesBox.Checked += (s, e) => { showLines = true; ForceRefresh(); };
            linesBox.Unchecked += (s, e) => { showLines = false; ForceRefresh(); };

            var top = new StackPanel { Orientation = Orientation.Horizontal };
            top.Children.Add(stripTrend);
            top.Children.Add(linesBox);

            stripLong = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 3, 0, 0) };
            stripShort = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 3, 0, 0) };
            var rows = new StackPanel();
            rows.Children.Add(top);
            rows.Children.Add(stripLong);
            rows.Children.Add(stripShort);

            strip = new Border
            {
                Child = rows,
                Background = new SolidColorBrush(Color.FromArgb(170, 0, 0, 0)),
                Padding = new Thickness(8, 4, 8, 4),
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(6, 24, 0, 0),
            };
            System.Windows.Controls.Panel.SetZIndex(strip, 1000);
            if (chartGrid != null) chartGrid.Children.Add(strip);
        }

        private void BuildBanner()
        {
            banner = new TextBlock
            {
                Text = "GATE OFFLINE — the Setup Gate AddOn isn't running",
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromRgb(170, 20, 20)),
                FontSize = 18,
                FontWeight = FontWeights.Bold,
                Padding = new Thickness(12, 6, 12, 6),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 40, 0, 0),
                IsHitTestVisible = false,
                Visibility = Visibility.Collapsed,
            };
            System.Windows.Controls.Panel.SetZIndex(banner, 1001);
            if (chartGrid != null) chartGrid.Children.Add(banner);
        }

        private void BuildPanel()
        {
            string group = "SetupGate" + GetHashCode().ToString(CultureInfo.InvariantCulture);
            var root = new StackPanel { Margin = new Thickness(4, 8, 4, 4) };
            root.Children.Add(Text("SETUP GATE", 12, Colors.SkyBlue, true));

            longButton = Radio("Long", group + "side", true);
            shortButton = Radio("Short", group + "side", false);
            longButton.Checked += (s, e) => UpdatePanel();
            shortButton.Checked += (s, e) => UpdatePanel();
            root.Children.Add(Row(longButton, shortButton));

            var timeframeRow = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
            foreach (var tf in AllTimeframes)
            {
                var button = Radio(InstrumentGate.Label(tf), group + "tf", tf == GateTimeframe.M1);
                timeframeButtons[tf] = button;
                timeframeRow.Children.Add(button);
            }
            root.Children.Add(timeframeRow);

            root.Children.Add(Row(
                MakeButton("Set Level", (s, e) => BeginClick(ClickTarget.Level)),
                MakeButton("Set Low/High", (s, e) => BeginClick(ClickTarget.Extreme))));

            var prices = new Grid { Margin = new Thickness(0, 4, 0, 4) };
            prices.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(42) });
            prices.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            extremeCaption = Text("Low", 11, Colors.Gainsboro, false);
            extremeBox = PriceBox();
            AddPriceRow(prices, extremeCaption, extremeBox, null);
            foreach (var tf in AllTimeframes)
            {
                var box = PriceBox();
                levelBoxes[tf] = box;
                AddPriceRow(prices, Text(InstrumentGate.Label(tf), 11, Colors.Gainsboro, false), box, tf);
            }
            root.Children.Add(prices);

            var armMarket = MakeButton("ARM MARKET", (s, e) => Arm(EntryKind.Market));
            armMarket.HorizontalAlignment = HorizontalAlignment.Stretch;
            root.Children.Add(armMarket);
            limitBox = PriceBox();
            limitBox.Width = 80;
            root.Children.Add(Row(MakeButton("ARM LIMIT @", (s, e) => Arm(EntryKind.Limit)), limitBox));
            root.Children.Add(MakeButton("Disarm", (s, e) => Disarm()));

            statusText = Text("", 11, Colors.White, true);
            messageText = Text("", 11, Colors.Khaki, false);
            root.Children.Add(statusText);
            root.Children.Add(messageText);

            gatePanel = new Border
            {
                Child = root,
                Background = new SolidColorBrush(Color.FromArgb(235, 25, 25, 25)),
                BorderBrush = Brushes.SteelBlue,
                BorderThickness = new Thickness(0, 1, 0, 0),
            };
        }

        private void PlacePanel(ChartControl control)
        {
            var trader = control.OwnerChart != null ? control.OwnerChart.ChartTrader : null;
            traderGrid = trader != null ? trader.Content as Grid : null;
            if (traderGrid != null)
            {
                if (traderGrid.RowDefinitions.Count == 0)
                {
                    var existing = new RowDefinition { Height = new GridLength(1, GridUnitType.Star) };
                    traderGrid.RowDefinitions.Add(existing);
                    traderRows.Add(existing);
                }
                var row = new RowDefinition { Height = GridLength.Auto };
                traderGrid.RowDefinitions.Add(row);
                traderRows.Add(row);
                Grid.SetRow(gatePanel, traderGrid.RowDefinitions.Count - 1);
                if (traderGrid.ColumnDefinitions.Count > 1) Grid.SetColumnSpan(gatePanel, traderGrid.ColumnDefinitions.Count);
                traderGrid.Children.Add(gatePanel);
            }
            else if (chartGrid != null)
            {
                gatePanel.Width = 210;
                gatePanel.HorizontalAlignment = HorizontalAlignment.Right;
                gatePanel.VerticalAlignment = VerticalAlignment.Bottom;
                gatePanel.Margin = new Thickness(0, 0, 80, 40);
                System.Windows.Controls.Panel.SetZIndex(gatePanel, 1000);
                chartGrid.Children.Add(gatePanel);
            }
        }

        // ---------------- strip and panel updates ----------------

        private void UpdateStrip()
        {
            if (snapshot == null)
            {
                stripTrend.Text = runtime == null ? "SETUP GATE — offline" : "SETUP GATE — loading " + instrumentName;
                stripLong.Children.Clear();
                stripShort.Children.Clear();
                return;
            }
            string trend = snapshot.Trend == GateTrend.Up ? "▲ UP" : snapshot.Trend == GateTrend.Down ? "▼ DOWN" : "not answered";
            stripTrend.Text = "TREND " + trend + (snapshot.NeedsTrendAnswer ? "  (answer needed)" : "");
            FillSideRow(stripLong, snapshot.Long);
            FillSideRow(stripShort, snapshot.Short);
        }

        private void FillSideRow(StackPanel row, SideSnapshot side)
        {
            row.Children.Clear();
            row.Opacity = side.IsActive ? 1.0 : 0.45;
            var caption = Text(side.Side == GateSide.Long ? "LONG" : "SHORT", 11, Colors.White, side.IsActive);
            caption.Width = 46;
            row.Children.Add(caption);
            foreach (var tf in side.Timeframes)
            {
                row.Children.Add(Text(InstrumentGate.Label(tf.Timeframe), 11, Colors.Gainsboro, false));
                row.Children.Add(Icon(GateVisuals.IconFor(tf.State)));
            }
            if (snapshot.Arm != null && snapshot.Arm.Side == side.Side)
                row.Children.Add(Text(snapshot.Arm.Describe(), 11, Colors.LimeGreen, true));
        }

        private void UpdatePanel()
        {
            if (gatePanel == null) return;
            GateSide side = SelectedSide();
            extremeCaption.Text = side == GateSide.Long ? "Low" : "High";
            if (snapshot == null)
            {
                statusText.Text = runtime == null ? "GATE OFFLINE — the Setup Gate AddOn isn't running." : "Loading " + instrumentName + "…";
                return;
            }
            var sideSnapshot = side == GateSide.Long ? snapshot.Long : snapshot.Short;
            SetBox(extremeBox, sideSnapshot.Extreme);
            foreach (var tf in sideSnapshot.Timeframes) SetBox(levelBoxes[tf.Timeframe], tf.LevelPrice);
            string cancel = runtime != null ? runtime.LastCancel(instrumentName) : null;
            statusText.Text = snapshot.StatusLine + (cancel != null ? "\nLast cancel: " + cancel : "");
        }

        private static void SetBox(TextBox box, double? value)
        {
            if (box.IsKeyboardFocusWithin) return;
            box.Text = value.HasValue ? InstrumentGate.FormatPrice(value.Value) : "";
        }

        // ---------------- commands ----------------

        private void BeginClick(ClickTarget target)
        {
            if (target == ClickTarget.Level) clickMode.BeginLevel(SelectedSide(), SelectedTimeframe());
            else clickMode.BeginExtreme(SelectedSide());
            messageText.Text = clickMode.Prompt;
        }

        private void CommitBox(GateTimeframe? tf, TextBox box)
        {
            if (runtime == null || snapshot == null) return;
            double price;
            if (!TryPrice(box.Text, out price)) return;
            price = Round(price);
            var side = SelectedSide();
            var sideSnapshot = side == GateSide.Long ? snapshot.Long : snapshot.Short;
            double? current = tf.HasValue
                ? sideSnapshot.Timeframes.First(t => t.Timeframe == tf.Value).LevelPrice
                : sideSnapshot.Extreme;
            if (current.HasValue && Math.Abs(current.Value - price) < TickSize / 2) return;
            Show(tf.HasValue
                ? runtime.SetLevel(instrumentName, side, tf.Value, price)
                : runtime.SetExtreme(instrumentName, side, price), "Saved.");
        }

        private void Arm(EntryKind kind)
        {
            if (runtime == null || snapshot == null)
            {
                messageText.Text = "The Setup Gate isn't running.";
                return;
            }
            var trader = hostControl != null && hostControl.OwnerChart != null ? hostControl.OwnerChart.ChartTrader : null;
            if (trader == null || trader.Account == null)
            {
                messageText.Text = "Show Chart Trader on this chart and choose an account.";
                return;
            }
            if (trader.AtmStrategy == null || string.IsNullOrEmpty(trader.AtmStrategy.Template))
            {
                messageText.Text = "Choose an ATM strategy in Chart Trader — the entry needs its stop and target.";
                return;
            }
            double limit = 0;
            if (kind == EntryKind.Limit && !TryPrice(limitBox.Text, out limit))
            {
                messageText.Text = "Type your limit price next to ARM LIMIT.";
                return;
            }
            GateSide side = SideMath.ActiveSide(snapshot.Trend) ?? SelectedSide();
            var arm = new PendingArm(side, kind, kind == EntryKind.Limit ? Round(limit) : 0,
                trader.AtmStrategy.Template, trader.Account.Name, trader.Quantity);
            Show(runtime.Arm(instrumentName, arm), "Armed.");
        }

        private void Disarm()
        {
            if (runtime != null) Show(runtime.Disarm(instrumentName), "Disarmed.");
        }

        private void Show(GateCommandResult result, string ok)
        {
            messageText.Text = result.Ok ? ok : result.Error;
            RefreshSnapshot();
        }

        // ---------------- mouse ----------------

        private void OnMouseDown(object sender, MouseButtonEventArgs e)
        {
            if (lastScale == null || runtime == null || hostControl == null) return;
            int y = PixelY(e);
            if (clickMode.Target != ClickTarget.None)
            {
                double price = Round(lastScale.GetValueByY(y));
                var target = clickMode.Target;
                var side = clickMode.Side;
                var tf = clickMode.Timeframe;
                clickMode.Cancel();
                Show(target == ClickTarget.Level
                    ? runtime.SetLevel(instrumentName, side, tf, price)
                    : runtime.SetExtreme(instrumentName, side, price), "Placed at " + InstrumentGate.FormatPrice(price) + ".");
                e.Handled = true;
                return;
            }
            if (!showLines) return;
            var scale = lastScale;
            var hit = ChartLines.NearestWithin(chartLines, p => scale.GetYByValue(p), y, DragTolerancePixels);
            if (hit == null) return;
            dragging = hit;
            dragPrice = hit.Price;
            hostControl.CaptureMouse();
            e.Handled = true;
        }

        private void OnMouseMove(object sender, MouseEventArgs e)
        {
            if (dragging == null || lastScale == null) return;
            dragPrice = Round(lastScale.GetValueByY(PixelY(e)));
            ForceRefresh();
            e.Handled = true;
        }

        private void OnMouseUp(object sender, MouseButtonEventArgs e)
        {
            if (dragging == null) return;
            var line = dragging;
            dragging = null;
            if (hostControl != null) hostControl.ReleaseMouseCapture();
            e.Handled = true;
            if (runtime == null || Math.Abs(dragPrice - line.Price) < TickSize / 2)
            {
                ForceRefresh();
                return;
            }
            Show(line.IsExtreme
                ? runtime.SetExtreme(instrumentName, line.Side, dragPrice)
                : runtime.SetLevel(instrumentName, line.Side, line.Timeframe.Value, dragPrice),
                "Moved to " + InstrumentGate.FormatPrice(dragPrice) + ".");
        }

        private void OnKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key != Key.Escape || clickMode.Target == ClickTarget.None) return;
            clickMode.Cancel();
            messageText.Text = "";
            e.Handled = true;
        }

        private int PixelY(MouseEventArgs e) =>
            ChartingExtensions.ConvertToVerticalPixels(e.GetPosition(hostControl as IInputElement).Y, hostControl);

        // ---------------- helpers ----------------

        private GateSide SelectedSide() => shortButton != null && shortButton.IsChecked == true ? GateSide.Short : GateSide.Long;

        private GateTimeframe SelectedTimeframe()
        {
            foreach (var pair in timeframeButtons)
            {
                if (pair.Value.IsChecked == true) return pair.Key;
            }
            return GateTimeframe.M1;
        }

        private double Round(double price) => Instrument.MasterInstrument.RoundToTickSize(price);

        private static bool TryPrice(string text, out double value)
        {
            string t = (text ?? "").Trim();
            if (double.TryParse(t, NumberStyles.Float, CultureInfo.CurrentCulture, out value) && value > 0) return true;
            return double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out value) && value > 0;
        }

        private static SharpDX.Color4 ToColor(string hex, float alpha)
        {
            var c = (Color)ColorConverter.ConvertFromString(hex);
            return new SharpDX.Color4(c.R / 255f, c.G / 255f, c.B / 255f, alpha);
        }

        private void AddPriceRow(Grid grid, TextBlock caption, TextBox box, GateTimeframe? tf)
        {
            int row = grid.RowDefinitions.Count;
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            Grid.SetRow(caption, row);
            Grid.SetRow(box, row);
            Grid.SetColumn(box, 1);
            caption.VerticalAlignment = VerticalAlignment.Center;
            grid.Children.Add(caption);
            grid.Children.Add(box);
            box.KeyDown += (s, e) =>
            {
                if (e.Key != Key.Enter) return;
                CommitBox(tf, box);
                e.Handled = true;
            };
            box.LostFocus += (s, e) => CommitBox(tf, box);
        }

        private static FrameworkElement Icon(GateIcon icon)
        {
            var margin = new Thickness(3, 0, 8, 0);
            switch (icon)
            {
                case GateIcon.NoLevel:
                    return new System.Windows.Shapes.Ellipse
                    {
                        Width = 6, Height = 6, Fill = Brushes.Gray, Margin = margin, VerticalAlignment = VerticalAlignment.Center,
                    };
                case GateIcon.Dead:
                    return new TextBlock
                    {
                        Text = "✕", Foreground = Brushes.Red, FontWeight = FontWeights.Bold, Margin = margin,
                        VerticalAlignment = VerticalAlignment.Center,
                    };
                default:
                    return new Border
                    {
                        Width = 12,
                        Height = 12,
                        Margin = margin,
                        VerticalAlignment = VerticalAlignment.Center,
                        BorderThickness = new Thickness(2),
                        BorderBrush = icon == GateIcon.Waiting ? Brushes.Red : Brushes.LimeGreen,
                        Background = icon == GateIcon.SolidGreen ? Brushes.LimeGreen
                            : icon == GateIcon.Waiting ? Brushes.Red : Brushes.Transparent,
                    };
            }
        }

        private static TextBlock Text(string text, double size, Color color, bool bold) =>
            new TextBlock
            {
                Text = text,
                FontSize = size,
                Foreground = new SolidColorBrush(color),
                FontWeight = bold ? FontWeights.Bold : FontWeights.Normal,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 1, 4, 1),
                VerticalAlignment = VerticalAlignment.Center,
            };

        private static RadioButton Radio(string text, string group, bool isChecked) =>
            new RadioButton
            {
                Content = text,
                GroupName = group,
                IsChecked = isChecked,
                Foreground = Brushes.White,
                Margin = new Thickness(0, 0, 8, 0),
            };

        private static TextBox PriceBox() =>
            new TextBox
            {
                Background = new SolidColorBrush(Color.FromRgb(45, 45, 45)),
                Foreground = Brushes.White,
                BorderBrush = Brushes.DimGray,
                Margin = new Thickness(0, 1, 0, 1),
            };

        private static Button MakeButton(string text, RoutedEventHandler onClick)
        {
            var button = new Button { Content = text, Margin = new Thickness(0, 2, 4, 2), Padding = new Thickness(6, 2, 6, 2) };
            button.Click += onClick;
            return button;
        }

        private static StackPanel Row(params UIElement[] children)
        {
            var row = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 2, 0, 2) };
            foreach (var child in children) row.Children.Add(child);
            return row;
        }
    }
}
