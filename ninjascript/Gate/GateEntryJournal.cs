using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>
    /// Working gate entries by broker order id, persisted so a Gtc limit entry the gate fired is
    /// still recognised after a NinjaTrader restart (spec §6/§12a: its edits stay allowed, it keeps
    /// blocking a second arm, and its fill is still tagged). Never throws on load.
    /// </summary>
    public sealed class GateEntryJournal
    {
        private readonly Dictionary<string, EntryKind> entries = new Dictionary<string, EntryKind>(StringComparer.Ordinal);

        public int Count => entries.Count;

        public void Record(string orderId, EntryKind kind)
        {
            if (string.IsNullOrEmpty(orderId)) return;
            entries[orderId] = kind;
        }

        public void Forget(string orderId)
        {
            if (!string.IsNullOrEmpty(orderId)) entries.Remove(orderId);
        }

        public bool TryGet(string orderId, out EntryKind kind)
        {
            kind = EntryKind.Market;
            return !string.IsNullOrEmpty(orderId) && entries.TryGetValue(orderId, out kind);
        }

        public static void Save(string path, GateEntryJournal journal)
        {
            var sb = new StringBuilder();
            foreach (var pair in journal.entries) sb.Append(pair.Key).Append('|').Append(pair.Value).AppendLine();
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        }

        /// <summary>Missing, unreadable or malformed lines are skipped; never throws.</summary>
        public static GateEntryJournal Load(string path)
        {
            var journal = new GateEntryJournal();
            string[] lines;
            try
            {
                if (!File.Exists(path)) return journal;
                lines = File.ReadAllLines(path, Encoding.UTF8);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return journal;
            }
            foreach (string line in lines)
            {
                string[] f = line.Split('|');
                EntryKind kind;
                if (f.Length == 2 && f[0].Length > 0 && Enum.TryParse(f[1], false, out kind) && Enum.IsDefined(typeof(EntryKind), kind))
                    journal.entries[f[0]] = kind;
            }
            return journal;
        }
    }
}
