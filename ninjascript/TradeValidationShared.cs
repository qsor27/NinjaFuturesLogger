#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using NinjaTrader.Cbi;
#endregion

// Shared trade-validation machinery for NinjaFuturesLogger.
// NT8 compiles every .cs under Documents\NinjaTrader 8\bin\Custom into ONE assembly,
// so ExecutionExporter (Indicators), TradeFeedbackAddOn (AddOns) and
// TradeFeedbackIndicator (Indicators) all link against this single copy.
namespace NinjaTrader.NinjaScript.NinjaFuturesLogger
{
    public static class TradeValidationShared
    {
        // Single shared positionId -> "Valid"/"Invalid" map. This is the bridge that
        // lets validations set anywhere (exporter chart panel, AddOn enforcement
        // modal) reach the exporter's CSV TradeValidation column.
        public static readonly ConcurrentDictionary<string, string> SharedValidationMap =
            new ConcurrentDictionary<string, string>();

        private static readonly object trackerLock = new object();
        private static PositionValidationTracker tracker;

        // Canonical state file. Legacy stores under Documents\FuturesTradingLog are
        // merged in once, the first time this file does not exist (see LoadWithMigration).
        public static string StateFilePath
        {
            get
            {
                var myDocuments = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                return Path.Combine(myDocuments, "NinjaFuturesLogger", "trade_validation_state.txt");
            }
        }

        // The one tracker instance every component uses. Lazily loaded so whichever
        // component initializes first (exporter, AddOn, or indicator) triggers the
        // load + migration exactly once.
        public static PositionValidationTracker Tracker
        {
            get
            {
                if (tracker == null)
                {
                    lock (trackerLock)
                    {
                        if (tracker == null)
                        {
                            var loaded = LoadWithMigration();
                            foreach (var entry in loaded.GetValidatedPositions())
                            {
                                SharedValidationMap.AddOrUpdate(
                                    entry.PositionId,
                                    entry.ValidationStatus,
                                    (key, oldValue) => entry.ValidationStatus);
                            }
                            tracker = loaded;
                        }
                    }
                }
                return tracker;
            }
        }

        public static void SaveState()
        {
            lock (trackerLock)
            {
                if (tracker == null) return;
                Directory.CreateDirectory(Path.GetDirectoryName(StateFilePath));
                SaveValidationState(tracker, StateFilePath);
            }
        }

        private static PositionValidationTracker LoadWithMigration()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(StateFilePath));
            if (File.Exists(StateFilePath))
                return LoadValidationState(StateFilePath);

            // One-time migration: merge both legacy stores into the canonical file.
            // Legacy files are left in place untouched.
            var merged = new PositionValidationTracker();
            var legacyRoot = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                "FuturesTradingLog");
            var legacyFiles = new[]
            {
                Path.Combine(legacyRoot, "trade_validation_state.txt"), // old ExecutionExporter store
                Path.Combine(legacyRoot, "trade_feedback_state.txt"),   // old AddOn+Indicator (clobbered) store
            };
            foreach (var legacyFile in legacyFiles)
            {
                if (File.Exists(legacyFile))
                    merged.MergeFrom(LoadValidationState(legacyFile));
            }
            SaveValidationState(merged, StateFilePath);
            return merged;
        }

        // The join key across all components. Drift here silently breaks validation
        // lookup, which is why exactly one copy exists.
        public static string GeneratePositionId(DateTime timestamp, string instrument, string account)
        {
            return $"{timestamp:yyyy-MM-ddTHH:mm:ss}_{instrument}_{account}";
        }

        private static readonly Regex AutoExitNames =
            new Regex(@"^(Stop\d+|Target\d+|Stop loss|Profit target|Trail stop|Exit|Close)$");

        // Combined rule (2026-08 consolidation decision): backtest orders, orders tied
        // to a strategy entry signal, and ATM/strategy protective exits (matched by
        // name) all bypass validation enforcement. The old Name-substring heuristic
        // ("Strategy") is deliberately dropped. Deliberate behavior change: ATM/strategy
        // protective stops now bypass validation instead of risking cancellation.
        public static bool IsAutomatedOrder(Order order)
        {
            if (order == null) return false;
            if (order.IsBacktestOrder) return true;
            if (!string.IsNullOrEmpty(order.FromEntrySignal)) return true;
            if (order.Name != null && AutoExitNames.IsMatch(order.Name)) return true;
            return false;
        }

        // Reads PHYSICAL key state via Win32 GetAsyncKeyState, which works from any
        // thread. NT8 raises OrderUpdate on MTA worker threads, where the previous
        // WPF Keyboard.Modifiers read always threw InvalidOperationException ("The
        // calling thread must be STA") and the catch turned that into false — the
        // override could never fire. GetAsyncKeyState reads the async key-state
        // table directly, so it is immune to thread apartment and input-queue
        // affinity; VK_CONTROL/VK_SHIFT cover the left and right keys.
        [DllImport("user32.dll")]
        private static extern short GetAsyncKeyState(int vKey);

        private const int VK_SHIFT = 0x10;
        private const int VK_CONTROL = 0x11;

        public static bool IsEmergencyOverride()
        {
            try
            {
                return (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0 &&
                       (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
            }
            catch
            {
                return false;
            }
        }

        public static void SaveValidationState(PositionValidationTracker trackerToSave, string filePath)
        {
            try
            {
                var state = trackerToSave.SerializeToText();
                File.WriteAllText(filePath, state, Encoding.UTF8);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error saving validation state: {ex.Message}");
            }
        }

        public static PositionValidationTracker LoadValidationState(string filePath)
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
    }

    /// <summary>
    /// Thread-safe tracker for position validation status. The single canonical copy;
    /// method set is the reconciled union of the three pre-consolidation copies.
    /// </summary>
    public class PositionValidationTracker
    {
        private Dictionary<string, PositionValidationEntry> positions;
        private readonly object lockObject = new object();

        public PositionValidationTracker()
        {
            positions = new Dictionary<string, PositionValidationEntry>();
        }

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

        public bool RequiresValidation(string positionId)
        {
            lock (lockObject)
            {
                return positions.ContainsKey(positionId) && positions[positionId].RequiresValidation;
            }
        }

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
        /// Imports every entry from another tracker. Existing IDs win (AddPosition
        /// skips duplicates); any non-null status on the incoming entry is applied.
        /// Used only by the one-time legacy state-file migration.
        /// </summary>
        public void MergeFrom(PositionValidationTracker other)
        {
            List<PositionValidationEntry> entries;
            lock (other.lockObject)
            {
                entries = other.positions.Values.ToList();
            }
            foreach (var entry in entries)
            {
                AddPosition(entry.PositionId, entry.CloseTimestamp, entry.Instrument, entry.PnL, entry.RequiresValidation);
                if (!string.IsNullOrEmpty(entry.ValidationStatus) && entry.ValidationStatus != "None")
                {
                    MarkValidated(entry.PositionId, entry.ValidationStatus);
                }
            }
        }

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
    /// Represents a single position validation entry.
    /// </summary>
    public class PositionValidationEntry
    {
        public string PositionId { get; set; }
        public DateTime CloseTimestamp { get; set; }
        public string Instrument { get; set; }
        public decimal PnL { get; set; }
        public bool RequiresValidation { get; set; }
        public string ValidationStatus { get; set; }   // "Valid", "Invalid", or null
    }
}
