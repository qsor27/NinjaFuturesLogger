using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class SideInputs
    {
        private readonly List<ExtremeInput> extremeEdits = new List<ExtremeInput>();

        /// <summary>
        /// Every edit of the low (Long) or high (Short), oldest first. The full history is kept and
        /// replayed by ExtremeTracker so editing the extreme can never revive a dead level.
        /// </summary>
        public IReadOnlyList<ExtremeInput> ExtremeEdits => extremeEdits;

        /// <summary>The latest edit, or null when the trader hasn't set one.</summary>
        public ExtremeInput Extreme => extremeEdits.Count == 0 ? null : extremeEdits[extremeEdits.Count - 1];

        public void EditExtreme(ExtremeInput edit)
        {
            if (edit == null) throw new ArgumentNullException(nameof(edit));
            if (extremeEdits.Count > 0 && edit.SetAt < Extreme.SetAt)
                throw new ArgumentException("Extreme edits must be in time order.", nameof(edit));
            extremeEdits.Add(edit);
        }

        public Dictionary<GateTimeframe, LevelInput> Levels { get; } = new Dictionary<GateTimeframe, LevelInput>();

        /// <summary>
        /// RequireBreakAfter of levels the trader removed, per timeframe. The next level set on that
        /// timeframe inherits it, so removing a dead level never skips "new extreme after death".
        /// </summary>
        public Dictionary<GateTimeframe, long> RemovedRequirements { get; } = new Dictionary<GateTimeframe, long>();

        /// <summary>Removes every extreme edit (the trader deleted the low/high).</summary>
        public void ClearExtreme() => extremeEdits.Clear();
    }

    public sealed class InstrumentInputs
    {
        public SideInputs Long { get; } = new SideInputs();
        public SideInputs Short { get; } = new SideInputs();

        public SideInputs For(GateSide side) => side == GateSide.Long ? Long : Short;
    }

    /// <summary>Trader inputs for every instrument contract. Arms and trend are never persisted.</summary>
    public sealed class GateStateFile
    {
        public Dictionary<string, InstrumentInputs> Instruments { get; } =
            new Dictionary<string, InstrumentInputs>(StringComparer.Ordinal);

        public InstrumentInputs GetOrAdd(string instrument)
        {
            InstrumentInputs inputs;
            if (!Instruments.TryGetValue(instrument, out inputs))
            {
                inputs = new InstrumentInputs();
                Instruments[instrument] = inputs;
            }
            return inputs;
        }
    }

    public sealed class GateStateLoad
    {
        public GateStateLoad(GateStateFile state, bool wasCorrupt, string backupPath, string error)
        {
            State = state;
            WasCorrupt = wasCorrupt;
            BackupPath = backupPath;
            Error = error;
        }

        public GateStateFile State { get; }
        public bool WasCorrupt { get; }
        public string BackupPath { get; }

        /// <summary>Set when the file exists but couldn't be read (locked, no access). State is empty.</summary>
        public string Error { get; }
    }

    /// <summary>Line-based, culture-invariant persistence of trader inputs (spec §10, §11).</summary>
    public static class GateStateStore
    {
        private const string Header = "# NinjaFuturesLogger setup-gate state v1";
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        public static void Save(string path, GateStateFile state)
        {
            var sb = new StringBuilder();
            sb.AppendLine(Header);
            foreach (var pair in state.Instruments)
            {
                foreach (GateSide side in new[] { GateSide.Long, GateSide.Short })
                {
                    var inputs = pair.Value.For(side);
                    foreach (var edit in inputs.ExtremeEdits)
                    {
                        sb.Append("E|").Append(pair.Key).Append('|').Append(side).Append('|')
                          .Append(edit.Price.ToString("R", Inv)).Append('|')
                          .Append(edit.SetAt.ToString(Inv)).AppendLine();
                    }
                    foreach (var removed in inputs.RemovedRequirements)
                    {
                        sb.Append("C|").Append(pair.Key).Append('|').Append(side).Append('|')
                          .Append(removed.Key).Append('|').Append(removed.Value.ToString(Inv)).AppendLine();
                    }
                    foreach (var level in inputs.Levels)
                    {
                        sb.Append("L|").Append(pair.Key).Append('|').Append(side).Append('|')
                          .Append(level.Key).Append('|')
                          .Append(level.Value.Price.ToString("R", Inv)).Append('|')
                          .Append(level.Value.SetAt.ToString(Inv)).Append('|')
                          .Append(level.Value.RequireBreakAfter.ToString(Inv)).AppendLine();
                    }
                }
            }

            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, sb.ToString(), Encoding.UTF8);
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
        }

        public static GateStateLoad Load(string path)
        {
            if (!File.Exists(path)) return new GateStateLoad(new GateStateFile(), false, null, null);

            string[] lines;
            try
            {
                lines = File.ReadAllLines(path, Encoding.UTF8);
            }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            {
                return new GateStateLoad(new GateStateFile(), false, null, "Could not read " + path + ": " + e.Message);
            }

            try
            {
                return new GateStateLoad(Parse(lines), false, null, null);
            }
            catch (FormatException)
            {
                return new GateStateLoad(new GateStateFile(), true, BackUp(path), null);
            }
        }

        /// <summary>Moves a corrupt file aside; returns where it went, or null if it couldn't be moved.</summary>
        private static string BackUp(string path)
        {
            string[] candidates =
            {
                path + ".bad",
                path + ".bad-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssfff", Inv),
            };
            foreach (string candidate in candidates)
            {
                try
                {
                    if (File.Exists(candidate)) File.Delete(candidate);
                    File.Move(path, candidate);
                    return candidate;
                }
                catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
                {
                    // try the next name
                }
            }
            return null;
        }

        private static GateStateFile Parse(string[] lines)
        {
            if (lines.Length == 0 || lines[0] != Header) throw new FormatException("missing header");

            var state = new GateStateFile();
            for (int i = 1; i < lines.Length; i++)
            {
                string line = lines[i];
                if (line.Length == 0) continue;
                string[] f = line.Split('|');
                if (f[0] == "E" && f.Length == 5)
                {
                    var side = state.GetOrAdd(f[1]).For(ParseEnum<GateSide>(f[2]));
                    try
                    {
                        side.EditExtreme(new ExtremeInput(ParseDouble(f[3]), ParseLong(f[4])));
                    }
                    catch (ArgumentException e)
                    {
                        throw new FormatException("bad line " + (i + 1) + ": " + e.Message);
                    }
                }
                else if (f[0] == "C" && f.Length == 5)
                {
                    state.GetOrAdd(f[1]).For(ParseEnum<GateSide>(f[2])).RemovedRequirements[ParseEnum<GateTimeframe>(f[3])] =
                        ParseLong(f[4]);
                }
                else if (f[0] == "L" && f.Length == 7)
                {
                    state.GetOrAdd(f[1]).For(ParseEnum<GateSide>(f[2])).Levels[ParseEnum<GateTimeframe>(f[3])] =
                        new LevelInput(ParseDouble(f[4]), ParseLong(f[5]), ParseLong(f[6]));
                }
                else
                {
                    throw new FormatException("bad line " + (i + 1));
                }
            }
            return state;
        }

        private static double ParseDouble(string s)
        {
            double v;
            if (!double.TryParse(s, NumberStyles.Float, Inv, out v)) throw new FormatException("bad number: " + s);
            return v;
        }

        private static long ParseLong(string s)
        {
            long v;
            if (!long.TryParse(s, NumberStyles.Integer, Inv, out v)) throw new FormatException("bad time: " + s);
            return v;
        }

        private static T ParseEnum<T>(string s) where T : struct
        {
            T v;
            if (!Enum.TryParse(s, false, out v) || !Enum.IsDefined(typeof(T), v))
                throw new FormatException("bad value: " + s);
            return v;
        }
    }
}
