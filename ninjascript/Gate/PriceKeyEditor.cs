using System;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate
{
    public sealed class PriceEdit
    {
        public PriceEdit(string text, int caret)
        {
            Text = text;
            Caret = caret;
        }

        public string Text { get; }
        public int Caret { get; }
    }

    /// <summary>
    /// NinjaTrader's chart window grabs keystrokes for its instrument selector, so a TextBox in the
    /// chart or Chart Trader never receives them. Price boxes handle each key themselves through this
    /// editor. Keys: "0"-"9", ".", "Back", "Delete", "Left", "Right", "Home", "End".
    /// </summary>
    public static class PriceKeyEditor
    {
        /// <summary>The edited text and caret, or null when the key isn't an editing key.</summary>
        public static PriceEdit Apply(string text, int selectionStart, int selectionLength, string key)
        {
            if (key == null) return null;
            text = text ?? "";
            int start = Math.Max(0, Math.Min(selectionStart, text.Length));
            int length = Math.Max(0, Math.Min(selectionLength, text.Length - start));
            string withoutSelection = text.Remove(start, length);

            if (key.Length == 1 && (char.IsDigit(key[0]) || key == "."))
            {
                if (key == "." && withoutSelection.Contains(".")) return new PriceEdit(text, start + length);
                return new PriceEdit(withoutSelection.Insert(start, key), start + 1);
            }

            switch (key)
            {
                case "Back":
                    if (length > 0) return new PriceEdit(withoutSelection, start);
                    if (start == 0) return new PriceEdit(text, 0);
                    return new PriceEdit(text.Remove(start - 1, 1), start - 1);
                case "Delete":
                    if (length > 0) return new PriceEdit(withoutSelection, start);
                    if (start >= text.Length) return new PriceEdit(text, start);
                    return new PriceEdit(text.Remove(start, 1), start);
                case "Left":
                    return new PriceEdit(text, length > 0 ? start : Math.Max(0, start - 1));
                case "Right":
                    return new PriceEdit(text, length > 0 ? start + length : Math.Min(text.Length, start + 1));
                case "Home":
                    return new PriceEdit(text, 0);
                case "End":
                    return new PriceEdit(text, text.Length);
                default:
                    return null;
            }
        }
    }
}
