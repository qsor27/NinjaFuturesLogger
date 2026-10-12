using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    /// <summary>Event names written to gate_log.csv (spec §12).</summary>
    public static class GateEvents
    {
        public const string Arm = "Arm";
        public const string Disarm = "Disarm";
        public const string Fire = "Fire";
        public const string Cancel = "Cancel";
        public const string SlipThrough = "SlipThrough";
        public const string TrendAnswer = "TrendAnswer";
        public const string LevelSet = "LevelSet";
        public const string ExtremeSet = "ExtremeSet";
        public const string Transition = "Transition";
    }

    /// <summary>Append-only CSV log of everything the gate decides.</summary>
    public static class GateLog
    {
        public const string Header = "Time,Instrument,Account,Event,Detail";
        private static readonly object FileLock = new object();

        public static string Escape(string field)
        {
            if (field == null) return "";
            if (field.IndexOfAny(new[] { ',', '"', '\n', '\r' }) < 0) return field;
            return "\"" + field.Replace("\"", "\"\"") + "\"";
        }

        public static string FormatRow(DateTime utc, string instrument, string account, string evt, string detail)
        {
            return string.Join(",",
                utc.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture),
                Escape(instrument), Escape(account), Escape(evt), Escape(detail));
        }

        public static void Append(string path, string row)
        {
            lock (FileLock)
            {
                string directory = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
                bool isNew = !File.Exists(path);
                var text = new StringBuilder();
                if (isNew) text.AppendLine(Header);
                text.AppendLine(row);
                File.AppendAllText(path, text.ToString(), new UTF8Encoding(false));
            }
        }
    }
}
