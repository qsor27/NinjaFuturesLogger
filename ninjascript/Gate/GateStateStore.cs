using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class SideInputs
    {
        public ExtremeInput Extreme { get; set; }
        public Dictionary<GateTimeframe, LevelInput> Levels { get; } = new Dictionary<GateTimeframe, LevelInput>();
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
        public GateStateLoad(GateStateFile state, bool wasCorrupt, string backupPath)
        {
            State = state;
            WasCorrupt = wasCorrupt;
            BackupPath = backupPath;
        }

        public GateStateFile State { get; }
        public bool WasCorrupt { get; }
        public string BackupPath { get; }
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
                    if (inputs.Extreme != null)
                    {
                        sb.Append("E|").Append(pair.Key).Append('|').Append(side).Append('|')
                          .Append(inputs.Extreme.Price.ToString("R", Inv)).Append('|')
                          .Append(inputs.Extreme.SetAt.ToString(Inv)).AppendLine();
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
            if (!File.Exists(path)) return new GateStateLoad(new GateStateFile(), false, null);

            try
            {
                return new GateStateLoad(Parse(File.ReadAllLines(path, Encoding.UTF8)), false, null);
            }
            catch (FormatException)
            {
                string backup = path + ".bad";
                if (File.Exists(backup)) File.Delete(backup);
                File.Move(path, backup);
                return new GateStateLoad(new GateStateFile(), true, backup);
            }
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
                    state.GetOrAdd(f[1]).For(ParseEnum<GateSide>(f[2])).Extreme =
                        new ExtremeInput(ParseDouble(f[3]), ParseLong(f[4]));
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
