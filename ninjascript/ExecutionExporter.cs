#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Security;
using System.Text;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.DrawingTools;
#endregion

//This namespace holds Indicators in this folder and is required. Do not change it.
namespace NinjaTrader.NinjaScript.Indicators
{
    /// <summary>
    /// ExecutionExporter - Automatically exports trade executions to CSV format
    /// Compatible with FuturesTradingLog application
    /// Task 8.5-8.7: Extended with TradeValidation column support
    /// </summary>
    public class ExecutionExporter : Indicator
    {
        #region Variables
        private StreamWriter streamWriter;
        private string exportFilePath;
        private string exportDirectory;
        private DateTime currentFileDate;
        private readonly object lockObject = new object();
        private HashSet<string> exportedExecutions;
        private Dictionary<string, int> positionTracker;
        private TimeZoneInfo pacificTimeZone;

        // Trade Validation Tracking (optional feature)
        private PositionValidationTracker validationTracker;
        private string validationStateFilePath;
        private ValidationPanel validationPanel;
        private System.Windows.Controls.Grid chartGrid;
        public static ConcurrentDictionary<string, string> SharedValidationMap = new ConcurrentDictionary<string, string>();

        // Position closure tracking - maps (Date_Instrument_Account) to closure time
        private static ConcurrentDictionary<string, DateTime> PositionClosureMap = new ConcurrentDictionary<string, DateTime>();

        // Queued unvalidated positions (when blocking is disabled)
        public static ConcurrentDictionary<string, int> QueuedPositionsMap = new ConcurrentDictionary<string, int>();
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description                     = @"Automatically exports trade executions to CSV format for FuturesTradingLog application";
                Name                           = "ExecutionExporter";
                Calculate                      = Calculate.OnBarClose;
                IsOverlay                      = false;
                DisplayInDataBox               = true;
                DrawOnPricePanel              = false;
                DrawHorizontalGridLines       = true;
                DrawVerticalGridLines         = true;
                PaintPriceMarkers             = true;
                ScaleJustification            = NinjaTrader.Gui.Chart.ScaleJustification.Right;
                IsSuspendedWhileInactive      = false;

                // Default settings - use user's Documents folder for cross-platform compatibility
                ExportPath                    = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "FuturesTradingLog", "data");
                CreateDailyFiles              = true;
                MaxFileSizeMB                 = 10;
                EnableLogging                 = true;
                UseSessionCloseDate           = true;
                SessionStartHourPT            = 15; // 3pm Pacific Time

