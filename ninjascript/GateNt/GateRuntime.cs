#region Using declarations
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate;
#endregion

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.GateNt
{
    /// <summary>
    /// Plan B2: the single in-process owner of every InstrumentGate. Every gate call happens under
    /// one lock (InstrumentGate is not thread-safe); the actions it returns are carried out after
    /// the lock is released, so NinjaTrader order calls and event handlers never run while it is
    /// held. Lock order is always feed → runtime.
    /// </summary>
    public sealed class GateRuntime
    {
        private static readonly GateTimeframe[] Timeframes =
            { GateTimeframe.M1, GateTimeframe.M3, GateTimeframe.H1, GateTimeframe.H4 };

        private readonly object sync = new object();
        private readonly Action<string> print;
        private readonly Dictionary<string, InstrumentGate> gates = new Dictionary<string, InstrumentGate>(StringComparer.Ordinal);
        private readonly Dictionary<string, List<GateBarFeed>> feeds = new Dictionary<string, List<GateBarFeed>>(StringComparer.Ordinal);
        private readonly Dictionary<string, int> positions = new Dictionary<string, int>(StringComparer.Ordinal);
        private readonly Dictionary<string, HashSet<long>> workingEntries = new Dictionary<string, HashSet<long>>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> lastCancel = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<Connection, ConnectionStatus> priceStatus = new Dictionary<Connection, ConnectionStatus>();
        private readonly HashSet<string> reportedAccountProblems = new HashSet<string>(StringComparer.Ordinal);
        private GateStateFile state = new GateStateFile();
        private GateOrderEnforcer enforcer;

        public GateRuntime(Action<string> print)
        {
            this.print = print ?? (s => { });
        }

        public static GateRuntime Current { get; private set; }

        public GateSettings Settings { get; private set; } = GateSettings.Defaults();

        public static string Folder =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "NinjaFuturesLogger");
        public static string StatePath => Path.Combine(Folder, "setup_gate_state.txt");
        public static string SettingsPath => Path.Combine(Folder, "setup_gate_settings.txt");
        public static string LogPath => Path.Combine(Folder, "gate_log.csv");
        public static string JournalPath => Path.Combine(Folder, "gate_entries.txt");

        /// <summary>An instrument's snapshot may have changed. Raised on a NinjaTrader thread.</summary>
        public event Action<string> GateChanged;

        /// <summary>The instrument needs the hourly trend answered (spec §5). Raised on a NinjaTrader thread.</summary>
        public event Action<string> TrendPromptRequested;

        /// <summary>Something the trader must see now (slip-through, load failure, config gap).</summary>
        public event Action<string> AlertRaised;

        public void Start()
        {
            var problems = new List<string>();
            Settings = GateSettings.LoadOrCreate(SettingsPath, problems);
            foreach (string problem in problems) RaiseAlert(problem);
            if (Settings.GatedAccounts.Count == 0)
                RaiseAlert("No gated accounts are set in " + SettingsPath + " — the gate is not enforcing any account.");

            var load = GateStateStore.Load(StatePath);
            if (load.Error != null)
                RaiseAlert("Setup gate state could not be read (" + load.Error + "). Starting empty — set your levels again.");
            if (load.WasCorrupt)
                RaiseAlert("Setup gate state was corrupt and was moved to " + (load.BackupPath ?? "(could not be moved)") + ".");
            lock (sync) state = load.State;

            Current = this;
            lock (Connection.Connections)
            {
                lock (sync)
                {
                    foreach (Connection connection in Connection.Connections) priceStatus[connection] = connection.PriceStatus;
                }
            }
            enforcer = new GateOrderEnforcer(this);
            Connection.ConnectionStatusUpdate += OnConnectionStatusUpdate;
            enforcer.SubscribeAll();
            CheckAccounts();

            List<string> saved;
            lock (sync) saved = state.Instruments.Keys.ToList();
            foreach (string instrument in saved)
            {
                string error = Track(instrument);
                if (error != null) RaiseAlert(error);
            }
        }

        public void Stop()
        {
            Connection.ConnectionStatusUpdate -= OnConnectionStatusUpdate;
            if (enforcer != null) enforcer.Stop();
            foreach (var feed in AllFeeds()) feed.Dispose();
            lock (sync)
            {
                feeds.Clear();
                Save();
            }
            if (Current == this) Current = null;
        }

        public IReadOnlyList<string> TrackedInstruments()
        {
            lock (sync) return gates.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
        }

        /// <summary>Starts gating an instrument contract such as "MNQ 12-26". Returns an error or null.</summary>
        public string Track(string instrumentName)
        {
            if (string.IsNullOrWhiteSpace(instrumentName)) return "Type an instrument such as MNQ 12-26.";
            var instrument = Instrument.GetInstrument(instrumentName.Trim(), false);
            if (instrument == null) return "Unknown instrument: " + instrumentName.Trim();

            string name = instrument.FullName;
            List<GateBarFeed> created;
            lock (sync)
            {
                if (gates.ContainsKey(name)) return null;
                var gate = new InstrumentGate(name, state.GetOrAdd(name));
                gate.SetOneMinuteFeed(false); // fail closed until 1m history arrives
                gate.LeaderPositionQty = LeaderPosition(name);
                HashSet<long> working;
                gate.GateEntryWorking = workingEntries.TryGetValue(name, out working) && working.Count > 0;
                gates[name] = gate;
                created = Timeframes.Select(tf => new GateBarFeed(this, instrument, tf, Settings.HistoryDays)).ToList();
                feeds[name] = created;
            }
            foreach (var feed in created) feed.Start();
            Changed(name);
            return null;
        }

        public GateSnapshot Snapshot(string instrument)
        {
            lock (sync)
            {
                InstrumentGate gate;
                return instrument != null && gates.TryGetValue(instrument, out gate) ? gate.Snapshot() : null;
            }
        }

        public long LatestHourEnd(string instrument)
        {
            lock (sync)
            {
                InstrumentGate gate;
                return instrument != null && gates.TryGetValue(instrument, out gate) ? gate.LatestHourEnd : 0;
            }
        }

        public IReadOnlyList<GateBar> RecentHourlyBars(string instrument, int count)
        {
            lock (sync)
            {
                InstrumentGate gate;
                if (instrument == null || !gates.TryGetValue(instrument, out gate)) return new GateBar[0];
                var bars = gate.BarsFor(GateTimeframe.H1);
                return bars.Skip(Math.Max(0, bars.Count - count)).ToList();
            }
        }

        public string LastCancel(string instrument)
        {
            lock (sync)
            {
                string reason;
                return instrument != null && lastCancel.TryGetValue(instrument, out reason) ? reason : null;
            }
        }

        public GateCommandResult SetLevel(string instrument, GateSide side, GateTimeframe tf, double price) =>
            Command(instrument, g => g.SetLevel(side, tf, price, Now()));

        public GateCommandResult SetExtreme(string instrument, GateSide side, double price) =>
            Command(instrument, g => g.SetExtreme(side, price, Now()));

        public GateCommandResult Arm(string instrument, PendingArm arm)
        {
            if (arm != null && !AtmTemplateExists(arm.AtmTemplate))
            {
                return GateCommandResult.Rejected("ATM template \"" + arm.AtmTemplate
                    + "\" was not found in Documents\\NinjaTrader 8\\templates\\AtmStrategy — type it exactly as Chart Trader shows it.");
            }
            return Command(instrument, g => g.ArmEntry(arm));
        }

        public GateCommandResult Disarm(string instrument) => Command(instrument, g => g.Disarm());

        public GateCommandResult AnswerTrend(string instrument, GateTrend trend, long forHourEnd) =>
            Command(instrument, g => g.AnswerTrend(trend, forHourEnd));

        /// <summary>
        /// Feeds call this while holding their own lock (so bars apply in order) and then call
        /// Carry after releasing it, so no NinjaTrader order call runs under any gate lock.
        /// </summary>
        internal IReadOnlyList<GateAction> ApplyBars(string instrument, GateTimeframe tf, IReadOnlyList<GateBar> bars, bool history)
        {
            var actions = new List<GateAction>();
            lock (sync)
            {
                InstrumentGate gate;
                if (!gates.TryGetValue(instrument, out gate)) return actions;
                if (history)
                {
                    actions.AddRange(gate.LoadHistory(tf, bars));
                    if (tf == GateTimeframe.M1) actions.AddRange(gate.SetOneMinuteFeed(true).Actions);
                }
                else
                {
                    foreach (var bar in bars) actions.AddRange(gate.OnBarClosed(tf, bar));
                }
            }
            return actions;
        }

        internal void Carry(string instrument, IReadOnlyList<GateAction> actions)
        {
            Execute(instrument, actions);
            Changed(instrument);
        }

        internal void OnFeedFailed(string instrument, GateTimeframe tf, string message)
        {
            RaiseAlert(instrument + " " + InstrumentGate.Label(tf) + " bars could not load: " + message);
            if (tf == GateTimeframe.M1) SetOneMinuteFeed(instrument, false);
        }

        internal void UpdatePosition(string account, string instrument, int signedQty)
        {
            if (!Settings.IsGated(account)) return;
            lock (sync)
            {
                positions[account + "|" + instrument] = signedQty;
                InstrumentGate gate;
                if (gates.TryGetValue(instrument, out gate)) gate.LeaderPositionQty = LeaderPosition(instrument);
            }
            Changed(instrument);
        }

        internal void SetGateEntryWorking(string instrument, long orderId, bool working)
        {
            lock (sync)
            {
                HashSet<long> ids;
                if (!workingEntries.TryGetValue(instrument, out ids))
                {
                    ids = new HashSet<long>();
                    workingEntries[instrument] = ids;
                }
                if (working) ids.Add(orderId);
                else ids.Remove(orderId);
                InstrumentGate gate;
                if (gates.TryGetValue(instrument, out gate)) gate.GateEntryWorking = ids.Count > 0;
            }
            Changed(instrument);
        }

        internal void ReportCancel(string instrument, string reason)
        {
            lock (sync) lastCancel[instrument] = DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + " " + reason;
            Changed(instrument);
        }

        internal void Log(string instrument, string account, string evt, string detail)
        {
            try
            {
                GateLog.Append(LogPath, GateLog.FormatRow(DateTime.UtcNow, instrument, account, evt, detail));
            }
            catch (Exception e)
            {
                print("Setup gate log write failed: " + e.Message);
            }
        }

        internal void RaiseAlert(string message)
        {
            print("SETUP GATE: " + message);
            var handler = AlertRaised;
            if (handler != null) handler(message);
        }

        private GateCommandResult Command(string instrument, Func<InstrumentGate, GateCommandResult> run)
        {
            GateCommandResult result;
            lock (sync)
            {
                InstrumentGate gate;
                if (instrument == null || !gates.TryGetValue(instrument, out gate))
                    return GateCommandResult.Rejected("Track an instrument first.");
                result = run(gate);
                if (gate.InputsChanged)
                {
                    Save();
                    gate.MarkInputsSaved();
                }
            }
            Execute(instrument, result.Actions);
            Changed(instrument);
            return result;
        }

        private void Execute(string instrument, IReadOnlyList<GateAction> actions)
        {
            foreach (var action in actions)
            {
                switch (action.Kind)
                {
                    case GateActionKind.FireEntry:
                        Log(instrument, action.Arm.Account, GateEvents.Fire, action.Detail);
                        string error = SubmitEntry(instrument, action.Arm);
                        if (error != null)
                        {
                            Log(instrument, action.Arm.Account, GateEvents.Cancel, "Entry could not be submitted: " + error);
                            RaiseAlert(instrument + ": the armed entry could not be submitted — " + error);
                        }
                        break;
                    case GateActionKind.CancelArm:
                        Log(instrument, action.Arm != null ? action.Arm.Account : null, GateEvents.Disarm, action.Detail);
                        break;
                    case GateActionKind.PromptTrend:
                        var prompt = TrendPromptRequested;
                        if (prompt != null) prompt(instrument);
                        break;
                    default:
                        Log(instrument, null, action.Event, action.Detail);
                        break;
                }
            }
        }

        /// <summary>Spec §6 fire: market or limit entry named "Entry" (ATM requirement) with the armed ATM template.</summary>
        private string SubmitEntry(string instrumentName, PendingArm arm)
        {
            Account account = null;
            lock (Account.All)
            {
                foreach (Account candidate in Account.All)
                {
                    if (candidate.Name == arm.Account)
                    {
                        account = candidate;
                        break;
                    }
                }
            }
            if (account == null) return "account " + arm.Account + " was not found";
            var instrument = Instrument.GetInstrument(instrumentName, false);
            if (instrument == null) return "instrument " + instrumentName + " was not found";

            try
            {
                bool market = arm.Kind == EntryKind.Market;
                var order = account.CreateOrder(
                    instrument,
                    arm.Side == GateSide.Long ? OrderAction.Buy : OrderAction.SellShort,
                    market ? OrderType.Market : OrderType.Limit,
                    OrderEntry.Manual,
                    market ? TimeInForce.Day : TimeInForce.Gtc,
                    arm.Quantity,
                    market ? 0 : arm.LimitPrice,
                    0,
                    string.Empty,
                    "Entry",
                    NinjaTrader.Core.Globals.MaxDate,
                    null);
                GateEntryNames.Register(order.Id.ToString(CultureInfo.InvariantCulture), arm.Kind);
                enforcer.MarkGateEntry(order, arm.Kind, instrumentName, arm.Side == GateSide.Long);
                NinjaTrader.NinjaScript.AtmStrategy.StartAtmStrategy(arm.AtmTemplate, order);
                return null;
            }
            catch (Exception e)
            {
                return e.Message;
            }
        }

        private void SetOneMinuteFeed(string instrument, bool healthy)
        {
            IReadOnlyList<GateAction> actions;
            lock (sync)
            {
                InstrumentGate gate;
                if (!gates.TryGetValue(instrument, out gate)) return;
                actions = gate.SetOneMinuteFeed(healthy).Actions;
            }
            Execute(instrument, actions);
            Changed(instrument);
        }

        private void OnConnectionStatusUpdate(object sender, ConnectionStatusEventArgs e)
        {
            // Broker accounts appear once their (order or price) connection is up; re-subscribe on
            // every connect and re-check that every configured account exists.
            if (e.Status == ConnectionStatus.Connected || e.PriceStatus == ConnectionStatus.Connected)
            {
                enforcer.SubscribeAll();
                CheckAccounts();
            }

            bool anyBefore;
            bool anyAfter;
            lock (sync)
            {
                anyBefore = priceStatus.Values.Any(s => s == ConnectionStatus.Connected);
                if (e.Connection != null) priceStatus[e.Connection] = e.PriceStatus;
                anyAfter = priceStatus.Values.Any(s => s == ConnectionStatus.Connected);
            }

            if (e.PriceStatus == ConnectionStatus.Connected && e.PreviousPriceStatus != ConnectionStatus.Connected)
            {
                foreach (var feed in AllFeeds()) feed.Restart();
            }
            else if (anyBefore && !anyAfter)
            {
                // Only when no connection is left providing prices: one prop connection dropping
                // must not block every instrument.
                foreach (string instrument in TrackedInstruments()) SetOneMinuteFeed(instrument, false);
                RaiseAlert("Price data connection lost — entries are blocked until bars reload.");
            }
        }

        private void CheckAccounts()
        {
            foreach (string problem in Settings.UnmatchedAccounts(enforcer.AccountNames()))
            {
                bool first;
                lock (sync) first = reportedAccountProblems.Add(problem);
                if (first) RaiseAlert(problem);
            }
        }

        private static bool AtmTemplateExists(string name)
        {
            if (string.IsNullOrWhiteSpace(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) return false;
            string folder = Path.Combine(NinjaTrader.Core.Globals.UserDataDir, "templates", "AtmStrategy");
            return File.Exists(Path.Combine(folder, name + ".xml"));
        }

        private List<GateBarFeed> AllFeeds()
        {
            lock (sync) return feeds.Values.SelectMany(list => list).ToList();
        }

        private int LeaderPosition(string instrument)
        {
            foreach (string account in Settings.GatedAccounts)
            {
                int qty;
                if (positions.TryGetValue(account + "|" + instrument, out qty) && qty != 0) return qty;
            }
            return 0;
        }

        private void Save()
        {
            try
            {
                GateStateStore.Save(StatePath, state);
            }
            catch (Exception e)
            {
                RaiseAlert("Setup gate state could not be saved: " + e.Message);
            }
        }

        private void Changed(string instrument)
        {
            var handler = GateChanged;
            if (handler != null) handler(instrument);
        }

        private static long Now() => DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    }
}
