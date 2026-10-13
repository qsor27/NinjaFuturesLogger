using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public enum EntryKind { Market, Limit }

    /// <summary>An entry the trader armed (spec §6): Chart Trader's selections snapshotted at click time.</summary>
    public sealed class PendingArm
    {
        public PendingArm(GateSide side, EntryKind kind, double limitPrice, string atmTemplate, string account, int quantity,
            bool counterTrend = false)
        {
            CounterTrend = counterTrend;
            Side = side;
            Kind = kind;
            LimitPrice = limitPrice;
            AtmTemplate = atmTemplate;
            Account = account;
            Quantity = quantity;
        }

        public GateSide Side { get; }
        public EntryKind Kind { get; }
        public double LimitPrice { get; }
        public string AtmTemplate { get; }
        public string Account { get; }
        public int Quantity { get; }

        /// <summary>The trader confirmed arming against the hourly trend.</summary>
        public bool CounterTrend { get; }

        /// <summary>Spec §9 panel echo, e.g. "ARMED MKT · 4ptSL-20ptTP · 1 ct".</summary>
        public string Describe()
        {
            string head = Kind == EntryKind.Market
                ? "ARMED MKT"
                : "ARMED LMT @ " + LimitPrice.ToString("0.00##", CultureInfo.InvariantCulture);
            return head + " · " + AtmTemplate + " · " + Quantity.ToString(CultureInfo.InvariantCulture) + " ct"
                + (CounterTrend ? " · counter-trend" : "");
        }
    }

    public enum GateActionKind { FireEntry, CancelArm, PromptTrend, Log }

    /// <summary>Something the NinjaTrader shell must do because of a bar close or a trader command.</summary>
    public sealed class GateAction
    {
        private GateAction(GateActionKind kind, PendingArm arm, string evt, string detail)
        {
            Kind = kind;
            Arm = arm;
            Event = evt;
            Detail = detail;
        }

        public GateActionKind Kind { get; }

        /// <summary>The arm to fire or that was cancelled; null for prompts and plain log entries.</summary>
        public PendingArm Arm { get; }

        /// <summary>A GateEvents name for the log; null for prompts.</summary>
        public string Event { get; }

        public string Detail { get; }

        public static GateAction Fire(PendingArm arm) =>
            new GateAction(GateActionKind.FireEntry, arm, GateEvents.Fire, arm.Describe());

        public static GateAction CancelArmed(PendingArm arm, string reason) =>
            new GateAction(GateActionKind.CancelArm, arm, GateEvents.Disarm, reason);

        public static GateAction Prompt() =>
            new GateAction(GateActionKind.PromptTrend, null, null, "Confirm the hourly trend.");

        public static GateAction LogEvent(string evt, string detail) =>
            new GateAction(GateActionKind.Log, null, evt, detail);
    }

    /// <summary>Outcome of a trader command: rejected with a reason, or done with actions to carry out.</summary>
    public sealed class GateCommandResult
    {
        private static readonly GateAction[] NoActions = new GateAction[0];

        private GateCommandResult(string error, IReadOnlyList<GateAction> actions)
        {
            Error = error;
            Actions = actions;
        }

        public string Error { get; }
        public bool Ok => Error == null;
        public IReadOnlyList<GateAction> Actions { get; }

        public static GateCommandResult Done() => new GateCommandResult(null, NoActions);
        public static GateCommandResult Done(IReadOnlyList<GateAction> actions) => new GateCommandResult(null, actions ?? NoActions);
        public static GateCommandResult Rejected(string error) => new GateCommandResult(error, NoActions);
    }

    /// <summary>
    /// Spec §12a. NinjaTrader requires ATM entry orders to be named "Entry", so the gate records
    /// which orders it fired here and ExecutionExporter writes the registered name into the CSV
    /// Name column. The names must match services/entry_method.py.
    /// </summary>
    public static class GateEntryNames
    {
        public const string MarketNextOpen = "GateMktNextOpen";
        public const string LimitNextOpen = "GateLmtNextOpen";

        /// <summary>Appended for an arm the trader confirmed against the hourly trend (CSV Name column).</summary>
        public const string CounterTrendSuffix = "CT";

        private static readonly Regex GateName = new Regex(@"^Gate(Mkt|Lmt)NextOpen(CT)?$");

        private static readonly object Sync = new object();
        private static readonly Dictionary<string, string> Names = new Dictionary<string, string>(StringComparer.Ordinal);

        public static string NameFor(EntryKind kind, bool counterTrend = false) =>
            (kind == EntryKind.Market ? MarketNextOpen : LimitNextOpen) + (counterTrend ? CounterTrendSuffix : "");

        public static bool IsGateName(string name) => name != null && GateName.IsMatch(name);

        public static void Register(string orderKey, EntryKind kind, bool counterTrend = false) =>
            RegisterName(orderKey, NameFor(kind, counterTrend));

        public static void RegisterName(string orderKey, string name)
        {
            if (string.IsNullOrEmpty(orderKey)) throw new ArgumentException("An order key is required.", nameof(orderKey));
            if (!IsGateName(name)) throw new ArgumentException("Not a gate entry name: " + name, nameof(name));
            lock (Sync) Names[orderKey] = name;
        }

        public static bool TryResolve(string orderKey, out string name)
        {
            name = null;
            if (string.IsNullOrEmpty(orderKey)) return false;
            lock (Sync) return Names.TryGetValue(orderKey, out name);
        }

        internal static void Clear()
        {
            lock (Sync) Names.Clear();
        }
    }
}
