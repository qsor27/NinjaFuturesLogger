#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Input;
using NinjaTrader.Cbi;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.Gui.Tools;
using NinjaTrader.NinjaScript;
#endregion

//This namespace holds Indicators in this folder and is required. Do not change it.
namespace NinjaTrader.NinjaScript.Indicators
{
	/// <summary>
	/// Trade Feedback Indicator - Tracks closed positions and integrates with FuturesTradingLog
	/// </summary>
	public class TradeFeedbackIndicator : Indicator
	{
		private static PositionValidationTracker validationTracker;
		private static string stateFilePath;
		private static bool isInitialized = false;
		private readonly object lockObject = new object();

		// Settings
		private bool enableOrderBlocking = true;
		private int gracePeriodSeconds = 0;
		private bool bypassAutomatedStrategies = true;
		private bool enableEmergencyOverride = true;

		// Shared static dictionary for ExecutionExporter integration
		public static ConcurrentDictionary<string, string> SharedValidationMap = new ConcurrentDictionary<string, string>();

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = @"Tracks trade positions for validation in FuturesTradingLog";
				Name = "TradeFeedbackIndicator";
				Calculate = Calculate.OnBarClose;
				IsOverlay = true;
				DisplayInDataBox = false;
				DrawOnPricePanel = true;
				PaintPriceMarkers = false;
				IsSuspendedWhileInactive = false;
			}
			else if (State == State.DataLoaded)
			{
				// Initialize only once (static singleton pattern)
				if (!isInitialized)
				{
					try
					{
						// Setup state file path
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
									Print($"✓ Subscribed to events for account: {account.Name}");
								}
							}
						}

						isInitialized = true;

						Print("✓ TradeFeedbackIndicator initialized successfully");
						Print($"✓ State file: {stateFilePath}");
						Print($"✓ Order blocking: {(enableOrderBlocking ? "ENABLED" : "DISABLED")}");
						Print("✓ Now tracking position closes...");
					}
					catch (Exception ex)
					{
						Print($"✗ TradeFeedbackIndicator Error: {ex.Message}");
						Print($"✗ Stack trace: {ex.StackTrace}");
					}
				}
			}
			else if (State == State.Terminated)
			{
				// Save state before termination
				if (isInitialized && validationTracker != null)
				{
					SaveState(validationTracker, stateFilePath);
					Print("✓ TradeFeedbackIndicator: State saved");
				}

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
			}
		}

		protected override void OnBarUpdate()
		{
			// Nothing to do on bar updates - we're event-driven
		}

		#region Position Tracking

		private void OnPositionUpdate(object sender, PositionEventArgs e)
		{
			try
			{
				if (e?.Position == null) return;

				var pos = e.Position;
				var instrument = pos.Instrument?.FullName ?? "Unknown";
				var account = pos.Account?.Name ?? "Unknown";

				// DEBUG: Log all updates
				Print($"DEBUG: PositionUpdate - {instrument} [{account}] MarketPosition: {pos.MarketPosition} Qty: {pos.Quantity}");

				// Check if position just went to flat (closed)
				if (pos.MarketPosition == MarketPosition.Flat && pos.Quantity == 0)
				{
					// Get average prices from position
					double averagePrice = pos.AveragePrice;

					// Calculate approximate P&L (this is a rough estimate since position is closed)
					// In reality, we'd need to track entry/exit prices separately
					// For now, just mark it for validation
					Print($"✓ POSITION CLOSED: {instrument} [{account}] - Adding to validation tracker");

					var positionId = GeneratePositionId(DateTime.Now, instrument, account);

					lock (lockObject)
					{
						if (validationTracker != null)
						{
							validationTracker.AddPosition(positionId, DateTime.Now, instrument, 0m, true);
							Print($"✓ Added to tracker: {positionId}");

							// Show current tracker status
							var unvalidated = validationTracker.GetUnvalidated();
							Print($"✓ Unvalidated positions: {unvalidated.Count}");
						}
					}
				}
			}
			catch (Exception ex)
			{
				Print($"✗ Error in OnPositionUpdate: {ex.Message}");
			}
		}

		private void OnOrderUpdate(object sender, OrderEventArgs e)
		{
			try
			{
				if (!enableOrderBlocking) return;
				if (e?.Order == null) return;

				// Only process new order attempts
				if (e.OrderState != OrderState.Working && e.OrderState != OrderState.Submitted)
					return;

				Print($"DEBUG: OrderUpdate - {e.Order.Instrument?.FullName} State: {e.OrderState}");

				// Check for automated strategy bypass
				if (bypassAutomatedStrategies && IsAutomatedOrder(e.Order))
				{
					Print($"✓ Bypassing validation for automated order");
					return;
				}

				// Check for emergency override
				if (enableEmergencyOverride && IsEmergencyOverride())
				{
					Print($"✓ EMERGENCY OVERRIDE: Bypassing validation (Ctrl+Shift detected)");
					return;
				}

				// Check for unvalidated positions
				string instrument = e.Order.Instrument?.FullName ?? "";
				List<PositionValidationEntry> unvalidatedPositions;

				lock (lockObject)
				{
					if (validationTracker != null)
					{
						unvalidatedPositions = validationTracker.GetUnvalidatedPositionsForInstrument(
							instrument,
							gracePeriodSeconds
						);

						if (unvalidatedPositions.Count > 0)
						{
							Print($"⚠ VALIDATION REQUIRED: {unvalidatedPositions.Count} unvalidated position(s) for {instrument}");

							// Show validation alert
							Core.Globals.RandomDispatcher.BeginInvoke(new Action(() =>
							{
								StringBuilder message = new StringBuilder();
								message.AppendLine($"Position validation required for {instrument}");
								message.AppendLine();
								message.AppendLine("Unvalidated positions:");

								foreach (var pos in unvalidatedPositions.Take(5))
								{
									message.AppendLine($"  {pos.CloseTimestamp:HH:mm:ss} - {pos.Instrument}");
								}

								message.AppendLine();
								message.AppendLine("Please validate in FuturesTradingLog web interface");

								if (enableEmergencyOverride)
								{
									message.AppendLine("(Hold Ctrl+Shift to override)");
								}

								NinjaTrader.Gui.Tools.NTMessageBoxSimple.Show(null, message.ToString(),
									"Validation Required", System.Windows.MessageBoxButton.OK,
									System.Windows.MessageBoxImage.Warning);
							}));
						}
					}
				}
			}
			catch (Exception ex)
			{
				Print($"✗ Error in OnOrderUpdate: {ex.Message}");
			}
		}

		#endregion

		#region Helper Methods

		private string GeneratePositionId(DateTime timestamp, string instrument, string account)
		{
			return $"{timestamp:yyyy-MM-ddTHH:mm:ss}_{instrument}_{account}";
		}

		private bool IsAutomatedOrder(Order order)
		{
			if (order.IsBacktestOrder) return true;
			if (!string.IsNullOrEmpty(order.Name) && order.Name.Contains("Strategy")) return true;
			return false;
		}

		private bool IsEmergencyOverride()
		{
			try
			{
				return (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control &&
					   (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
			}
			catch
			{
				return false;
			}
		}

		#endregion

		#region State Persistence

		private static void SaveState(PositionValidationTracker tracker, string filePath)
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

		private static PositionValidationTracker LoadState(string filePath)
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

			return new PositionValidationTracker();
		}

		#endregion
	}

	#region PositionValidationTracker Class

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

	public class PositionValidationEntry
	{
		public string PositionId { get; set; }
		public DateTime CloseTimestamp { get; set; }
		public string Instrument { get; set; }
		public decimal PnL { get; set; }
		public bool RequiresValidation { get; set; }
		public string ValidationStatus { get; set; }
	}

	#endregion
}

