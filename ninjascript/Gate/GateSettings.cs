using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>
    /// Setup Gate settings (spec Q17, §7, §8): which accounts are gated, which accounts a trade
    /// copier mirrors them into, the break-even offset, the copier window and how much bar history
    /// to replay. Plain key=value text so the trader can edit it in Notepad.
    /// </summary>
    public sealed class GateSettings
    {
        public const int DefaultBreakEvenTicks = 1;
        public const int DefaultFollowerWindowSeconds = 5;
        public const int DefaultHistoryDays = 5;

        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        public GateSettings(IEnumerable<string> gatedAccounts, IEnumerable<string> followerAccounts,
            int breakEvenTicks, int followerWindowSeconds, int historyDays)
        {
            GatedAccounts = Clean(gatedAccounts);
            FollowerAccounts = Clean(followerAccounts);
            BreakEvenTicks = breakEvenTicks;
            FollowerWindowSeconds = followerWindowSeconds;
            HistoryDays = historyDays;
        }

        public IReadOnlyList<string> GatedAccounts { get; }
        public IReadOnlyList<string> FollowerAccounts { get; }
        public int BreakEvenTicks { get; }
        public int FollowerWindowSeconds { get; }
        public int HistoryDays { get; }

        public bool IsGated(string account) => account != null && GatedAccounts.Contains(account, StringComparer.Ordinal);

        public bool IsFollower(string account) => account != null && FollowerAccounts.Contains(account, StringComparer.Ordinal);

        public static GateSettings Defaults() =>
            new GateSettings(new string[0], new string[0], DefaultBreakEvenTicks, DefaultFollowerWindowSeconds, DefaultHistoryDays);

        public string Serialize()
        {
            var sb = new StringBuilder();
            sb.AppendLine("# NinjaFuturesLogger setup-gate settings. Edit, save, then restart NinjaTrader.");
            sb.AppendLine("# Accounts whose entries must come from an armed setup, comma-separated (e.g. Sim101,APEX1234567).");
            sb.AppendLine("GatedAccounts=" + string.Join(",", GatedAccounts));
            sb.AppendLine("# Accounts a trade copier mirrors the gated account into, comma-separated.");
            sb.AppendLine("FollowerAccounts=" + string.Join(",", FollowerAccounts));
            sb.AppendLine("# After target 1 fills, move the stop to entry + this many ticks in your favour.");
            sb.AppendLine("BreakEvenTicks=" + BreakEvenTicks.ToString(Inv));
            sb.AppendLine("# Seconds a follower entry may lag the gated account's entry.");
            sb.AppendLine("FollowerWindowSeconds=" + FollowerWindowSeconds.ToString(Inv));
            sb.AppendLine("# Days of bar history replayed at startup.");
            sb.AppendLine("HistoryDays=" + HistoryDays.ToString(Inv));
            return sb.ToString();
        }

        public static GateSettings Parse(string text, List<string> problems)
        {
            IEnumerable<string> gated = new string[0];
            IEnumerable<string> followers = new string[0];
            int breakEven = DefaultBreakEvenTicks;
            int window = DefaultFollowerWindowSeconds;
            int days = DefaultHistoryDays;

            foreach (string raw in (text ?? "").Split('\n'))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal)) continue;
                int eq = line.IndexOf('=');
                if (eq <= 0)
                {
                    problems.Add("Ignored line: " + line);
                    continue;
                }
                string key = line.Substring(0, eq).Trim();
                string value = line.Substring(eq + 1).Trim();
                switch (key)
                {
                    case "GatedAccounts": gated = value.Split(','); break;
                    case "FollowerAccounts": followers = value.Split(','); break;
                    case "BreakEvenTicks": breakEven = ParseInt(key, value, 0, 100, DefaultBreakEvenTicks, problems); break;
                    case "FollowerWindowSeconds": window = ParseInt(key, value, 1, 120, DefaultFollowerWindowSeconds, problems); break;
                    case "HistoryDays": days = ParseInt(key, value, 1, 30, DefaultHistoryDays, problems); break;
                    default: problems.Add("Unknown setting: " + key); break;
                }
            }
            return new GateSettings(gated, followers, breakEven, window, days);
        }

        /// <summary>Missing file: write a commented template and return the defaults.</summary>
        public static GateSettings LoadOrCreate(string path, List<string> problems)
        {
            try
            {
                if (!File.Exists(path))
                {
                    var defaults = Defaults();
                    string directory = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                    File.WriteAllText(path, defaults.Serialize(), new UTF8Encoding(false));
                    problems.Add("Created " + path + " — add your gated account(s) there and restart NinjaTrader.");
                    return defaults;
                }
                return Parse(File.ReadAllText(path, Encoding.UTF8), problems);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                problems.Add("Could not read " + path + ": " + e.Message);
                return Defaults();
            }
        }

        private static int ParseInt(string key, string value, int min, int max, int fallback, List<string> problems)
        {
            int parsed;
            if (int.TryParse(value, NumberStyles.Integer, Inv, out parsed) && parsed >= min && parsed <= max) return parsed;
            problems.Add(key + " must be a whole number from " + min + " to " + max + "; using " + fallback + ".");
            return fallback;
        }

        private static IReadOnlyList<string> Clean(IEnumerable<string> names) =>
            (names ?? new string[0]).Select(n => (n ?? "").Trim()).Where(n => n.Length > 0)
                .Distinct(StringComparer.Ordinal).ToList();
    }
}