                // Validation tracking defaults
                EnableValidationTracking      = true;   // Enable by default for validation panel
                EnableOrderBlocking           = true;   // Actually cancels orders when validation required
                GracePeriodSeconds            = 0;
                BypassAutomatedStrategies     = true;
                EnableEmergencyOverride       = true;
            }
            else if (State == State.DataLoaded)
            {
                // Initialize collections
                exportedExecutions = new HashSet<string>();
                positionTracker = new Dictionary<string, int>();

                // Initialize Pacific timezone
                try
                {
                    pacificTimeZone = TimeZoneInfo.FindSystemTimeZoneById("Pacific Standard Time");
                    LogMessage("Pacific timezone initialized successfully");
                }
                catch (Exception ex)
                {
                    LogError($"Failed to initialize Pacific timezone: {ex.Message}. Will use server time as fallback.");
                    pacificTimeZone = null;
                }

                // Setup export directory
                SetupExportDirectory();

                // Initialize validation tracking if enabled
                if (EnableValidationTracking)
                {
                    try
                    {
                        var myDocuments = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                        var baseDirectory = Path.Combine(myDocuments, "FuturesTradingLog");
                        Directory.CreateDirectory(baseDirectory);
                        validationStateFilePath = Path.Combine(baseDirectory, "trade_validation_state.txt");

                        // Load validation state
                        validationTracker = LoadValidationState(validationStateFilePath);

                        // Populate SharedValidationMap from loaded validation data
                        var validatedPositions = validationTracker.GetValidatedPositions();
                        foreach (var entry in validatedPositions)
                        {
                            SharedValidationMap.AddOrUpdate(
                                entry.PositionId,
                                entry.ValidationStatus,
                                (key, oldValue) => entry.ValidationStatus
                            );
                        }

                        LogMessage($"Validation tracking enabled. State file: {validationStateFilePath}");
                        LogMessage($"Loaded {validatedPositions.Count} validated positions into SharedValidationMap");
                        LogMessage($"Order blocking: {(EnableOrderBlocking ? "ENABLED" : "DISABLED")}, Grace period: {GracePeriodSeconds}s");
                    }
                    catch (Exception ex)
                    {
                        LogError($"Failed to initialize validation tracking: {ex.Message}");
                    }
                }
            }
            else if (State == State.Historical)
            {
                // Initialize validation panel UI on chart
                if (EnableValidationTracking)
                {
                    if (ChartControl != null)
                    {
                        try
                        {
                            ChartControl.Dispatcher.InvokeAsync(() =>
                            {
                                try
                                {
                                    // Create validation panel
                                    validationPanel = new ValidationPanel(validationTracker, this, 5);
                                    Print("✓ Validation panel created");

                                    // Get panel and set high Z-index to ensure visibility
                                    var panel = validationPanel.GetPanel();
                                    System.Windows.Controls.Panel.SetZIndex(panel, 1000);

                                    // Find chart grid and add panel
                                    if (ChartControl.Parent is System.Windows.Controls.Grid grid)
                                    {
                                        chartGrid = grid;
                                        grid.Children.Add(panel);
                                        Print("✓ Validation panel added to chart grid");

                                        // Refresh to show any existing unvalidated positions
                                        validationPanel.RefreshPositions();
                                        Print($"✓ Panel initialized - unvalidated positions: {validationTracker.GetUnvalidated().Count}");
                                    }
                                    else
                                    {
                                        Print($"✗ ChartControl.Parent is {ChartControl.Parent?.GetType().Name ?? "null"}, not Grid");
                                    }
                                }
                                catch (Exception ex)
                                {
                                    Print($"✗ Panel add error: {ex.Message}");
                                    Print($"✗ Stack: {ex.StackTrace}");
                                }
                            });
                        }
                        catch (Exception ex)
                        {
                            Print($"✗ Panel init error: {ex.Message}");
                        }
                    }
                    else
                    {
                        Print("✗ ChartControl is null - panel cannot be added");
                    }
                }

                // Subscribe to execution events for all accounts
                if (Account.All != null)
                {
                    foreach (Account account in Account.All)
                    {
                        if (account != null)
                        {
                            account.ExecutionUpdate += OnExecutionUpdate;

                            // Subscribe to order events if order blocking is enabled
                            if (EnableValidationTracking && EnableOrderBlocking)
                            {
                                account.OrderUpdate += OnOrderUpdate;
                            }
                        }
                    }
                }

                Print($"ExecutionExporter initialized. Export path: {exportDirectory}");
                Print($"Session date mode: {(UseSessionCloseDate ? "ENABLED - Using session close date logic" : "DISABLED - Using legacy current date logic")}");
                Print($"UseSessionCloseDate: {UseSessionCloseDate}, SessionStartHourPT: {SessionStartHourPT}");
                if (EnableValidationTracking)
                {
                    Print($"Validation tracking: ENABLED (Order blocking: {(EnableOrderBlocking ? "ON" : "OFF")})");
                }
            }
            else if (State == State.Terminated)
            {
                // Remove validation panel from chart
                if (validationPanel != null && chartGrid != null)
                {
                    try
                    {
                        ChartControl?.Dispatcher?.InvokeAsync(() =>
                        {
                            try
                            {
                                chartGrid.Children.Remove(validationPanel.GetPanel());
                                validationPanel.Cleanup();
                                validationPanel = null;
                                LogMessage("✓ Validation panel removed from chart");
                            }
                            catch (Exception ex)
                            {
                                LogError($"Error removing validation panel: {ex.Message}");
                            }
                        });
                    }
                    catch (Exception ex)
                    {
                        LogError($"Error in panel cleanup: {ex.Message}");
                    }
                }

                // Save validation state before cleanup
                if (EnableValidationTracking && validationTracker != null)
                {
                    SaveValidationState(validationTracker, validationStateFilePath);
                    LogMessage("Validation state saved");
                }

                // Cleanup
                CleanupResources();

                // Unsubscribe from events
                if (Account.All != null)
                {
                    foreach (Account account in Account.All)
                    {
                        if (account != null)
                        {
                            account.ExecutionUpdate -= OnExecutionUpdate;

                            // Unsubscribe from order events if we subscribed
                            if (EnableValidationTracking && EnableOrderBlocking)
                            {
                                account.OrderUpdate -= OnOrderUpdate;
                            }
                        }
                    }
                }
            }
        }

        #region Timezone Conversion and Session Date Calculation

        /// <summary>
        /// Converts server time to Pacific Time
        /// </summary>
        /// <param name="serverTime">The server time to convert</param>
        /// <returns>Pacific Time equivalent</returns>
        public DateTime ConvertToPacificTime(DateTime serverTime)
        {
            try
            {
                if (pacificTimeZone != null)
                {
                    return TimeZoneInfo.ConvertTime(serverTime, pacificTimeZone);
                }
                else
                {
                    LogError("Pacific timezone not initialized. Using server time fallback due to timezone conversion error.");
                    return serverTime;
                }
            }
            catch (Exception ex)
            {
                LogError($"Timezone conversion failed: {ex.Message}. Using server time fallback due to timezone conversion error.");
                return serverTime;
            }
        }

        /// <summary>
        /// Converts server time to Pacific Time with explicit fallback handling
        /// Used primarily for testing
        /// </summary>
        /// <param name="serverTime">The server time to convert</param>
        /// <param name="timezone">The timezone to use (null triggers fallback)</param>
        /// <returns>Pacific Time equivalent or server time if conversion fails</returns>
        public DateTime ConvertToPacificTimeWithFallback(DateTime serverTime, TimeZoneInfo timezone)
        {
            try
            {
                if (timezone != null)
                {
                    return TimeZoneInfo.ConvertTime(serverTime, timezone);
                }
                else
                {
                    LogError("Timezone is null. Using server time fallback due to timezone conversion error.");
                    return serverTime;
                }
            }
            catch (Exception ex)
            {
                LogError($"Timezone conversion failed: {ex.Message}. Using server time fallback due to timezone conversion error.");
                return serverTime;
            }
        }

        /// <summary>
        /// Calculates the session closing date based on Pacific Time
        /// After 3pm PT (or configured hour): Use next day's date
        /// Before 3pm PT: Use current day's date
        /// </summary>
        /// <param name="pacificTime">Current time in Pacific timezone</param>
        /// <returns>Session closing date</returns>
        public DateTime CalculateSessionCloseDate(DateTime pacificTime)
        {
            DateTime sessionCloseDate;

            if (pacificTime.Hour >= SessionStartHourPT)
            {
                // After session start hour (e.g., 3pm PT) - use next day
                sessionCloseDate = pacificTime.AddDays(1).Date;
            }
            else
            {
                // Before session start hour - use current day
                sessionCloseDate = pacificTime.Date;
            }

            if (EnableLogging)
            {
                LogMessage($"Session date calculation - Pacific Time: {pacificTime:yyyy-MM-dd HH:mm:ss}, Session Close Date: {sessionCloseDate:yyyy-MM-dd}");
            }

            return sessionCloseDate;
        }

        /// <summary>
        /// Validates that the calculated session date is within reasonable bounds
        /// Logs warning if date seems incorrect but continues with calculated date
        /// </summary>
        /// <param name="calculatedDate">The calculated session close date</param>
        /// <param name="pacificNow">Current Pacific Time for validation context</param>
        /// <returns>True if date is valid, false if validation warning occurred</returns>
        public bool ValidateSessionDate(DateTime calculatedDate, DateTime pacificNow)
        {
            var daysDifference = (calculatedDate.Date - pacificNow.Date).Days;

            // Check if date is more than 1 day in the past
            if (daysDifference < -1)
            {
                LogError($"Date validation warning: Calculated date {calculatedDate:yyyy-MM-dd} is {Math.Abs(daysDifference)} days in the past (Pacific Now: {pacificNow:yyyy-MM-dd HH:mm:ss})");
                return false;
            }

            // Check if date is more than 2 days in the future
            if (daysDifference > 2)
            {
                LogError($"Date validation warning: Calculated date {calculatedDate:yyyy-MM-dd} is {daysDifference} days in the future (Pacific Now: {pacificNow:yyyy-MM-dd HH:mm:ss})");
                return false;
            }

            return true;
        }

        /// <summary>
        /// Gets the session closing date based on current time
        /// Handles timezone conversion and date calculation
        /// </summary>
        /// <returns>Session closing date to use for file naming</returns>
        private DateTime GetSessionCloseDate()
        {
            DateTime sessionCloseDate;

            if (UseSessionCloseDate)
            {
                // Get current server time
                DateTime serverTime = Core.Globals.Now;

                if (EnableLogging)
                {
                    LogMessage($"Server time: {serverTime:yyyy-MM-dd HH:mm:ss} ({TimeZoneInfo.Local.DisplayName})");
                }

                // Convert to Pacific Time
                DateTime pacificTime = ConvertToPacificTime(serverTime);

                if (EnableLogging)
                {
                    LogMessage($"Pacific time: {pacificTime:yyyy-MM-dd HH:mm:ss}");
                }

                // Calculate session closing date
                sessionCloseDate = CalculateSessionCloseDate(pacificTime);

                // Validate the date
                ValidateSessionDate(sessionCloseDate, pacificTime);
            }
            else
            {
                // Legacy mode: use current date
                sessionCloseDate = DateTime.Now.Date;

                if (EnableLogging)
                {
                    LogMessage($"Using legacy date logic (UseSessionCloseDate=false): {sessionCloseDate:yyyy-MM-dd}");
                }
            }

            return sessionCloseDate;
        }

        #endregion

        #region File Export and Path Management

        /// <summary>
        /// Generates the export filename based on session close date
        /// Format: NinjaTrader_Executions_YYYYMMDD.csv
        /// </summary>
        /// <param name="sessionCloseDate">The session closing date for the file</param>
        /// <returns>Filename string (without path)</returns>
        public string GenerateExportFilename(DateTime sessionCloseDate)
        {
            return string.Format("NinjaTrader_Executions_{0:yyyyMMdd}.csv", sessionCloseDate);
        }

        /// <summary>
        /// Constructs the full export file path
        /// </summary>
        /// <param name="exportDir">Export directory path</param>
        /// <param name="filename">Export filename</param>
        /// <returns>Full file path</returns>
        public string ConstructExportFilePath(string exportDir, string filename)
        {
            // Validate export directory exists
            if (!Directory.Exists(exportDir))
            {
                Directory.CreateDirectory(exportDir);
                LogMessage($"Created export directory: {exportDir}");
            }

            return Path.Combine(exportDir, filename);
        }

        /// <summary>
        /// Writes data to file with retry logic for transient failures
        /// </summary>
        /// <param name="filePath">Full path to the file</param>
        /// <param name="data">Data to write</param>
        /// <param name="append">Whether to append or overwrite</param>
        private void WriteToFileWithRetry(string filePath, string data, bool append)
        {
            int maxRetries = 3;
            int retryDelayMs = 1000;

            for (int attempt = 1; attempt <= maxRetries; attempt++)
            {
                try
                {
                    File.AppendAllText(filePath, data);
                    return; // Success
                }
                catch (IOException ex)
                {
                    if (attempt < maxRetries)
                    {
                        LogError($"File write attempt {attempt} failed (IOException): {ex.Message}. Retrying in {retryDelayMs}ms...");
                        Thread.Sleep(retryDelayMs);
                    }
                    else
                    {
                        LogError($"File write failed after {maxRetries} attempts (IOException): Path={filePath}, Error={ex.Message}");
                        throw;
                    }
                }
                catch (SecurityException ex)
                {
                    LogError($"File write failed (SecurityException): Permission denied for path {filePath}. Error: {ex.Message}. Please check folder permissions.");
                    throw;
                }
                catch (UnauthorizedAccessException ex)
                {
                    LogError($"File write failed (UnauthorizedAccessException): Access denied for path {filePath}. Error: {ex.Message}. Please check folder permissions.");
                    throw;
                }
                catch (Exception ex)
                {
                    LogError($"File write failed (Unexpected error): Type={ex.GetType().Name}, Path={filePath}, Error={ex.Message}");
                    throw;
                }
            }
        }

        #endregion

        private void SetupExportDirectory()
        {
            try
            {
                exportDirectory = ExportPath;

                if (!Directory.Exists(exportDirectory))
                {
                    Directory.CreateDirectory(exportDirectory);
                    LogMessage($"Created export directory: {exportDirectory}");
                }

                // Create subdirectories
                var exportedDir = Path.Combine(exportDirectory, "exported");
                var logsDir = Path.Combine(exportDirectory, "logs");

                if (!Directory.Exists(exportedDir))
                    Directory.CreateDirectory(exportedDir);

                if (!Directory.Exists(logsDir))
                    Directory.CreateDirectory(logsDir);

                // Initialize first file
                CreateNewExportFile();
            }
            catch (Exception ex)
            {
                LogError($"Error setting up export directory: {ex.Message}");
            }
        }

        private void CreateNewExportFile()
        {
            try
            {
                lock (lockObject)
                {
                    // Close existing file if open
                    if (streamWriter != null)
                    {
                        streamWriter.Close();
                        streamWriter.Dispose();

                        // Only move completed files to exported directory if not using daily files
                        // Daily files should remain in place for continued appending
                        if (!CreateDailyFiles && File.Exists(exportFilePath))
                        {
                            var existingFileName = Path.GetFileName(exportFilePath);
                            var exportedPath = Path.Combine(exportDirectory, "exported", existingFileName);
                            File.Move(exportFilePath, exportedPath);
                            LogMessage($"Moved completed file to: {exportedPath}");
                        }
                    }

                    // Generate new file name using session close date logic
                    DateTime fileDate = GetSessionCloseDate();
                    currentFileDate = fileDate;

                    string fileName;
                    if (CreateDailyFiles)
                    {
                        // Use session close date for daily files
                        fileName = GenerateExportFilename(fileDate);
                    }
                    else
                    {
                        // Use timestamp for time-based rotation
                        var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                        fileName = $"NinjaTrader_Executions_{timestamp}.csv";
                    }

                    exportFilePath = ConstructExportFilePath(exportDirectory, fileName);

                    if (EnableLogging)
                    {
                        LogMessage($"Export filename: {fileName}");
                    }

                    // Check if file already exists (for daily files)
                    bool fileExists = File.Exists(exportFilePath);

                    // Create or append to file
                    streamWriter = new StreamWriter(exportFilePath, append: fileExists, Encoding.UTF8);

                    // Only write header if file is new
                    if (!fileExists)
                    {
                        WriteCSVHeader();
                    }

                    streamWriter.Flush();

                    if (fileExists)
                    {
                        LogMessage($"Reopened existing daily file: {fileName}");
                    }
                    else
                    {
                        LogMessage($"Created new export file: {fileName}");
                    }
                }
            }
            catch (Exception ex)
            {
                LogError($"Error creating new export file: {ex.Message}");
            }
        }

        /// <summary>
        /// Task 8.5: Writes CSV header with TradeValidation column
        /// </summary>
        private void WriteCSVHeader()
        {
            // Task 8.5: Added TradeValidation column to header
            const string header = "Instrument,Action,Quantity,Price,Time,ID,E/X,Position,Order ID,Name,Commission,Rate,Account,Connection,TradeValidation";
            streamWriter.WriteLine(header);
        }

        private void OnExecutionUpdate(object sender, ExecutionEventArgs e)
        {
            try
            {
                if (e?.Execution == null) return;
                if (e.Execution.Instrument?.MasterInstrument == null) return;
                if (e.Execution.Order == null) return;

                // Generate unique execution ID
                var executionId = GenerateExecutionId(e.Execution);

                // Check for duplicates
                if (exportedExecutions.Contains(executionId))
                    return;

                // Determine entry/exit status
                var entryExit = DetermineEntryExit(e.Execution);

                // Export the execution
                ExportExecution(e.Execution, executionId, entryExit);

                // Track exported execution
                exportedExecutions.Add(executionId);

                // Check if we need to rotate files
                CheckFileRotation();
            }
            catch (Exception ex)
            {
                LogError($"Error processing execution: {ex.Message}");
            }
        }

        private string GenerateExecutionId(Execution execution)
        {
            try
            {
                // Use NinjaTrader's built-in execution ID if available
                if (!string.IsNullOrEmpty(execution?.ExecutionId))
                    return execution.ExecutionId;

                // Fallback to creating unique ID using instrument + timestamp + order ID
                var instrument = execution?.Instrument?.MasterInstrument?.Name ?? "UNKNOWN";
                var timestamp = execution?.Time.Ticks.ToString() ?? DateTime.Now.Ticks.ToString();
                var orderId = execution?.Order?.Id.ToString() ?? "0";

                return $"{instrument}_{timestamp}_{orderId}";
            }
            catch (Exception ex)
            {
                LogError($"Error generating execution ID: {ex.Message}");
                return $"ERROR_{DateTime.Now.Ticks}";
            }
        }

        private string DetermineEntryExit(Execution execution)
        {
            try
            {
                // Track positions separately by account and instrument
                var accountName = execution.Account?.Name ?? "Unknown";
                var instrumentKey = $"{accountName}_{execution.Instrument.FullName}";

                // Initialize position tracking for this account+instrument combination
                if (!positionTracker.ContainsKey(instrumentKey))
                {
                    positionTracker[instrumentKey] = 0;
                    LogMessage($"Created new position tracker for key: {instrumentKey}");
                }

                var previousPosition = positionTracker[instrumentKey];
                LogMessage($"DetermineEntryExit - Key: {instrumentKey}, Previous Position: {previousPosition}, OrderAction: {execution.Order.OrderAction}");

                // Determine signed quantity based on order action
                // Buy/BuyToCover = positive, Sell/SellShort = negative
                int signedQuantity;
                if (execution.Order.OrderAction == OrderAction.Buy || execution.Order.OrderAction == OrderAction.BuyToCover)
                {
                    signedQuantity = Math.Abs(execution.Quantity);
                }
                else if (execution.Order.OrderAction == OrderAction.Sell || execution.Order.OrderAction == OrderAction.SellShort)
                {
                    signedQuantity = -Math.Abs(execution.Quantity);
                }
                else
                {
                    // Fallback for unknown order actions
                    signedQuantity = execution.Quantity;
                }

                var newPosition = previousPosition + signedQuantity;

                // Update position tracker
                positionTracker[instrumentKey] = newPosition;
                LogMessage($"Updated position - Key: {instrumentKey}, New Position: {newPosition}");

                // Determine if this is entry or exit based on position change
                if (previousPosition == 0)
                {
                    return "Entry"; // Opening new position
                }
                else if (newPosition == 0)
                {
                    // Position closed - track for validation if enabled
                    if (EnableValidationTracking && validationTracker != null)
                    {
                        TrackClosedPosition(execution, accountName, instrumentKey);
                    }

                    return "Exit"; // Closing entire position
                }
                else if (Math.Sign(previousPosition) == Math.Sign(newPosition))
                {
                    // Same direction - check if adding or reducing
                    if (Math.Abs(newPosition) > Math.Abs(previousPosition))
                    {
                        return "Entry"; // Adding to position
                    }
                    else
                    {
                        return "Exit"; // Reducing position
                    }
                }
                else
                {
                    return "Exit"; // Position reversal (closing and reopening)
                }
            }
            catch
            {
                return "Entry"; // Default to entry if unable to determine
            }
        }

        private void ExportExecution(Execution execution, string executionId, string entryExit)
        {
            try
            {
                lock (lockObject)
                {
                    if (streamWriter == null)
                        CreateNewExportFile();

                    // Format execution data according to required CSV format
                    var csvLine = FormatExecutionAsCSV(execution, executionId, entryExit);

                    streamWriter.WriteLine(csvLine);
                    streamWriter.Flush();

                    if (EnableLogging)
                    {
                        var accountName = execution.Account?.Name ?? "Unknown";
                        var instrumentKey = $"{accountName}_{execution.Instrument.FullName}";
                        var currentPos = positionTracker.ContainsKey(instrumentKey) ? positionTracker[instrumentKey] : 0;
                        LogMessage($"Exported execution: [{accountName}] {execution.Instrument.FullName} {entryExit} {execution.Quantity}@{execution.Price} - Position: {currentPos}");
                    }
                }
            }
            catch (Exception ex)
            {
                LogError($"Error exporting execution: {ex.Message}");
            }
        }

        /// <summary>
        /// Task 8.7: Formats execution as CSV with TradeValidation data
        /// </summary>
        private string FormatExecutionAsCSV(Execution execution, string executionId, string entryExit)
        {
            // Map execution data to match manual NinjaTrader report format
            var instrument = execution.Instrument.FullName;
            var action = execution.Order.OrderAction.ToString(); // "Buy" or "Sell"
            var quantity = Math.Abs(execution.Quantity).ToString();
            var price = execution.Price.ToString("F2");
            var time = execution.Time.ToString("M/d/yyyy h:mm:ss tt");
            var id = executionId;
            var entryExitValue = entryExit;

            // Get current position after this execution from position tracker (account-specific)
            var accountName = execution.Account?.Name ?? "Unknown";
            var instrumentKey = $"{accountName}_{execution.Instrument.FullName}";
            var currentPosition = positionTracker.ContainsKey(instrumentKey) ? positionTracker[instrumentKey] : 0;

            string position;
            if (currentPosition > 0)
                position = $"{currentPosition} L";
            else if (currentPosition < 0)
                position = $"{Math.Abs(currentPosition)} S";
            else
                position = "-";

            var orderId = execution.Order?.Id.ToString() ?? "";
            var name = execution.Order?.Name ?? entryExit;

            // Handle commission
            var commission = "$" + execution.Commission.ToString("F2");

            var rate = "1"; // Default rate
            var account = execution.Account?.Name ?? "Unknown";
            var connection = "Apex Trader Funding "; // Default connection

            // Task 8.7: Check shared validation map for TradeValidation data
            string tradeValidation = GetTradeValidationStatus(execution);

            // Escape any commas in data fields
            instrument = EscapeCSVField(instrument);
            action = EscapeCSVField(action);
            id = EscapeCSVField(id);
            position = EscapeCSVField(position);
            orderId = EscapeCSVField(orderId);
            name = EscapeCSVField(name);
            account = EscapeCSVField(account);
            connection = EscapeCSVField(connection);

            // Task 8.7: Include TradeValidation in CSV output
            return $"{instrument},{action},{quantity},{price},{time},{id},{entryExitValue},{position},{orderId},{name},{commission},{rate},{account},{connection},{tradeValidation}";
        }

        /// <summary>
        /// Gets trade validation status from shared dictionary
        /// Uses position closure tracking to find validation for all executions in a position
        /// </summary>
        private string GetTradeValidationStatus(Execution execution)
        {
            try
            {
                var accountName = execution.Account?.Name ?? "Unknown";
                var instrument = execution.Instrument?.FullName ?? "Unknown";
                var executionTime = execution.Time;

                // Strategy 1: Try exact timestamp match (for closing execution)
                var positionId = GeneratePositionId(executionTime, instrument, accountName);
                if (SharedValidationMap.TryGetValue(positionId, out string validationStatus))
                {
                    return validationStatus;
                }

                // Strategy 2: Check position closure map for nearby closure time
                var dateKey = $"{executionTime:yyyy-MM-dd}_{instrument}_{accountName}";
                if (PositionClosureMap.TryGetValue(dateKey, out DateTime closureTime))
                {
                    // Check if this execution is within 60 seconds of the position closure
                    var timeDiff = Math.Abs((executionTime - closureTime).TotalSeconds);
                    if (timeDiff <= 60)
                    {
                        // Use the closure time to look up validation
                        var closurePositionId = GeneratePositionId(closureTime, instrument, accountName);
                        if (SharedValidationMap.TryGetValue(closurePositionId, out validationStatus))
                        {
                            return validationStatus;
                        }
                    }
                }

                // Strategy 3: Search within time window (±30 seconds)
                for (int secondsOffset = -30; secondsOffset <= 30; secondsOffset++)
                {
                    if (secondsOffset == 0) continue; // Already checked exact match

                    var searchTime = executionTime.AddSeconds(secondsOffset);
                    var searchPositionId = GeneratePositionId(searchTime, instrument, accountName);

                    if (SharedValidationMap.TryGetValue(searchPositionId, out validationStatus))
                    {
                        LogMessage($"Found validation via time window search (offset: {secondsOffset}s): {validationStatus}");
                        return validationStatus;
                    }
                }

                // Return empty string if not validated
                return "";
            }
            catch (Exception ex)
            {
                LogError($"Error getting trade validation status: {ex.Message}");
                return ""; // Return empty on error
            }
        }

        private string EscapeCSVField(string field)
        {
            if (string.IsNullOrEmpty(field))
                return "";

            if (field.Contains(",") || field.Contains("\"") || field.Contains("\n"))
            {
                return "\"" + field.Replace("\"", "\"\"") + "\"";
            }

            return field;
        }

        private void CheckFileRotation()
        {
            try
            {
                bool shouldRotate = false;

                // Check if we should create a new daily file based on session date
                if (CreateDailyFiles)
                {
                    DateTime newSessionDate = GetSessionCloseDate();

                    if (newSessionDate > currentFileDate)
                    {
                        shouldRotate = true;
                        if (EnableLogging)
                        {
                            LogMessage($"File rotation triggered: Session date changed from {currentFileDate:yyyy-MM-dd} to {newSessionDate:yyyy-MM-dd}");
                        }
                    }
                }

                // Check file size limit
                if (File.Exists(exportFilePath))
                {
                    var fileInfo = new FileInfo(exportFilePath);
                    var fileSizeMB = fileInfo.Length / (1024.0 * 1024.0);

                    if (fileSizeMB > MaxFileSizeMB)
                    {
                        shouldRotate = true;
                        if (EnableLogging)
                        {
                            LogMessage($"File rotation triggered: File size {fileSizeMB:F2}MB exceeds limit {MaxFileSizeMB}MB");
                        }
                    }
                }

                if (shouldRotate)
                {
                    CreateNewExportFile();
                }
            }
            catch (Exception ex)
            {
                LogError($"Error checking file rotation: {ex.Message}");
            }
        }

        private void LogMessage(string message)
        {
            try
            {
                if (!EnableLogging) return;

                var logPath = Path.Combine(exportDirectory, "logs", "execution_export.log");
                var logEntry = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} - INFO - {message}";

                File.AppendAllText(logPath, logEntry + Environment.NewLine);
                Print(message); // Also print to NinjaTrader output window
            }
            catch
            {
                // Silently ignore logging errors to prevent cascading failures
            }
        }

        private void LogError(string message)
        {
            try
            {
                var logPath = Path.Combine(exportDirectory, "logs", "execution_export.log");
                var logEntry = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} - ERROR - {message}";

                File.AppendAllText(logPath, logEntry + Environment.NewLine);
                Print($"ERROR: {message}"); // Also print to NinjaTrader output window
            }
            catch
            {
                // Silently ignore logging errors to prevent cascading failures
            }
        }

        private void CleanupResources()
        {
            try
            {
                lock (lockObject)
                {
                    if (streamWriter != null)
                    {
                        streamWriter.Close();
                        streamWriter.Dispose();
                        streamWriter = null;

                        LogMessage("ExecutionExporter resources cleaned up");
                    }
                }
            }
            catch (Exception ex)
            {
                LogError($"Error during cleanup: {ex.Message}");
            }
        }

        protected override void OnBarUpdate()
        {
            // This indicator doesn't need to process bar updates
            // All logic is handled in execution events
        }

        #region Validation Tracking

        /// <summary>
        /// Tracks a closed position for validation
        /// </summary>
        private void TrackClosedPosition(Execution execution, string accountName, string instrumentKey)
        {
            try
            {
                var instrument = execution.Instrument?.FullName ?? "Unknown";
                var closeTime = execution.Time;

                // Generate position ID
                var positionId = GeneratePositionId(closeTime, instrument, accountName);

                // Update position closure map for lookup optimization
                var dateKey = $"{closeTime:yyyy-MM-dd}_{instrument}_{accountName}";
                PositionClosureMap.AddOrUpdate(dateKey, closeTime, (key, oldValue) => closeTime);

                // If blocking is disabled, add to queued positions
                if (!EnableOrderBlocking)
                {
                    QueuedPositionsMap.AddOrUpdate(positionId, 1, (key, oldCount) => oldCount + 1);
                    LogMessage($"✓ Position queued (blocking disabled): {positionId} (Total queued: {QueuedPositionsMap.Count})");
                }

                // Add to validation tracker (all closed positions require validation)
                lock (lockObject)
                {
                    validationTracker.AddPosition(positionId, closeTime, instrument, 0m, true);

                    var unvalidatedCount = validationTracker.GetUnvalidated().Count;
                    LogMessage($"✓ Position closed - Added to validation tracker: {positionId}");
                    LogMessage($"✓ Unvalidated positions: {unvalidatedCount}");

                    // Save state after adding position
                    SaveValidationState(validationTracker, validationStateFilePath);

                    // Refresh validation panel to show new position
                    if (validationPanel != null)
                    {
                        ChartControl?.Dispatcher?.InvokeAsync(() =>
                        {
                            try
                            {
                                validationPanel.RefreshPositions();
                            }
                            catch (Exception ex)
                            {
                                LogError($"Error refreshing validation panel: {ex.Message}");
                            }
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                LogError($"Error tracking closed position: {ex.Message}");
            }
        }

        /// <summary>
        /// Handles order events to enforce validation requirement
        /// ACTUALLY CANCELS ORDERS when validation is required
        /// </summary>
        private void OnOrderUpdate(object sender, OrderEventArgs e)
        {
            try
            {
                if (!EnableOrderBlocking) return;
                if (e?.Order == null) return;
                if (e.Order.Account == null) return;

                // Only check new order submissions or working orders
                if (e.OrderState != OrderState.Submitted &&
                    e.OrderState != OrderState.Working &&
                    e.OrderState != OrderState.Accepted)
                    return;

                // Bypass automated strategy orders if configured
                if (BypassAutomatedStrategies && IsAutomatedOrder(e.Order))
                {
                    LogMessage($"Order bypassed validation (automated): {e.Order.Instrument?.FullName}");
                    return;
                }

                // Check for emergency override
                if (EnableEmergencyOverride && IsEmergencyOverride())
                {
                    LogMessage($"⚠ EMERGENCY OVERRIDE: Validation bypassed (Ctrl+Shift)");
                    return;
                }

                // Check for unvalidated positions
                var instrument = e.Order.Instrument?.FullName ?? "";
                List<PositionValidationEntry> unvalidatedPositions;

                lock (lockObject)
                {
                    if (validationTracker != null)
                    {
                        unvalidatedPositions = validationTracker.GetUnvalidatedPositionsForInstrument(
                            instrument,
                            GracePeriodSeconds
                        );

                        if (unvalidatedPositions.Count > 0)
                        {
                            // CANCEL THE ORDER - This actually prevents the trade!
                            try
                            {
                                e.Order.Account.Cancel(new[] { e.Order });

                                Print($"❌ ORDER CANCELLED - {unvalidatedPositions.Count} unvalidated position(s) for {instrument}");
                                Print($"❌ Cancelled Order: {e.Order.Name} {e.Order.OrderAction} {e.Order.Quantity} {instrument}");

                                foreach (var pos in unvalidatedPositions.Take(3))
                                {
                                    Print($"   • Unvalidated: {pos.Instrument} closed at {pos.CloseTimestamp:HH:mm:ss}");
                                }

                                Print($"   → Validate positions in the panel on the right side of chart");

                                if (EnableEmergencyOverride)
                                {
                                    Print($"   → Or hold Ctrl+Shift to override");
                                }
                            }
                            catch (Exception cancelEx)
                            {
                                LogError($"Failed to cancel order: {cancelEx.Message}");
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                LogError($"Error in OnOrderUpdate: {ex.Message}");
            }
        }


        /// <summary>
        /// Generates a unique position ID
        /// </summary>
        private string GeneratePositionId(DateTime timestamp, string instrument, string account)
        {
            return $"{timestamp:yyyy-MM-ddTHH:mm:ss}_{instrument}_{account}";
        }

        /// <summary>
        /// Checks if order is from automated strategy
        /// </summary>
        private bool IsAutomatedOrder(Order order)
        {
            if (order == null) return false;
            if (order.IsBacktestOrder) return true;
            if (!string.IsNullOrEmpty(order.Name) && order.Name.Contains("Strategy")) return true;
            return false;
        }

        /// <summary>
        /// Checks if emergency override is active (Ctrl+Shift)
        /// </summary>
        private bool IsEmergencyOverride()
        {
            try
            {
                return (System.Windows.Input.Keyboard.Modifiers & System.Windows.Input.ModifierKeys.Control) == System.Windows.Input.ModifierKeys.Control &&
                       (System.Windows.Input.Keyboard.Modifiers & System.Windows.Input.ModifierKeys.Shift) == System.Windows.Input.ModifierKeys.Shift;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Saves validation state to file
        /// </summary>
        private static void SaveValidationState(PositionValidationTracker tracker, string filePath)
        {
            try
            {
                var state = tracker.SerializeToText();
                File.WriteAllText(filePath, state, Encoding.UTF8);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error saving validation state: {ex.Message}");
            }
        }

        /// <summary>
        /// Loads validation state from file
        /// </summary>
        private static PositionValidationTracker LoadValidationState(string filePath)
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
                System.Diagnostics.Debug.WriteLine($"Error loading validation state: {ex.Message}");
            }

            return new PositionValidationTracker();
        }

        #endregion

        #region Properties

        /// <summary>
        /// Directory path where CSV execution files will be exported.
        /// Default: User's Documents folder under FuturesTradingLog\data
        /// The directory will be created automatically if it doesn't exist.
        /// Subdirectories 'exported' and 'logs' will also be created.
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Export Path", Description = "Directory path for CSV export files (created automatically if missing)", GroupName = "Settings", Order = 1)]
        public string ExportPath { get; set; }

        /// <summary>
        /// When enabled, creates one CSV file per trading session using session close date.
        /// When disabled, creates time-stamped files that rotate based on size limit.
        /// Recommended: true for integration with FuturesTradingLog daily import.
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Create Daily Files", Description = "Create one CSV file per trading session (recommended for daily imports)", GroupName = "Settings", Order = 2)]
        public bool CreateDailyFiles { get; set; }

        /// <summary>
        /// Maximum file size in megabytes before rotating to a new file.
        /// Only applies when CreateDailyFiles is false.
        /// Valid range: 1-100 MB. Default: 10 MB.
        /// </summary>
        [NinjaScriptProperty]
        [Range(1, 100)]
        [Display(Name = "Max File Size (MB)", Description = "Maximum CSV file size before rotation (1-100 MB)", GroupName = "Settings", Order = 3)]
        public int MaxFileSizeMB { get; set; }

        /// <summary>
        /// Enable detailed logging to execution_export.log file.
        /// Logs include timezone conversion, session date calculation, file operations, and errors.
        /// Recommended: true for initial setup and troubleshooting, can be disabled in production.
        /// Log file location: [ExportPath]\logs\execution_export.log
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Logging", Description = "Enable detailed logging for troubleshooting (logs to execution_export.log)", GroupName = "Settings", Order = 4)]
        public bool EnableLogging { get; set; }

        /// <summary>
        /// Enable session close date logic for file naming.
        /// When true: Uses futures market session closing date (executions after 3pm PT use next day's date)
        /// When false: Uses legacy current date logic (backward compatibility mode)
        /// Recommended: true for correct session date alignment with futures market schedule.
        /// Example: Sunday 4pm PT trades export to Monday file (session closes Monday 2pm PT)
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Use Session Close Date", Description = "Enable session close date logic (after 3pm PT uses next day) - Recommended: true", GroupName = "Session Settings", Order = 5)]
        public bool UseSessionCloseDate { get; set; }

        /// <summary>
        /// Hour in Pacific Time when a new trading session begins (24-hour format).
        /// Default: 15 (3pm PT) - matches futures market session start time.
        /// Valid range: 0-23 hours.
        /// After this hour, executions are exported using the NEXT day's date.
        /// Before this hour, executions use the CURRENT day's date.
        /// Example: At 4pm PT (hour 16), session close date is tomorrow because 16 >= 15.
        /// </summary>
        [NinjaScriptProperty]
        [Range(0, 23)]
        [Display(Name = "Session Start Hour (PT)", Description = "Hour when new session begins in Pacific Time (0-23, default: 15 for 3pm PT)", GroupName = "Session Settings", Order = 6)]
        public int SessionStartHourPT { get; set; }

        /// <summary>
        /// Enable trade validation tracking to mark closed positions for review.
        /// When enabled, tracks closed positions and saves validation state to file.
        /// Integrates with FuturesTradingLog web interface for performance analysis.
        /// Default: false (disabled)
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Validation Tracking", Description = "Track closed positions for validation in FuturesTradingLog (default: disabled)", GroupName = "Validation Settings", Order = 7)]
        public bool EnableValidationTracking { get; set; }

        /// <summary>
        /// Enable order blocking until positions are validated.
        /// ACTUALLY CANCELS orders when trying to trade with unvalidated positions.
        /// Orders are cancelled before execution using Account.Cancel() API.
        /// Requires EnableValidationTracking to be enabled.
        /// Default: true (enabled)
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Order Blocking", Description = "CANCEL orders when unvalidated positions exist (prevents trading)", GroupName = "Validation Settings", Order = 8)]
        public bool EnableOrderBlocking { get; set; }

        /// <summary>
        /// Grace period in seconds before order blocking activates after position closes.
        /// Gives traders time to validate positions before orders are cancelled.
        /// Set to 0 for immediate enforcement, or higher to allow time for validation.
        /// Valid range: 0-300 seconds. Default: 0 (immediate - orders cancelled right away)
        /// </summary>
        [NinjaScriptProperty]
        [Range(0, 300)]
        [Display(Name = "Grace Period (seconds)", Description = "Seconds after close before orders are cancelled (0 = immediate)", GroupName = "Validation Settings", Order = 9)]
        public int GracePeriodSeconds { get; set; }

        /// <summary>
        /// Bypass validation requirement for automated strategy orders.
        /// When enabled, only manual orders require validation.
        /// Default: true (bypass automated orders)
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Bypass Automated Strategies", Description = "Skip validation for automated strategy orders", GroupName = "Validation Settings", Order = 10)]
        public bool BypassAutomatedStrategies { get; set; }

        /// <summary>
        /// Enable emergency override using Ctrl+Shift keyboard shortcut.
        /// Allows bypassing validation in urgent situations.
        /// Default: true (emergency override enabled)
        /// </summary>
        [NinjaScriptProperty]
        [Display(Name = "Enable Emergency Override", Description = "Allow Ctrl+Shift to bypass validation", GroupName = "Validation Settings", Order = 11)]
        public bool EnableEmergencyOverride { get; set; }

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
        public List<PositionValidationEntry> GetUnvalidated()
        {
            lock (lockObject)
            {
                return positions.Values
                    .Where(p => p.RequiresValidation)
                    .OrderByDescending(p => p.CloseTimestamp)
                    .ToList();
            }
        }

        /// <summary>
        /// Gets unvalidated positions for a specific instrument with grace period
        /// </summary>
        public List<PositionValidationEntry> GetUnvalidatedPositionsForInstrument(string instrument, int gracePeriodSeconds)
        {
            lock (lockObject)
            {
                DateTime now = DateTime.Now;
                return positions.Values
                    .Where(p => p.RequiresValidation)
                    .Where(p => p.Instrument == instrument)
                    .Where(p => (now - p.CloseTimestamp).TotalSeconds >= gracePeriodSeconds)
                    .OrderByDescending(p => p.CloseTimestamp)
                    .ToList();
            }
        }

        /// <summary>
        /// Gets all positions that have been validated (have a non-null ValidationStatus)
        /// </summary>
        public List<PositionValidationEntry> GetValidatedPositions()
        {
            lock (lockObject)
            {
                return positions.Values
                    .Where(p => !string.IsNullOrEmpty(p.ValidationStatus))
                    .ToList();
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
                    sb.AppendLine($"{entry.PositionId}|{entry.CloseTimestamp:o}|{entry.Instrument}|{entry.PnL}|{entry.ValidationStatus ?? "None"}|{entry.RequiresValidation}");
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

    /// <summary>
    /// WPF panel for displaying and validating positions on the chart
    /// </summary>
    public class ValidationPanel
    {
        private StackPanel mainPanel;
        private ScrollViewer scrollViewer;
        private PositionValidationTracker tracker;
        private ExecutionExporter exporter;
        private bool isVisible;
        private int maxVisiblePositions;
        private const double PositionEntryHeight = 120.0;
        private TextBlock titleText;

        public ValidationPanel(PositionValidationTracker validationTracker, ExecutionExporter parentExporter, int maxPositions)
        {
            tracker = validationTracker;
            exporter = parentExporter;
            isVisible = false;
            maxVisiblePositions = maxPositions;

            CreatePanelUI();
        }

        private void CreatePanelUI()
        {
            // Create main container panel
            mainPanel = new StackPanel
            {
                Width = 200,
                Background = new SolidColorBrush(Color.FromArgb(220, 30, 30, 30)),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 50, 10, 0),
                Opacity = 0
            };

            // Title header
            var titlePanel = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(255, 20, 20, 20)),
                Padding = new Thickness(10, 5, 10, 5)
            };

            titleText = new TextBlock
            {
                Text = "Trade Validation",
                Foreground = Brushes.White,
                FontWeight = FontWeights.Bold,
                FontSize = 12,
                TextAlignment = TextAlignment.Center
            };

            titlePanel.Child = titleText;
            mainPanel.Children.Add(titlePanel);

            // Create scroll viewer for position list
            scrollViewer = new ScrollViewer
            {
                MaxHeight = maxVisiblePositions * PositionEntryHeight,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Hidden
            };

            var positionsStack = new StackPanel();
            scrollViewer.Content = positionsStack;

            mainPanel.Children.Add(scrollViewer);

            mainPanel.Visibility = Visibility.Collapsed;
        }

        public void RefreshPositions()
        {
            if (mainPanel == null) return;

            var positionsStack = (StackPanel)scrollViewer.Content;
            positionsStack.Children.Clear();

            var unvalidated = tracker.GetUnvalidated();

            // Update title with queued count if blocking is disabled
            var queuedCount = ExecutionExporter.QueuedPositionsMap.Count;
            if (queuedCount > 0)
            {
                titleText.Text = $"Trade Validation ({queuedCount} queued)";
            }
            else
            {
                titleText.Text = "Trade Validation";
            }

            if (unvalidated.Count == 0)
            {
                CollapsePanel();
                return;
            }

            ExpandPanel();

            foreach (var position in unvalidated.OrderByDescending(p => p.CloseTimestamp))
            {
                var entryPanel = CreatePositionEntry(position);
                positionsStack.Children.Add(entryPanel);
            }

            scrollViewer.ScrollToTop();
        }

        private StackPanel CreatePositionEntry(PositionValidationEntry position)
        {
            var entryPanel = new StackPanel
            {
                Margin = new Thickness(5),
                Background = new SolidColorBrush(Color.FromArgb(150, 50, 50, 50))
            };

            // Instrument symbol
            var instrumentLabel = new TextBlock
            {
                Text = position.Instrument,
                Foreground = Brushes.White,
                FontWeight = FontWeights.Bold,
                FontSize = 11,
                Margin = new Thickness(5, 5, 5, 2)
            };
            entryPanel.Children.Add(instrumentLabel);

            // Close time
            var timeLabel = new TextBlock
            {
                Text = $"Closed: {position.CloseTimestamp:HH:mm:ss}",
                Foreground = Brushes.LightGray,
                FontSize = 10,
                Margin = new Thickness(5, 0, 5, 5)
            };
            entryPanel.Children.Add(timeLabel);

            // Button panel
            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(5, 5, 5, 10)
            };

            // Valid button
            var validButton = new Button
            {
                Content = "✓ Valid",
                Background = new SolidColorBrush(Color.FromRgb(0, 150, 0)),
                Foreground = Brushes.White,
                Width = 75,
                Height = 28,
                Margin = new Thickness(2),
                Cursor = Cursors.Hand,
                BorderThickness = new Thickness(0)
            };
            validButton.Click += (s, e) => OnValidButtonClick(position.PositionId);
            buttonPanel.Children.Add(validButton);

            // Invalid button
            var invalidButton = new Button
            {
                Content = "✗ Invalid",
                Background = new SolidColorBrush(Color.FromRgb(180, 0, 0)),
                Foreground = Brushes.White,
                Width = 75,
                Height = 28,
                Margin = new Thickness(2),
                Cursor = Cursors.Hand,
                BorderThickness = new Thickness(0)
            };
            invalidButton.Click += (s, e) => OnInvalidButtonClick(position.PositionId);
            buttonPanel.Children.Add(invalidButton);

            entryPanel.Children.Add(buttonPanel);

            return entryPanel;
        }

        private void OnValidButtonClick(string positionId)
        {
            tracker.MarkValidated(positionId, "Valid");
            ExecutionExporter.SharedValidationMap.AddOrUpdate(positionId, "Valid", (key, oldValue) => "Valid");

            // Remove from queued positions if present
            if (ExecutionExporter.QueuedPositionsMap.TryRemove(positionId, out int queuedCount))
            {
                exporter.Print($"✓ Position marked as VALID: {positionId} (Removed from queue, {ExecutionExporter.QueuedPositionsMap.Count} remain)");
            }
            else
            {
                exporter.Print($"✓ Position marked as VALID: {positionId}");
            }

            RefreshPositions();
        }

        private void OnInvalidButtonClick(string positionId)
        {
            tracker.MarkValidated(positionId, "Invalid");
            ExecutionExporter.SharedValidationMap.AddOrUpdate(positionId, "Invalid", (key, oldValue) => "Invalid");

            // Remove from queued positions if present
            if (ExecutionExporter.QueuedPositionsMap.TryRemove(positionId, out int queuedCount))
            {
                exporter.Print($"✗ Position marked as INVALID: {positionId} (Removed from queue, {ExecutionExporter.QueuedPositionsMap.Count} remain)");
            }
            else
            {
                exporter.Print($"✗ Position marked as INVALID: {positionId}");
            }

            RefreshPositions();
        }

        private void ExpandPanel()
        {
            if (mainPanel == null) return;

            mainPanel.Visibility = Visibility.Visible;

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

        private void CollapsePanel()
        {
            if (mainPanel == null) return;

            var fadeOut = new DoubleAnimation
            {
                From = 1,
                To = 0,
                Duration = TimeSpan.FromMilliseconds(300),
                EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseIn }
            };

            fadeOut.Completed += (s, e) =>
            {
                mainPanel.Visibility = Visibility.Collapsed;
            };

            mainPanel.BeginAnimation(UIElement.OpacityProperty, fadeOut);
            isVisible = false;
        }

        public StackPanel GetPanel()
        {
            return mainPanel;
        }

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
}

#region NinjaScript generated code. Neither change nor remove.

namespace NinjaTrader.NinjaScript.Indicators
{
    public partial class Indicator : NinjaTrader.Gui.NinjaScript.IndicatorRenderBase
    {
        private ExecutionExporter[] cacheExecutionExporter;
        public ExecutionExporter ExecutionExporter(string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            return ExecutionExporter(Input, exportPath, createDailyFiles, maxFileSizeMB, enableLogging, useSessionCloseDate, sessionStartHourPT, enableValidationTracking, enableOrderBlocking, gracePeriodSeconds, bypassAutomatedStrategies, enableEmergencyOverride);
        }

        public ExecutionExporter ExecutionExporter(ISeries<double> input, string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            if (cacheExecutionExporter != null)
                for (int idx = 0; idx < cacheExecutionExporter.Length; idx++)
                    if (cacheExecutionExporter[idx] != null && cacheExecutionExporter[idx].ExportPath == exportPath && cacheExecutionExporter[idx].CreateDailyFiles == createDailyFiles && cacheExecutionExporter[idx].MaxFileSizeMB == maxFileSizeMB && cacheExecutionExporter[idx].EnableLogging == enableLogging && cacheExecutionExporter[idx].UseSessionCloseDate == useSessionCloseDate && cacheExecutionExporter[idx].SessionStartHourPT == sessionStartHourPT && cacheExecutionExporter[idx].EnableValidationTracking == enableValidationTracking && cacheExecutionExporter[idx].EnableOrderBlocking == enableOrderBlocking && cacheExecutionExporter[idx].GracePeriodSeconds == gracePeriodSeconds && cacheExecutionExporter[idx].BypassAutomatedStrategies == bypassAutomatedStrategies && cacheExecutionExporter[idx].EnableEmergencyOverride == enableEmergencyOverride && cacheExecutionExporter[idx].EqualsInput(input))
                        return cacheExecutionExporter[idx];
            return CacheIndicator<ExecutionExporter>(new ExecutionExporter(){ ExportPath = exportPath, CreateDailyFiles = createDailyFiles, MaxFileSizeMB = maxFileSizeMB, EnableLogging = enableLogging, UseSessionCloseDate = useSessionCloseDate, SessionStartHourPT = sessionStartHourPT, EnableValidationTracking = enableValidationTracking, EnableOrderBlocking = enableOrderBlocking, GracePeriodSeconds = gracePeriodSeconds, BypassAutomatedStrategies = bypassAutomatedStrategies, EnableEmergencyOverride = enableEmergencyOverride }, input, ref cacheExecutionExporter);
        }
    }
}

namespace NinjaTrader.NinjaScript.MarketAnalyzerColumns
{
    public partial class MarketAnalyzerColumn : MarketAnalyzerColumnBase
    {
        public Indicators.ExecutionExporter ExecutionExporter(string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            return indicator.ExecutionExporter(Input, exportPath, createDailyFiles, maxFileSizeMB, enableLogging, useSessionCloseDate, sessionStartHourPT, enableValidationTracking, enableOrderBlocking, gracePeriodSeconds, bypassAutomatedStrategies, enableEmergencyOverride);
        }

        public Indicators.ExecutionExporter ExecutionExporter(ISeries<double> input , string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            return indicator.ExecutionExporter(input, exportPath, createDailyFiles, maxFileSizeMB, enableLogging, useSessionCloseDate, sessionStartHourPT, enableValidationTracking, enableOrderBlocking, gracePeriodSeconds, bypassAutomatedStrategies, enableEmergencyOverride);
        }
    }
}

namespace NinjaTrader.NinjaScript.Strategies
{
    public partial class Strategy : NinjaTrader.Gui.NinjaScript.StrategyRenderBase
    {
        public Indicators.ExecutionExporter ExecutionExporter(string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            return indicator.ExecutionExporter(Input, exportPath, createDailyFiles, maxFileSizeMB, enableLogging, useSessionCloseDate, sessionStartHourPT, enableValidationTracking, enableOrderBlocking, gracePeriodSeconds, bypassAutomatedStrategies, enableEmergencyOverride);
        }

        public Indicators.ExecutionExporter ExecutionExporter(ISeries<double> input , string exportPath, bool createDailyFiles, int maxFileSizeMB, bool enableLogging, bool useSessionCloseDate, int sessionStartHourPT, bool enableValidationTracking, bool enableOrderBlocking, int gracePeriodSeconds, bool bypassAutomatedStrategies, bool enableEmergencyOverride)
        {
            return indicator.ExecutionExporter(input, exportPath, createDailyFiles, maxFileSizeMB, enableLogging, useSessionCloseDate, sessionStartHourPT, enableValidationTracking, enableOrderBlocking, gracePeriodSeconds, bypassAutomatedStrategies, enableEmergencyOverride);
        }
    }
}

#endregion
