using NUnit.Framework;

namespace NinjaTrader.NinjaScript.NinjaFuturesLogger.Gate.Tests
{
    /// The chart window swallows keystrokes, so price boxes apply each key themselves.
    public class PriceKeyEditorTests
    {
        [Test]
        public void TypesDigitsAndOneDecimalPoint()
        {
            var e = PriceKeyEditor.Apply("3088", 4, 0, "0");
            Assert.That(e.Text, Is.EqualTo("30880"));
            Assert.That(e.Caret, Is.EqualTo(5));
            e = PriceKeyEditor.Apply(e.Text, e.Caret, 0, ".");
            Assert.That(e.Text, Is.EqualTo("30880."));
            Assert.That(PriceKeyEditor.Apply("30880.5", 7, 0, ".").Text, Is.EqualTo("30880.5"));
        }

        [Test]
        public void TypingReplacesTheSelection()
        {
            var e = PriceKeyEditor.Apply("30880.50", 0, 8, "3");
            Assert.That(e.Text, Is.EqualTo("3"));
            Assert.That(e.Caret, Is.EqualTo(1));
            // A selected "." can be replaced by another "."
            Assert.That(PriceKeyEditor.Apply("1.5", 1, 1, ".").Text, Is.EqualTo("1.5"));
        }

        [Test]
        public void BackspaceAndDelete()
        {
            var back = PriceKeyEditor.Apply("30880", 5, 0, "Back");
            Assert.That(back.Text, Is.EqualTo("3088"));
            Assert.That(back.Caret, Is.EqualTo(4));
            Assert.That(PriceKeyEditor.Apply("30880", 0, 0, "Back").Text, Is.EqualTo("30880"));
            var del = PriceKeyEditor.Apply("30880", 0, 0, "Delete");
            Assert.That(del.Text, Is.EqualTo("0880"));
            Assert.That(del.Caret, Is.EqualTo(0));
            Assert.That(PriceKeyEditor.Apply("30880", 1, 3, "Back").Text, Is.EqualTo("30"));
        }

        [Test]
        public void CaretMovement()
        {
            Assert.That(PriceKeyEditor.Apply("123", 2, 0, "Left").Caret, Is.EqualTo(1));
            Assert.That(PriceKeyEditor.Apply("123", 0, 0, "Left").Caret, Is.EqualTo(0));
            Assert.That(PriceKeyEditor.Apply("123", 1, 0, "Right").Caret, Is.EqualTo(2));
            Assert.That(PriceKeyEditor.Apply("123", 3, 0, "Right").Caret, Is.EqualTo(3));
            Assert.That(PriceKeyEditor.Apply("123", 2, 0, "Home").Caret, Is.EqualTo(0));
            Assert.That(PriceKeyEditor.Apply("123", 0, 0, "End").Caret, Is.EqualTo(3));
            Assert.That(PriceKeyEditor.Apply("12345", 1, 2, "Right").Caret, Is.EqualTo(3));
        }

        [Test]
        public void OtherKeysAreNotEditingKeys()
        {
            Assert.That(PriceKeyEditor.Apply("123", 0, 0, "A"), Is.Null);
            Assert.That(PriceKeyEditor.Apply("123", 0, 0, null), Is.Null);
        }
    }
}
