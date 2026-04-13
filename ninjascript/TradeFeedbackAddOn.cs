#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Threading;
using System.Xml.Serialization;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.AddOns
{
    /// <summary>
    /// TradeFeedbackAddOn - Interactive trade validation interface for NinjaTrader
    /// Allows traders to mark closed positions as Valid or Invalid
    /// Integrates with FuturesTradingLog application for performance analysis
    /// </summary>
    public class TradeFeedbackAddOn : NinjaTrader.NinjaScript.AddOnBase
    {
        #region Variables
        private PositionValidationTracker validationTracker;
        private string stateFilePath;
        private readonly object lockObject = new object();

        // Task 8.3: Settings variables with defaults
        private bool enableOrderBlocking = true;
        private int gracePeriodSeconds = 0;
        private bool autoShowPanelOnPositionClose = true;
        private bool bypassAutomatedStrategies = true;
        private bool enableEmergencyOverride = true;
        private int maxUnvalidatedPositionsToDisplay = 5;

        // Task 8.6: Shared static dictionary for validation mapping
        // This allows ExecutionExporter to read validation data when writing CSV
        public static ConcurrentDictionary<string, string> SharedValidationMap = new ConcurrentDictionary<string, string>();
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
                AutoShowPanelOnPositionClose = true;
                BypassAutomatedStrategies = true;
                EnableEmergencyOverride = true;
                MaxUnvalidatedPositionsToDisplay = 5;
            }
            else if (State == State.DataLoaded)
            {
                // Task 8.4: Apply settings to AddOn behavior
                enableOrderBlocking = EnableOrderBlocking;
                gracePeriodSeconds = GracePeriodSeconds;
                autoShowPanelOnPositionClose = AutoShowPanelOnPositionClose;
                bypassAutomatedStrategies = BypassAutomatedStrategies;
                enableEmergencyOverride = EnableEmergencyOverride;
                maxUnvalidatedPositionsToDisplay = MaxUnvalidatedPositionsToDisplay;

                // Initialize state file path
                var myDocuments = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                var baseDirectory = Path.Combine(myDocuments, "FuturesTradingLog");
                Directory.CreateDirectory(baseDirectory);
                stateFilePath = Path.Combine(baseDirectory, "trade_feedback_state.txt");

                // Initialize validation tracker
                validationTracker = LoadState(stateFilePath);

                // Subscribe to position update events for all accounts
                if (Account.All != null)
                {
                    foreach (Account account in Account.All)
                    {
                        if (account != null)
                        {
                            account.PositionUpdate += OnPositionUpdate;
                            account.OrderUpdate += OnOrderUpdate;
                        }
                    }
                }

                Print("TradeFeedbackAddOn initialized. State file: " + stateFilePath);
                Print($"Settings - Order blocking: {enableOrderBlocking}, Grace period: {gracePeriodSeconds}s, Auto-show panel: {autoShowPanelOnPositionClose}, Max display: {maxUnvalidatedPositionsToDisplay}");
            }
            else if (State == State.Terminated)
            {
                // Save state before shutdown
                SaveState(validationTracker, stateFilePath);

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
                    var pnl = e.Position.GetUnrealizedProfitLoss(PerformanceUnit.Currency);

                    // Generate position ID
                    var positionId = GeneratePositionId(entryTime, instrument, account);

                    // Add to validation tracker (require validation for stopped-out positions)
                    bool requiresValidation = pnl < 0; // Require validation for losses
                    validationTracker.AddPosition(positionId, entryTime, instrument, (decimal)pnl, requiresValidation);

                    Print($"Position closed: {instrument} P&L: {pnl:F2} - Requires validation: {requiresValidation}");

                    // Task 8.4: Show validation panel if position requires validation AND auto-show is enabled
                    if (requiresValidation && autoShowPanelOnPositionClose)
                    {
                        ShowValidationPanelForActiveCharts();
                    }
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
                if (bypassAutomatedStrategies && IsAutomatedOrder(e.Order))
                {
                    Print($"Order {e.Order.OrderId} bypassed validation (automated strategy)");
                    return;
                }

                // Task 8.4: Check for emergency override (from settings)
                if (enableEmergencyOverride && IsEmergencyOverrideActive())
                {
                    Print($"WARNING: Order {e.Order.OrderId} bypassed validation via emergency override (Ctrl+Shift)");
                    return;
                }

                // Get unvalidated positions for the order's instrument
                var unvalidatedPositions = validationTracker.GetUnvalidatedForInstrument(e.Order.Instrument?.FullName);

                // Task 8.4: Check grace period (from settings)
                unvalidatedPositions = FilterByGracePeriod(unvalidatedPositions);

                if (unvalidatedPositions.Count > 0)
                {
                    // Task 7.3: Alert user - order blocking
                    // Note: NinjaTrader AddOns cannot directly cancel orders
                    // Instead we alert the user to validate positions before trading
                    Print($"VALIDATION REQUIRED: {unvalidatedPositions.Count} unvalidated position(s) for {e.Order.Instrument?.FullName}");
                    Print($"Order detected: {e.Order.OrderId} - User should validate positions before proceeding");

                    // Task 7.4: Show validation enforcement modal
                    ShowValidationEnforcementModal(unvalidatedPositions, e.Order);
                }
            }
            catch (Exception ex)
            {
                Print($"Error in OnOrderUpdate: {ex.Message}");
            }
        }

        /// <summary>
        /// Task 7.7: Checks if an order is from an automated strategy
        /// </summary>
        private bool IsAutomatedOrder(Order order)
        {
            if (order == null) return false;

            // Check if order is marked as automated
            // Note: NinjaTrader 8 may not have IsAutomated property directly accessible
            // Check order name or from strategy
            if (order.FromEntrySignal != null && !string.IsNullOrEmpty(order.FromEntrySignal))
            {
                return true; // Order from strategy signal
            }

            return false;
        }

        /// <summary>
        /// Task 7.6: Checks if emergency override shortcut (Ctrl+Shift) is active
        /// </summary>
        private bool IsEmergencyOverrideActive()
        {
            try
            {
                // Check if both Ctrl and Shift are held down
                return (Keyboard.IsKeyDown(Key.LeftCtrl) || Keyboard.IsKeyDown(Key.RightCtrl)) &&
                       (Keyboard.IsKeyDown(Key.LeftShift) || Keyboard.IsKeyDown(Key.RightShift));
            }
            catch
            {
                // If keyboard check fails, assume no override
                return false;
            }
        }

        /// <summary>
        /// Task 7.8: Filters positions by grace period
        /// </summary>
        private Dictionary<string, PositionValidationEntry> FilterByGracePeriod(Dictionary<string, PositionValidationEntry> positions)
        {
            if (gracePeriodSeconds <= 0)
                return positions;

            var now = DateTime.Now;
            var filtered = new Dictionary<string, PositionValidationEntry>();

            foreach (var kvp in positions)
            {
                var timeSinceClose = (now - kvp.Value.CloseTimestamp).TotalSeconds;
                if (timeSinceClose >= gracePeriodSeconds)
                {
                    filtered[kvp.Key] = kvp.Value;
                }
                else
                {
                    var remaining = gracePeriodSeconds - (int)timeSinceClose;
                    Print($"Grace period active for {kvp.Value.Instrument}: {remaining}s remaining");
                }
            }

            return filtered;
        }

        /// <summary>
        /// Task 7.4: Shows validation enforcement modal dialog
        /// Task 7.5: Implements "Validate and Continue" workflow
        /// </summary>
        private void ShowValidationEnforcementModal(Dictionary<string, PositionValidationEntry> unvalidatedPositions, Order blockedOrder)
        {
            try
            {
                // Execute on UI thread
                Application.Current?.Dispatcher.InvokeAsync(() =>
                {
                    try
                    {
                        // Create custom WPF window for validation enforcement
                        var modal = new ValidationEnforcementWindow(unvalidatedPositions, validationTracker, blockedOrder, this);
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
                        var positionList = string.Join("\n", unvalidatedPositions.Values.Select(p =>
                            $"{p.Instrument}: {p.PnL:F2}"));

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

        /// <summary>
        /// Shows validation panel on all active chart windows
        /// </summary>
        private void ShowValidationPanelForActiveCharts()
        {
            try
            {
                // This would need to iterate through active chart windows
                // For now, this is a placeholder for the UI integration
                // Actual implementation would require accessing ChartControl instances
                Print("Validation panel would be shown on active charts");
            }
            catch (Exception ex)
            {
                Print($"Error showing validation panel: {ex.Message}");
            }
        }

        /// <summary>
        /// Creates or retrieves validation panel for a chart window
        /// </summary>
        // Removed: ChartWindow not available in NinjaTrader AddOn context
        // Chart panel UI will be implemented as a separate tool window instead

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

                // Update the shared static dictionary
                SharedValidationMap.AddOrUpdate(positionId, validationStatus, (key, oldValue) => validationStatus);

                Print($"Updated shared validation map: {positionId} -> {validationStatus}");
            }
            catch (Exception ex)
            {
                Print($"Error updating shared validation map: {ex.Message}");
            }
        }

        #endregion

        #region State Persistence

        /// <summary>
        /// Saves validation tracker state to text file
        /// </summary>
        public static void SaveState(PositionValidationTracker tracker, string filePath)
        {
            try
            {
                var state = tracker.SerializeToText();
                File.WriteAllText(filePath, state, Encoding.UTF8);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error saving state: {ex.Message}");
            }
        }

        /// <summary>
        /// Loads validation tracker state from text file
        /// Returns new empty tracker if file doesn't exist
        /// </summary>
        public static PositionValidationTracker LoadState(string filePath)
        {
            try
            {
                if (File.Exists(filePath))
                {
                    var text = File.ReadAllText(filePath, Encoding.UTF8);
                    return PositionValidationTracker.DeserializeFromText(text);
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error loading state: {ex.Message}");
            }

            // Return new empty tracker if file doesn't exist or error occurred
            return new PositionValidationTracker();
        }

        #endregion

        #region Utility Methods

        /// <summary>
        /// Generates a unique composite position ID from entry time, instrument, and account
        /// Format: YYYY-MM-DDTHH:mm:ss_INSTRUMENT_ACCOUNT
        /// </summary>
        public static string GeneratePositionId(DateTime entryTime, string instrument, string account)
        {
            return $"{entryTime:yyyy-MM-ddTHH:mm:ss}_{instrument}_{account}";
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
        /// Task 8.3: Auto-Show Panel on Position Close
        /// Default: true
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Auto-Show Panel on Position Close",
                 Description = "Automatically display validation panel when a position closes",
                 GroupName = "Trade Feedback Settings",
                 Order = 3)]
        public bool AutoShowPanelOnPositionClose { get; set; }

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

        /// <summary>
        /// Task 8.3: Maximum Unvalidated Positions to Display (1-10)
        /// Default: 5
        /// </summary>
        [NinjaScriptProperty]
        [Range(1, 10)]
        [Display(Name = "Maximum Unvalidated Positions to Display",
                 Description = "Maximum number of positions shown in validation panel (1-10)",
                 GroupName = "Trade Feedback Settings",
                 Order = 6)]
        public int MaxUnvalidatedPositionsToDisplay { get; set; }

        #endregion
    }

    #region PositionValidationTracker Class

    /// <summary>
    /// Thread-safe tracker for position validation status
    /// Manages validation state for closed positions
    /// </summary>
    public class PositionValidationTracker
    {
        private Dictionary<string, PositionValidationEntry> positions;
        private readonly object lockObject = new object();

        public PositionValidationTracker()
        {
            positions = new Dictionary<string, PositionValidationEntry>();
        }

        /// <summary>
        /// Adds a position to the tracker
        /// </summary>
        public void AddPosition(string positionId, DateTime closeTimestamp, string instrument, decimal pnl, bool requiresValidation)
        {
            lock (lockObject)
            {
                if (!positions.ContainsKey(positionId))
                {
                    positions[positionId] = new PositionValidationEntry
                    {
                        PositionId = positionId,
                        CloseTimestamp = closeTimestamp,
                        Instrument = instrument,
                        PnL = pnl,
                        RequiresValidation = requiresValidation,
                        ValidationStatus = null
                    };
                }
            }
        }

        /// <summary>
        /// Marks a position as validated with the given status
        /// </summary>
        public void MarkValidated(string positionId, string validationStatus)
        {
            lock (lockObject)
            {
                if (positions.ContainsKey(positionId))
                {
                    positions[positionId].ValidationStatus = validationStatus;
                    positions[positionId].RequiresValidation = false;
                }
            }
        }

        /// <summary>
        /// Gets all positions that require validation
        /// </summary>
        public Dictionary<string, PositionValidationEntry> GetUnvalidated()
        {
            lock (lockObject)
            {
                return positions
                    .Where(p => p.Value.RequiresValidation)
                    .ToDictionary(p => p.Key, p => p.Value);
            }
        }

        /// <summary>
        /// Gets unvalidated positions for a specific instrument
        /// </summary>
        public Dictionary<string, PositionValidationEntry> GetUnvalidatedForInstrument(string instrument)
        {
            lock (lockObject)
            {
                return positions
                    .Where(p => p.Value.RequiresValidation && p.Value.Instrument == instrument)
                    .ToDictionary(p => p.Key, p => p.Value);
            }
        }

        /// <summary>
        /// Checks if a position requires validation
        /// </summary>
        public bool RequiresValidation(string positionId)
        {
            lock (lockObject)
            {
                return positions.ContainsKey(positionId) && positions[positionId].RequiresValidation;
            }
        }

        /// <summary>
        /// Serializes tracker state to simple text format
        /// </summary>
        public string SerializeToText()
        {
            lock (lockObject)
            {
                StringBuilder sb = new StringBuilder();
                foreach (var entry in positions.Values)
                {
                    sb.AppendLine($"{entry.PositionId}|{entry.CloseTimestamp:o}|{entry.Instrument}|{entry.PnL}|{entry.ValidationStatus}|{entry.RequiresValidation}");
                }
                return sb.ToString();
            }
        }

        /// <summary>
        /// Deserializes tracker state from simple text format
        /// </summary>
        public static PositionValidationTracker DeserializeFromText(string text)
        {
            var tracker = new PositionValidationTracker();

            if (string.IsNullOrWhiteSpace(text))
                return tracker;

            string[] lines = text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);

            foreach (string line in lines)
            {
                string[] parts = line.Split('|');
                if (parts.Length == 6)
                {
                    string positionId = parts[0];
                    DateTime closeTimestamp = DateTime.Parse(parts[1]);
                    string instrument = parts[2];
                    decimal pnl = (decimal)double.Parse(parts[3]);
                    bool requiresValidation = bool.Parse(parts[5]);

                    tracker.AddPosition(positionId, closeTimestamp, instrument, pnl, requiresValidation);

                    // Set validation status if present
                    string validationStatus = parts[4];
                    if (!string.IsNullOrEmpty(validationStatus) && validationStatus != "None")
                    {
                        tracker.MarkValidated(positionId, validationStatus);
                    }
                }
            }

            return tracker;
        }
    }

    /// <summary>
    /// Represents a single position validation entry
    /// </summary>
    public class PositionValidationEntry
    {
        public string PositionId { get; set; }
        public DateTime CloseTimestamp { get; set; }
        public string Instrument { get; set; }
        public decimal PnL { get; set; }
        public bool RequiresValidation { get; set; }
        public string ValidationStatus { get; set; } // "Valid", "Invalid", or null
    }

    #endregion

    #region ValidationPanel WPF UI Class

    /// <summary>
    /// WPF panel for displaying and interacting with position validation UI
    /// Positioned on right edge of chart window
    /// </summary>
    public class ValidationPanel
    {
        private StackPanel mainPanel;
        private ScrollViewer scrollViewer;
        private PositionValidationTracker tracker;
        private TradeFeedbackAddOn addOn;
        private bool isVisible;
        private int maxVisiblePositions;
        private const double PositionEntryHeight = 120.0;

        public ValidationPanel(PositionValidationTracker validationTracker, TradeFeedbackAddOn parentAddOn, int maxPositions)
        {
            tracker = validationTracker;
            addOn = parentAddOn;
            isVisible = false;
            maxVisiblePositions = maxPositions; // Task 8.4: Use setting value

            CreatePanelUI();
        }

        /// <summary>
        /// Creates the WPF panel structure
        /// </summary>
        private void CreatePanelUI()
        {
            // Create main container panel
            mainPanel = new StackPanel
            {
                Width = 150,
                Background = new SolidColorBrush(Color.FromArgb(200, 30, 30, 30)), // Semi-transparent dark background
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 50, 10, 0),
                Opacity = 0 // Start hidden for animation
            };

            // Create scroll viewer for position list with auto-scroll
            scrollViewer = new ScrollViewer
            {
                MaxHeight = maxVisiblePositions * PositionEntryHeight,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Hidden
            };

            // Container for position entries
            var positionsStack = new StackPanel();
            scrollViewer.Content = positionsStack;

            mainPanel.Children.Add(scrollViewer);

            // Initially collapsed
            mainPanel.Visibility = Visibility.Collapsed;
        }

        /// <summary>
        /// Updates panel with current unvalidated positions
        /// </summary>
        public void RefreshPositions()
        {
            if (mainPanel == null) return;

            var positionsStack = (StackPanel)scrollViewer.Content;
            positionsStack.Children.Clear();

            var unvalidated = tracker.GetUnvalidated();

            if (unvalidated.Count == 0)
            {
                // Fade out and collapse panel when no positions need validation
                CollapsePanel();
                return;
            }

            // Show and expand panel with animation
            ExpandPanel();

            // Add position entries (most recent first)
            foreach (var position in unvalidated.OrderByDescending(p => p.Value.CloseTimestamp))
            {
                var entryPanel = CreatePositionEntry(position.Value);
                positionsStack.Children.Add(entryPanel);
            }

            // Auto-scroll to top when new positions added
            scrollViewer.ScrollToTop();
        }

        /// <summary>
        /// Creates UI for a single position entry
        /// </summary>
        private StackPanel CreatePositionEntry(PositionValidationEntry position)
        {
            var entryPanel = new StackPanel
            {
                Margin = new Thickness(5),
                Background = new SolidColorBrush(Color.FromArgb(100, 50, 50, 50))
            };

            // Instrument symbol display
            var instrumentLabel = new TextBlock
            {
                Text = position.Instrument,
                Foreground = Brushes.White,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(5, 5, 5, 2)
            };
            entryPanel.Children.Add(instrumentLabel);

            // Entry/Exit time in HH:mm format
            var timeLabel = new TextBlock
            {
                Text = position.CloseTimestamp.ToString("HH:mm"),
                Foreground = Brushes.LightGray,
                FontSize = 10,
                Margin = new Thickness(5, 0, 5, 2)
            };
            entryPanel.Children.Add(timeLabel);

            // P&L with color coding: green for profit, red for loss
            var pnlLabel = new TextBlock
            {
                Text = $"P&L: ${position.PnL:F2}",
                Foreground = position.PnL >= 0 ? Brushes.LimeGreen : Brushes.Red,
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(5, 0, 5, 5)
            };
            entryPanel.Children.Add(pnlLabel);

            // Button container - Valid/Invalid buttons side-by-side
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(5)
            };

            // Valid button: green background, white text
            var validButton = new Button
            {
                Content = "✓ Valid",
                Background = new SolidColorBrush(Color.FromRgb(0, 150, 0)),
                Foreground = Brushes.White,
                Width = 60,
                Margin = new Thickness(2),
                Cursor = Cursors.Hand
            };
            validButton.Click += (s, e) => OnValidButtonClick(position.PositionId);
            buttonPanel.Children.Add(validButton);

            // Invalid button: red background, white text
            var invalidButton = new Button
            {
                Content = "✗ Invalid",
                Background = new SolidColorBrush(Color.FromRgb(180, 0, 0)),
                Foreground = Brushes.White,
                Width = 60,
                Margin = new Thickness(2),
                Cursor = Cursors.Hand
            };
            invalidButton.Click += (s, e) => OnInvalidButtonClick(position.PositionId);
            buttonPanel.Children.Add(invalidButton);

            entryPanel.Children.Add(buttonPanel);

            return entryPanel;
        }

        /// <summary>
        /// Handles Valid button click
        /// Updates tracker, logs action, and removes position from UI
        /// </summary>
        private void OnValidButtonClick(string positionId)
        {
            // Update validation tracker to "Valid"
            tracker.MarkValidated(positionId, "Valid");

            // Task 8.6: Update shared validation map for ExecutionExporter
            addOn.UpdateSharedValidationMap(positionId, "Valid");

            // Log validation action to NinjaTrader output window
            System.Diagnostics.Debug.WriteLine($"Position {positionId} marked as Valid");

            // Remove position from UI panel by refreshing
            RefreshPositions();
        }

        /// <summary>
        /// Handles Invalid button click
        /// Updates tracker, logs action, and removes position from UI
        /// </summary>
        private void OnInvalidButtonClick(string positionId)
        {
            // Update validation tracker to "Invalid"
            tracker.MarkValidated(positionId, "Invalid");

            // Task 8.6: Update shared validation map for ExecutionExporter
            addOn.UpdateSharedValidationMap(positionId, "Invalid");

            // Log validation action to NinjaTrader output window
            System.Diagnostics.Debug.WriteLine($"Position {positionId} marked as Invalid");

            // Remove position from UI panel by refreshing
            RefreshPositions();
        }

        /// <summary>
        /// Expands panel with smooth fade-in animation
        /// </summary>
        private void ExpandPanel()
        {
            if (mainPanel == null) return;

            mainPanel.Visibility = Visibility.Visible;

            // Create fade-in animation
            var fadeIn = new DoubleAnimation
            {
                From = 0,
                To = 1,
                Duration = TimeSpan.FromMilliseconds(300),
                EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }
            };

            mainPanel.BeginAnimation(UIElement.OpacityProperty, fadeIn);
            isVisible = true;
        }

        /// <summary>
        /// Collapses panel with smooth fade-out animation
        /// </summary>
        private void CollapsePanel()
        {
            if (mainPanel == null) return;

            // Create fade-out animation
            var fadeOut = new DoubleAnimation
            {
                From = 1,
                To = 0,
                Duration = TimeSpan.FromMilliseconds(300),
                EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseIn }
            };

            fadeOut.Completed += (s, e) =>
            {
                // Collapse to minimal width after fade-out
                mainPanel.Visibility = Visibility.Collapsed;
            };

            mainPanel.BeginAnimation(UIElement.OpacityProperty, fadeOut);
            isVisible = false;
        }

        /// <summary>
        /// Toggles panel visibility
        /// </summary>
        public void ToggleVisibility()
        {
            if (mainPanel == null) return;

            if (isVisible)
            {
                CollapsePanel();
            }
            else
            {
                RefreshPositions();
            }
        }

        /// <summary>
        /// Gets the main WPF panel
        /// </summary>
        public StackPanel GetPanel()
        {
            return mainPanel;
        }

        /// <summary>
        /// Cleanup resources
        /// </summary>
        public void Cleanup()
        {
            if (mainPanel != null)
            {
                mainPanel.Children.Clear();
                mainPanel = null;
            }
        }
    }

    #endregion

    #region ValidationEnforcementWindow

    /// <summary>
    /// Task 7.4 & 7.5: Modal window for validation enforcement
    /// Implements "Validate and Continue" workflow
    /// </summary>
    public class ValidationEnforcementWindow : Window
    {
        private Dictionary<string, PositionValidationEntry> unvalidatedPositions;
        private PositionValidationTracker tracker;
        private Order blockedOrder;
        private TradeFeedbackAddOn addOn;

        public ValidationEnforcementWindow(
            Dictionary<string, PositionValidationEntry> positions,
            PositionValidationTracker validationTracker,
            Order order,
            TradeFeedbackAddOn parentAddOn)
        {
            unvalidatedPositions = positions;
            tracker = validationTracker;
            blockedOrder = order;
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
            foreach (var position in unvalidatedPositions.Values.OrderByDescending(p => p.CloseTimestamp))
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
            unvalidatedPositions.Remove(positionId);

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
