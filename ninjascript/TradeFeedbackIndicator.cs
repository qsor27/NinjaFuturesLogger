#region Using declarations
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Text;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.NinjaFuturesLogger;
#endregion

//This namespace holds Indicators in this folder and is required. Do not change it.
namespace NinjaTrader.NinjaScript.Indicators
{
	/// <summary>
	/// Trade Feedback Indicator - Tracks closed positions and integrates with NinjaFuturesLogger
	/// </summary>
	public class TradeFeedbackIndicator : Indicator
	{
		private PositionValidationTracker validationTracker;
		private readonly object lockObject = new object();

		// Owner-instance guard: exactly one live indicator instance holds the
		// Account.All subscriptions; released on Terminated so a later instance
		// can resubscribe (fixes the legacy never-reset static-init bug: the old
		// one-shot guard was never cleared, so after the first instance
		// terminated no new instance ever resubscribed until NT restart).
		private static TradeFeedbackIndicator activeInstance;
		private static readonly object activeInstanceLock = new object();

		// Settings
		private bool enableOrderBlocking = true;
		private int gracePeriodSeconds = 0;
		private bool bypassAutomatedStrategies = true;
		private bool enableEmergencyOverride = true;

		protected override void OnStateChange()
		{
			if (State == State.SetDefaults)
			{
				Description = @"Tracks trade positions for validation in NinjaFuturesLogger";
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
				lock (activeInstanceLock)
				{
					// Only one live instance owns the account subscriptions
					if (activeInstance == null)
					{
						try
						{
							// Shared singleton: canonical state file, legacy migration on first touch
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
										Print($"✓ Subscribed to events for account: {account.Name}");
									}
								}
							}

							activeInstance = this;

							Print("✓ TradeFeedbackIndicator initialized successfully");
							Print($"✓ State file: {TradeValidationShared.StateFilePath}");
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
			}
			else if (State == State.Terminated)
			{
				lock (activeInstanceLock)
				{
					if (activeInstance == this)
					{
						// Save state before termination
						if (validationTracker != null)
						{
							TradeValidationShared.SaveState();
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

						// Release the claim so a later instance can resubscribe
						activeInstance = null;
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
					Print($"✓ POSITION CLOSED: {instrument} [{account}] - Adding to validation tracker");

					var positionId = TradeValidationShared.GeneratePositionId(DateTime.Now, instrument, account);

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
				if (bypassAutomatedStrategies && TradeValidationShared.IsAutomatedOrder(e.Order))
				{
					Print($"✓ Bypassing validation for automated order");
					return;
				}

				// Check for emergency override
				if (enableEmergencyOverride && TradeValidationShared.IsEmergencyOverride())
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
								message.AppendLine("Please validate in NinjaFuturesLogger web interface");

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
	}
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