#region NinjaScript generated code. Neither change nor remove.

namespace NinjaTrader.NinjaScript.Indicators
{
	public partial class Indicator : NinjaTrader.Gui.NinjaScript.IndicatorRenderBase
	{
		private TradeFeedbackIndicator[] cacheTradeFeedbackIndicator;
		public TradeFeedbackIndicator TradeFeedbackIndicator()
		{
			return TradeFeedbackIndicator(Input);
		}

		public TradeFeedbackIndicator TradeFeedbackIndicator(ISeries<double> input)
		{
			if (cacheTradeFeedbackIndicator != null)
				for (int idx = 0; idx < cacheTradeFeedbackIndicator.Length; idx++)
					if (cacheTradeFeedbackIndicator[idx] != null &&  cacheTradeFeedbackIndicator[idx].EqualsInput(input))
						return cacheTradeFeedbackIndicator[idx];
			return CacheIndicator<TradeFeedbackIndicator>(new TradeFeedbackIndicator(), input, ref cacheTradeFeedbackIndicator);
		}
	}
}

namespace NinjaTrader.NinjaScript.MarketAnalyzerColumns
{
	public partial class MarketAnalyzerColumn : MarketAnalyzerColumnBase
	{
		public Indicators.TradeFeedbackIndicator TradeFeedbackIndicator()
		{
			return indicator.TradeFeedbackIndicator(Input);
		}

		public Indicators.TradeFeedbackIndicator TradeFeedbackIndicator(ISeries<double> input )
		{
			return indicator.TradeFeedbackIndicator(input);
		}
	}
}

namespace NinjaTrader.NinjaScript.Strategies
{
	public partial class Strategy : NinjaTrader.Gui.NinjaScript.StrategyRenderBase
	{
		public Indicators.TradeFeedbackIndicator TradeFeedbackIndicator()
		{
			return indicator.TradeFeedbackIndicator(Input);
		}

		public Indicators.TradeFeedbackIndicator TradeFeedbackIndicator(ISeries<double> input )
		{
			return indicator.TradeFeedbackIndicator(input);
		}
	}
}

#endregion
