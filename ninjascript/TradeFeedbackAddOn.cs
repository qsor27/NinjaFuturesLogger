#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.NinjaFuturesLogger;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>
    /// TradeFeedbackAddOn - Interactive trade validation interface for NinjaTrader
    /// Allows traders to mark closed positions as Valid or Invalid
    /// Integrates with NinjaFuturesLogger application for performance analysis
    /// </summary>
    public class TradeFeedbackAddOn : NinjaTrader.NinjaScript.AddOnBase
    {
        #region Variables
        private PositionValidationTracker validationTracker;

        // Task 8.3: Settings variables with defaults
        private bool enableOrderBlocking = true;
        private int gracePeriodSeconds = 0;
        private bool bypassAutomatedStrategies = true;
        private bool enableEmergencyOverride = true;

        // Cumulative realized PnL per account, sampled at each flat transition; the
        // delta is the realized PnL of the trade that just closed. Account event
        // callbacks (PositionUpdate) can fire on different threads, so this follows
        // the file's existing cross-thread-map convention (see SharedValidationMap).
        private readonly ConcurrentDictionary<string, double> lastRealizedPnlByAccount = new ConcurrentDictionary<string, double>();
        #endregion

        #region AddOn Lifecycle

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = @"Interactive trade validation interface for marking trades as Valid or Invalid";
                Name = "TradeFeedbackAddOn";

                // Task 8.3: Initialize default settings
                EnableOrderBlocking = true;
                GracePeriodSeconds = 0;
                BypassAutomatedStrategies = true;
                EnableEmergencyOverride = true;
            }
            else if (State == State.DataLoaded)
            {
                // Task 8.4: Apply settings to AddOn behavior
                enableOrderBlocking = EnableOrderBlocking;
                gracePeriodSeconds = GracePeriodSeconds;
                bypassAutomatedStrategies = BypassAutomatedStrategies;
                enableEmergencyOverride = EnableEmergencyOverride;

                // Initialize validation tracker (shared singleton; canonical state file,
                // legacy files migrated on first ever touch)
                validationTracker = TradeValidationShared.Tracker;

                // Subscribe to position update events for all accounts
                if (Account.All != null)
                {
                    foreach (Account account in Account.All)
                    {
                        if (account != null)
                        {
                            account.PositionUpdate += OnPositionUpdate;
                            account.OrderUpdate += OnOrderUpdate;

                            try
                            {
                                lastRealizedPnlByAccount[account.Name] = account.Get(AccountItem.RealizedProfitLoss, Currency.UsDollar);
                            }
                            catch
                            {
                                lastRealizedPnlByAccount[account.Name] = 0;
                            }
                        }
                    }
                }

                Print("TradeFeedbackAddOn initialized. State file: " + TradeValidationShared.StateFilePath);
                Print($"Settings - Order blocking: {enableOrderBlocking}, Grace period: {gracePeriodSeconds}s");
            }
            else if (State == State.Terminated)
            {
                // Save state before shutdown
                TradeValidationShared.SaveState();

                // Unsubscribe from events
                if (Account.All != null)
                {
                    foreach (Account account in Account.All)
                    {
                        if (account != null)
                        {
                            account.PositionUpdate -= OnPositionUpdate;
                            account.OrderUpdate -= OnOrderUpdate;
                        }
                    }
                }

                Print("TradeFeedbackAddOn terminated. State saved.");
            }
        }

        #endregion

        #region Position Event Handlers

        /// <summary>
        /// Handles position update events to detect closed positions
        /// </summary>
        private void OnPositionUpdate(object sender, PositionEventArgs e)
        {
            try
            {
                if (e?.Position == null) return;

                // Debug: Log all position updates to see what's happening
                Print($"DEBUG: PositionUpdate - {e.Position.Instrument?.FullName} MarketPosition: {e.Position.MarketPosition} Quantity: {e.Position.Quantity}");

                // Check if position is now flat (closed)
                if (e.Position.MarketPosition == MarketPosition.Flat && e.Position.Quantity == 0)
                {
                    // Position just closed
                    var account = e.Position.Account?.Name ?? "Unknown";
                    var instrument = e.Position.Instrument?.FullName ?? "Unknown";
                    var entryTime = DateTime.Now; // Use current time as approximation

                    // Realized PnL of the closing trade = delta of the account's cumulative
                    // realized PnL since the last flat transition. (GetUnrealizedProfitLoss on an
                    // already-flat position is ~0 and never triggered validation - the old bug.)
                    // A failed/unavailable read must never fabricate a PnL or mutate the baseline:
                    // that would either poison the NEXT trade's delta or produce a false "large
                    // loss" (0 - baseline) that wrongly triggers validation/order-blocking. So we
                    // skip validation tracking for this closed position entirely and log it -
                    // no AddPosition call, no baseline write.
                    double realizedNow;
                    try
                    {
                        if (e.Position.Account == null)
                        {
                            Print($"Skipping validation tracking for {instrument}: position has no Account reference");
                            return;
                        }

                        realizedNow = e.Position.Account.Get(AccountItem.RealizedProfitLoss, Currency.UsDollar);
                    }
                    catch (Exception readEx)
                    {
                        Print($"Error reading RealizedProfitLoss for {account}: {readEx.Message} - skipping validation tracking for this closed position");
                        return;
                    }

                    double baseline;
                    if (!lastRealizedPnlByAccount.TryGetValue(account, out baseline))
                        baseline = realizedNow;
                    var pnl = realizedNow - baseline;
                    lastRealizedPnlByAccount[account] = realizedNow;

                    // Generate position ID
                    var positionId = TradeValidationShared.GeneratePositionId(entryTime, instrument, account);

                    // Add to validation tracker (require validation for stopped-out positions)
                    bool requiresValidation = pnl < 0; // Require validation for realized losses
                    validationTracker.AddPosition(positionId, entryTime, instrument, (decimal)pnl, requiresValidation);

                    Print($"Position closed: {instrument} P&L: {pnl:F2} - Requires validation: {requiresValidation}");
                }
            }
            catch (Exception ex)
            {
                Print($"Error in OnPositionUpdate: {ex.Message}");
            }
        }

        #endregion

        #region Order Blocking and Enforcement

        /// <summary>
        /// Handles order update events to intercept and block orders when validation required
        /// Task 7.2: Subscribe to Account.OrderUpdate events
        /// Task 7.3: Implement order interception logic
        /// </summary>
        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            try
            {
                if (e?.Order == null) return;

                // Only intercept new order submissions
                if (e.OrderState != OrderState.Submitted && e.OrderState != OrderState.Working)
                    return;

                // Task 8.4: Check if order blocking is enabled from settings
                if (!enableOrderBlocking)
                    return;

                // Task 8.4: Bypass validation for automated strategies (from settings)
                if (bypassAutomatedStrategies && TradeValidationShared.IsAutomatedOrder(e.Order))
                {
                    Print($"Order {e.Order.OrderId} bypassed validation (automated strategy)");
                    return;
                }

                // Task 8.4: Check for emergency override (from settings)
                if (enableEmergencyOverride && TradeValidationShared.IsEmergencyOverride())
                {
                    Print($"WARNING: Order {e.Order.OrderId} bypassed validation via emergency override (Ctrl+Shift)");
                    return;
                }

                // Get unvalidated positions for the order's instrument (grace period applied
                // inside the shared tracker query)
                var unvalidatedPositions = validationTracker.GetUnvalidatedPositionsForInstrument(
                    e.Order.Instrument?.FullName ?? "",
                    gracePeriodSeconds);

                if (unvalidatedPositions.Count > 0)
                {
                    // Task 7.3: Alert user - order blocking
                    // Note: NinjaTrader AddOns cannot directly cancel orders
                    // Instead we alert the user to validate positions before trading
                    Print($"VALIDATION REQUIRED: {unvalidatedPositions.Count} unvalidated position(s) for {e.Order.Instrument?.FullName}");
                    Print($"Order detected: {e.Order.OrderId} - User should validate positions before proceeding");

                    // Task 7.4: Show validation enforcement modal
                    ShowValidationEnforcementModal(unvalidatedPositions);
                }
            }
            catch (Exception ex)
            {
                Print($"Error in OnOrderUpdate: {ex.Message}");
            }
        }

        /// <summary>
        /// Task 7.4: Shows validation enforcement modal dialog
        /// Task 7.5: Implements "Validate and Continue" workflow
        /// </summary>
        private void ShowValidationEnforcementModal(List<PositionValidationEntry> unvalidatedPositions)
        {
            try
            {
                // Execute on UI thread
                Application.Current?.Dispatcher.InvokeAsync(() =>
                {
                    try
                    {
                        // Create custom WPF window for validation enforcement
                        var modal = new ValidationEnforcementWindow(unvalidatedPositions, validationTracker, this);
                        modal.Owner = Application.Current.MainWindow;
                        modal.WindowStartupLocation = WindowStartupLocation.CenterOwner;

                        // Show modal dialog (blocking)
                        var result = modal.ShowDialog();

                        if (result == true)
                        {
                            Print("Positions validated via enforcement modal");
                        }
                    }
                    catch (Exception ex)
                    {
                        Print($"Error showing validation modal: {ex.Message}");

                        // Fallback to simple message box
                        var positionList = string.Join("\n", unvalidatedPositions.Select(p => $"{p.Instrument}: {p.PnL:F2}"));

                        NTMessageBoxSimple.Show(Application.Current.MainWindow,
                            $"Position validation required before placing new order.\n\n" +
                            $"Unvalidated positions:\n{positionList}\n\n" +
                            $"Please validate positions using the chart panel.",
                            "Validation Required",
                            MessageBoxButton.OK,
                            MessageBoxImage.Warning);
                    }
                });
            }
            catch (Exception ex)
            {
                Print($"Error in ShowValidationEnforcementModal: {ex.Message}");
            }
        }

        #endregion

        #region Chart Panel UI

        #endregion

        #region Task 8.6: Validation Mapping for ExecutionExporter

        /// <summary>
        /// Task 8.6: Updates the shared validation map when a position is marked
        /// Called by UI components after validation
        /// </summary>
        public void UpdateSharedValidationMap(string positionId, string validationStatus)
        {
            try
            {
                if (string.IsNullOrEmpty(positionId))
                    return;

                TradeValidationShared.SharedValidationMap.AddOrUpdate(
                    positionId, validationStatus, (key, oldValue) => validationStatus);

                Print($"Updated shared validation map: {positionId} -> {validationStatus}");
            }
            catch (Exception ex)
            {
                Print($"Error updating shared validation map: {ex.Message}");
            }
        }

        #endregion

        #region Task 8.2 & 8.3: Settings Properties

        /// <summary>
        /// Task 8.3: Enable Order Blocking Until Validation
        /// Default: true
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Order Blocking Until Validation",
                 Description = "Block new orders until stopped-out positions are validated",
                 GroupName = "Trade Feedback Settings",
                 Order = 1)]
        public bool EnableOrderBlocking { get; set; }

        /// <summary>
        /// Task 8.3: Validation Grace Period (0-300 seconds)
        /// Default: 0
        /// </summary>
        [NinjaScriptProperty]
        [Range(0, 300)]
        [Display(Name = "Validation Grace Period (seconds)",
                 Description = "Delay before blocking activates after position close (0-300 seconds)",
                 GroupName = "Trade Feedback Settings",
                 Order = 2)]
        public int GracePeriodSeconds { get; set; }

        /// <summary>
        /// Task 8.3: Bypass Validation for Automated Strategies
        /// Default: true
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Bypass Validation for Automated Strategies",
                 Description = "Allow automated strategy orders to bypass validation requirement",
                 GroupName = "Trade Feedback Settings",
                 Order = 4)]
        public bool BypassAutomatedStrategies { get; set; }

        /// <summary>
        /// Task 8.3: Enable Emergency Override Shortcut
        /// Default: true
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Emergency Override Shortcut",
                 Description = "Allow Ctrl+Shift override to bypass validation in emergencies",
                 GroupName = "Trade Feedback Settings",
                 Order = 5)]
        public bool EnableEmergencyOverride { get; set; }

        #endregion
    }


    #region ValidationEnforcementWindow

    /// <summary>
    /// Task 7.4 & 7.5: Modal window for validation enforcement
    /// Implements "Validate and Continue" workflow
    /// </summary>
    public class ValidationEnforcementWindow : Window
    {
        private List<PositionValidationEntry> unvalidatedPositions;
        private PositionValidationTracker tracker;
        private TradeFeedbackAddOn addOn;

        public ValidationEnforcementWindow(
            List<PositionValidationEntry> positions,
            PositionValidationTracker validationTracker,
            TradeFeedbackAddOn parentAddOn)
        {
            unvalidatedPositions = positions;
            tracker = validationTracker;
            addOn = parentAddOn;

            InitializeWindow();
        }

        private void InitializeWindow()
        {
            // Window properties
            Title = "Position Validation Required";
            Width = 450;
            Height = 400;
            WindowStyle = WindowStyle.ToolWindow;
            ResizeMode = ResizeMode.NoResize;
            Background = new SolidColorBrush(Color.FromRgb(30, 30, 30));

            // Main container
            var mainGrid = new Grid();
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            mainGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            // Header message
            var headerText = new TextBlock
            {
                Text = "Position validation required before placing new order",
                Foreground = Brushes.White,
                FontSize = 14,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(15, 15, 15, 10),
                TextWrapping = TextWrapping.Wrap
            };
            Grid.SetRow(headerText, 0);
            mainGrid.Children.Add(headerText);

            // Scrollable list of positions
            var scrollViewer = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Margin = new Thickness(15, 0, 15, 10)
            };

            var positionsStack = new StackPanel();
            foreach (var position in unvalidatedPositions.OrderByDescending(p => p.CloseTimestamp))
            {
                positionsStack.Children.Add(CreatePositionValidationPanel(position));
            }

            scrollViewer.Content = positionsStack;
            Grid.SetRow(scrollViewer, 1);
            mainGrid.Children.Add(scrollViewer);

            // Bottom buttons
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(15, 0, 15, 15)
            };

            var closeButton = new Button
            {
                Content = "Close",
                Width = 100,
                Height = 30,
                Margin = new Thickness(5),
                Background = new SolidColorBrush(Color.FromRgb(100, 100, 100)),
                Foreground = Brushes.White
            };
            closeButton.Click += (s, e) => { DialogResult = false; Close(); };
            buttonPanel.Children.Add(closeButton);

            Grid.SetRow(buttonPanel, 2);
            mainGrid.Children.Add(buttonPanel);

            Content = mainGrid;
        }

        private StackPanel CreatePositionValidationPanel(PositionValidationEntry position)
        {
            var panel = new StackPanel
            {
                Margin = new Thickness(0, 5, 0, 5),
                Background = new SolidColorBrush(Color.FromArgb(150, 50, 50, 50))
            };

            // Position info
            var infoPanel = new StackPanel
            {
                Margin = new Thickness(10, 10, 10, 5)
            };

            var instrumentText = new TextBlock
            {
                Text = position.Instrument,
                Foreground = Brushes.White,
                FontWeight = FontWeights.Bold,
                FontSize = 12
            };
            infoPanel.Children.Add(instrumentText);

            var detailsText = new TextBlock
            {
                Text = $"Closed: {position.CloseTimestamp:HH:mm:ss}  |  P&L: ${position.PnL:F2}",
                Foreground = position.PnL >= 0 ? Brushes.LimeGreen : Brushes.Red,
                FontSize = 11,
                Margin = new Thickness(0, 3, 0, 0)
            };
            infoPanel.Children.Add(detailsText);

            panel.Children.Add(infoPanel);

            // Validation buttons
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(10, 5, 10, 10)
            };

            var validButton = new Button
            {
                Content = "✓ Valid",
                Width = 80,
                Height = 28,
                Margin = new Thickness(5, 0, 5, 0),
                Background = new SolidColorBrush(Color.FromRgb(0, 150, 0)),
                Foreground = Brushes.White,
                Cursor = Cursors.Hand
            };
            validButton.Click += (s, e) => OnValidatePosition(position.PositionId, "Valid", panel);
            buttonPanel.Children.Add(validButton);

            var invalidButton = new Button
            {
                Content = "✗ Invalid",
                Width = 80,
                Height = 28,
                Margin = new Thickness(5, 0, 5, 0),
                Background = new SolidColorBrush(Color.FromRgb(180, 0, 0)),
                Foreground = Brushes.White,
                Cursor = Cursors.Hand
            };
            invalidButton.Click += (s, e) => OnValidatePosition(position.PositionId, "Invalid", panel);
            buttonPanel.Children.Add(invalidButton);

            panel.Children.Add(buttonPanel);

            return panel;
        }

        private void OnValidatePosition(string positionId, string status, StackPanel panel)
        {
            // Mark position as validated
            tracker.MarkValidated(positionId, status);

            // Task 8.6: Update shared validation map for ExecutionExporter
            addOn.UpdateSharedValidationMap(positionId, status);

            // Remove from unvalidated list
            unvalidatedPositions.RemoveAll(p => p.PositionId == positionId);

            // Remove panel from UI
            var parentStack = panel.Parent as StackPanel;
            if (parentStack != null)
            {
                parentStack.Children.Remove(panel);
            }

            // If all positions validated, close dialog
            if (unvalidatedPositions.Count == 0)
            {
                DialogResult = true;
                Close();
            }
        }
    }

    #endregion
}
