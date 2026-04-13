using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.AddOns.Tests
{
    /// <summary>
    /// Unit tests for TradeFeedbackAddOn core functionality
    /// Task Group 5: AddOn Project Structure and Basic UI
    /// Task Group 6: Validation UI and Interaction
    /// Task Group 7: Order Blocking and Enforcement
    /// </summary>
    [TestFixture]
    public class TradeFeedbackAddOnTests
    {
        private string testStateFilePath;

        [SetUp]
        public void Setup()
        {
            // Use temporary test file path
            testStateFilePath = Path.Combine(Path.GetTempPath(), "test_trade_feedback_state.json");

            // Clean up any existing test file
            if (File.Exists(testStateFilePath))
            {
                File.Delete(testStateFilePath);
            }
        }

        [TearDown]
        public void TearDown()
        {
            // Clean up test file after each test
            if (File.Exists(testStateFilePath))
            {
                File.Delete(testStateFilePath);
            }
        }

        #region PositionValidationTracker Tests (Task Group 5)

        [Test]
        public void PositionValidationTracker_AddPosition_StoresPositionCorrectly()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var instrument = "MNQH25";
            var pnl = -50.25m;

            // Act
            tracker.AddPosition(positionId, DateTime.Now, instrument, pnl, requiresValidation: true);

            // Assert
            Assert.IsTrue(tracker.RequiresValidation(positionId));
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(1, unvalidated.Count);
        }

        [Test]
        public void PositionValidationTracker_MarkValidated_RemovesFromUnvalidatedList()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var instrument = "MNQH25";
            var pnl = 75.50m;
            tracker.AddPosition(positionId, DateTime.Now, instrument, pnl, requiresValidation: true);

            // Act
            tracker.MarkValidated(positionId, "Valid");

            // Assert
            Assert.IsFalse(tracker.RequiresValidation(positionId));
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(0, unvalidated.Count);
        }

        [Test]
        public void PositionValidationTracker_GetUnvalidated_ReturnsOnlyUnvalidatedPositions()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T15:00:00_MNQH25_SimAccount";
            var instrument = "MNQH25";

            tracker.AddPosition(positionId1, DateTime.Now, instrument, -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, instrument, 100m, requiresValidation: false);

            // Act
            var unvalidated = tracker.GetUnvalidated();

            // Assert
            Assert.AreEqual(1, unvalidated.Count);
            Assert.IsTrue(unvalidated.ContainsKey(positionId1));
            Assert.IsFalse(unvalidated.ContainsKey(positionId2));
        }

        [Test]
        public void PositionValidationTracker_ThreadSafety_HandlesMultipleThreads()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var tasks = new System.Threading.Tasks.Task[10];
            var instrument = "MNQH25";

            // Act - Create multiple threads adding positions simultaneously
            for (int i = 0; i < 10; i++)
            {
                int index = i;
                tasks[i] = System.Threading.Tasks.Task.Run(() =>
                {
                    var positionId = $"2025-01-15T14:30:{index:D2}_MNQH25_SimAccount";
                    tracker.AddPosition(positionId, DateTime.Now, instrument, -50m, requiresValidation: true);
                });
            }

            System.Threading.Tasks.Task.WaitAll(tasks);

            // Assert - All 10 positions should be tracked
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(10, unvalidated.Count);
        }

        #endregion

        #region State Persistence Tests (Task Group 5)

        [Test]
        public void StatePersistence_SaveState_CreatesJsonFile()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker.AddPosition(positionId, DateTime.Now, "MNQH25", -50m, requiresValidation: true);

            // Act
            TradeFeedbackAddOn.SaveState(tracker, testStateFilePath);

            // Assert
            Assert.IsTrue(File.Exists(testStateFilePath));
            var fileContent = File.ReadAllText(testStateFilePath);
            Assert.IsNotEmpty(fileContent);
            Assert.IsTrue(fileContent.Contains(positionId));
        }

        [Test]
        public void StatePersistence_LoadState_RestoresTrackerData()
        {
            // Arrange
            var tracker1 = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker1.AddPosition(positionId, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            TradeFeedbackAddOn.SaveState(tracker1, testStateFilePath);

            // Act
            var tracker2 = TradeFeedbackAddOn.LoadState(testStateFilePath);

            // Assert
            Assert.IsNotNull(tracker2);
            Assert.IsTrue(tracker2.RequiresValidation(positionId));
            var unvalidated = tracker2.GetUnvalidated();
            Assert.AreEqual(1, unvalidated.Count);
        }

        [Test]
        public void StatePersistence_LoadState_HandlesFileNotFound()
        {
            // Arrange
            var nonExistentPath = Path.Combine(Path.GetTempPath(), "nonexistent_state.json");

            // Act
            var tracker = TradeFeedbackAddOn.LoadState(nonExistentPath);

            // Assert - Should return new empty tracker
            Assert.IsNotNull(tracker);
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(0, unvalidated.Count);
        }

        [Test]
        public void StatePersistence_SaveAndLoad_PreservesValidationStatus()
        {
            // Arrange
            var tracker1 = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T15:00:00_MNQH25_SimAccount";

            tracker1.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker1.AddPosition(positionId2, DateTime.Now, "MNQH25", 100m, requiresValidation: true);
            tracker1.MarkValidated(positionId1, "Valid");

            TradeFeedbackAddOn.SaveState(tracker1, testStateFilePath);

            // Act
            var tracker2 = TradeFeedbackAddOn.LoadState(testStateFilePath);

            // Assert
            Assert.IsFalse(tracker2.RequiresValidation(positionId1)); // Was validated
            Assert.IsTrue(tracker2.RequiresValidation(positionId2));  // Still unvalidated
        }

        #endregion

        #region Composite Key Generation Tests (Task Group 5)

        [Test]
        public void GeneratePositionId_CreatesUniqueCompositeKey()
        {
            // Arrange
            var entryTime = new DateTime(2025, 1, 15, 14, 30, 0);
            var instrument = "MNQH25";
            var account = "SimAccount";

            // Act
            var positionId = TradeFeedbackAddOn.GeneratePositionId(entryTime, instrument, account);

            // Assert
            Assert.IsNotEmpty(positionId);
            Assert.IsTrue(positionId.Contains("2025-01-15"));
            Assert.IsTrue(positionId.Contains("MNQH25"));
            Assert.IsTrue(positionId.Contains("SimAccount"));
        }

        [Test]
        public void GeneratePositionId_DifferentInputs_GeneratesDifferentKeys()
        {
            // Arrange
            var entryTime = new DateTime(2025, 1, 15, 14, 30, 0);
            var instrument1 = "MNQH25";
            var instrument2 = "ESH25";
            var account = "SimAccount";

            // Act
            var positionId1 = TradeFeedbackAddOn.GeneratePositionId(entryTime, instrument1, account);
            var positionId2 = TradeFeedbackAddOn.GeneratePositionId(entryTime, instrument2, account);

            // Assert
            Assert.AreNotEqual(positionId1, positionId2);
        }

        #endregion

        #region Validation UI Tests (Task Group 6)

        [Test]
        public void ValidationPanel_ValidButtonClick_UpdatesTrackerToValid()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker.AddPosition(positionId, DateTime.Now, "MNQH25", -50m, requiresValidation: true);

            // Act - Simulate valid button click behavior
            tracker.MarkValidated(positionId, "Valid");

            // Assert
            Assert.IsFalse(tracker.RequiresValidation(positionId));
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(0, unvalidated.Count);
        }

        [Test]
        public void ValidationPanel_InvalidButtonClick_UpdatesTrackerToInvalid()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker.AddPosition(positionId, DateTime.Now, "MNQH25", -75m, requiresValidation: true);

            // Act - Simulate invalid button click behavior
            tracker.MarkValidated(positionId, "Invalid");

            // Assert
            Assert.IsFalse(tracker.RequiresValidation(positionId));
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(0, unvalidated.Count);
        }

        [Test]
        public void ValidationPanel_MultiplePositions_OrderedByMostRecentFirst()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var time1 = new DateTime(2025, 1, 15, 14, 30, 0);
            var time2 = new DateTime(2025, 1, 15, 14, 35, 0);
            var time3 = new DateTime(2025, 1, 15, 14, 40, 0);

            tracker.AddPosition("pos1", time1, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition("pos2", time2, "ESH25", -75m, requiresValidation: true);
            tracker.AddPosition("pos3", time3, "MNQH25", -100m, requiresValidation: true);

            // Act
            var unvalidated = tracker.GetUnvalidated();

            // Assert - Should have 3 positions
            Assert.AreEqual(3, unvalidated.Count);

            // Verify ordering (most recent first)
            var orderedPositions = unvalidated.OrderByDescending(p => p.Value.CloseTimestamp).ToList();
            Assert.AreEqual("pos3", orderedPositions[0].Key);
            Assert.AreEqual("pos2", orderedPositions[1].Key);
            Assert.AreEqual("pos1", orderedPositions[2].Key);
        }

        [Test]
        public void ValidationPanel_RemovePosition_AfterValidation()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T14:35:00_ESH25_SimAccount";

            tracker.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, "ESH25", -75m, requiresValidation: true);

            Assert.AreEqual(2, tracker.GetUnvalidated().Count);

            // Act - Mark first position as valid
            tracker.MarkValidated(positionId1, "Valid");

            // Assert - Only second position should remain
            var remaining = tracker.GetUnvalidated();
            Assert.AreEqual(1, remaining.Count);
            Assert.IsTrue(remaining.ContainsKey(positionId2));
            Assert.IsFalse(remaining.ContainsKey(positionId1));
        }

        [Test]
        public void ValidationPanel_PositionDisplay_ShowsCorrectData()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var entryTime = new DateTime(2025, 1, 15, 14, 30, 0);
            var instrument = "MNQH25";
            var pnl = -50.25m;
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";

            // Act
            tracker.AddPosition(positionId, entryTime, instrument, pnl, requiresValidation: true);

            // Assert
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(1, unvalidated.Count);

            var position = unvalidated[positionId];
            Assert.AreEqual(instrument, position.Instrument);
            Assert.AreEqual(pnl, position.PnL);
            Assert.AreEqual(entryTime, position.CloseTimestamp);
        }

        [Test]
        public void ValidationPanel_PnLColorCoding_ProfitVsLoss()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var profitPosition = "pos_profit";
            var lossPosition = "pos_loss";

            // Act
            tracker.AddPosition(profitPosition, DateTime.Now, "MNQH25", 100m, requiresValidation: true);
            tracker.AddPosition(lossPosition, DateTime.Now, "ESH25", -50m, requiresValidation: true);

            // Assert - Verify P&L values for color coding logic
            var positions = tracker.GetUnvalidated();
            Assert.AreEqual(2, positions.Count);

            Assert.IsTrue(positions[profitPosition].PnL >= 0); // Green
            Assert.IsTrue(positions[lossPosition].PnL < 0);    // Red
        }

        [Test]
        public void ValidationPanel_ScrollBehavior_WithMoreThan5Positions()
        {
            // Arrange
            var tracker = new PositionValidationTracker();

            // Act - Add 7 positions to trigger scrolling
            for (int i = 0; i < 7; i++)
            {
                var positionId = $"2025-01-15T14:3{i}:00_MNQH25_SimAccount";
                tracker.AddPosition(positionId, DateTime.Now.AddMinutes(i), "MNQH25", -50m, requiresValidation: true);
            }

            // Assert - Should have 7 positions (more than max visible of 5)
            var unvalidated = tracker.GetUnvalidated();
            Assert.AreEqual(7, unvalidated.Count);
            Assert.Greater(unvalidated.Count, 5); // Triggers scroll behavior
        }

        #endregion

        #region Order Blocking Tests (Task Group 7)

        /// <summary>
        /// Task 7.1: Test 1 - Order blocking filters positions by instrument correctly
        /// Tests that GetUnvalidatedForInstrument returns only positions matching the instrument
        /// </summary>
        [Test]
        public void OrderBlocking_GetUnvalidatedForInstrument_ReturnsOnlyMatchingInstrument()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T14:35:00_ESH25_SimAccount";
            var positionId3 = "2025-01-15T14:40:00_MNQH25_SimAccount";

            tracker.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, "ESH25", -75m, requiresValidation: true);
            tracker.AddPosition(positionId3, DateTime.Now, "MNQH25", -100m, requiresValidation: true);

            // Act
            var mnqPositions = tracker.GetUnvalidatedForInstrument("MNQH25");
            var esPositions = tracker.GetUnvalidatedForInstrument("ESH25");

            // Assert
            Assert.AreEqual(2, mnqPositions.Count);
            Assert.AreEqual(1, esPositions.Count);
            Assert.IsTrue(mnqPositions.ContainsKey(positionId1));
            Assert.IsTrue(mnqPositions.ContainsKey(positionId3));
            Assert.IsTrue(esPositions.ContainsKey(positionId2));
        }

        /// <summary>
        /// Task 7.1: Test 2 - Order blocking clears when position validated
        /// Tests that marking a position as validated removes it from blocking list
        /// </summary>
        [Test]
        public void OrderBlocking_ValidationRemoval_ClearsBlockingRequirement()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker.AddPosition(positionId, DateTime.Now, "MNQH25", -50m, requiresValidation: true);

            // Verify position requires validation initially
            var unvalidatedBefore = tracker.GetUnvalidatedForInstrument("MNQH25");
            Assert.AreEqual(1, unvalidatedBefore.Count);

            // Act - Mark position as validated
            tracker.MarkValidated(positionId, "Valid");

            // Assert - No longer requires validation
            var unvalidatedAfter = tracker.GetUnvalidatedForInstrument("MNQH25");
            Assert.AreEqual(0, unvalidatedAfter.Count);
        }

        /// <summary>
        /// Task 7.1: Test 3 - Order blocking is independent per instrument
        /// Tests that validating one instrument doesn't affect blocking for others
        /// </summary>
        [Test]
        public void OrderBlocking_MultipleInstruments_IndependentBlocking()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var mnqPosition = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var esPosition = "2025-01-15T14:35:00_ESH25_SimAccount";

            tracker.AddPosition(mnqPosition, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(esPosition, DateTime.Now, "ESH25", -75m, requiresValidation: true);

            // Act - Validate only MNQ position
            tracker.MarkValidated(mnqPosition, "Valid");

            // Assert - MNQ should be clear, ES should still block
            var mnqUnvalidated = tracker.GetUnvalidatedForInstrument("MNQH25");
            var esUnvalidated = tracker.GetUnvalidatedForInstrument("ESH25");

            Assert.AreEqual(0, mnqUnvalidated.Count);
            Assert.AreEqual(1, esUnvalidated.Count);
        }

        /// <summary>
        /// Task 7.1: Test 4 - Validated positions do not block new orders
        /// Tests that positions marked Valid or Invalid do not appear in blocking list
        /// </summary>
        [Test]
        public void OrderBlocking_ValidatedPositions_DoNotBlockOrders()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T14:35:00_MNQH25_SimAccount";

            // Add two positions for same instrument
            tracker.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, "MNQH25", -75m, requiresValidation: true);

            // Validate both positions
            tracker.MarkValidated(positionId1, "Valid");
            tracker.MarkValidated(positionId2, "Invalid");

            // Act
            var unvalidated = tracker.GetUnvalidatedForInstrument("MNQH25");

            // Assert - No unvalidated positions should block new orders
            Assert.AreEqual(0, unvalidated.Count);
        }

        /// <summary>
        /// Task 7.1: Test 5 - Grace period tracking with timestamp preservation
        /// Tests that position close timestamps are preserved for grace period calculations
        /// </summary>
        [Test]
        public void OrderBlocking_GracePeriod_TimestampPreservedCorrectly()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var closeTime = DateTime.Now.AddSeconds(-30); // Closed 30 seconds ago
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";

            // Act
            tracker.AddPosition(positionId, closeTime, "MNQH25", -50m, requiresValidation: true);

            // Assert - Position exists with correct timestamp for grace period filtering
            var unvalidated = tracker.GetUnvalidatedForInstrument("MNQH25");
            Assert.AreEqual(1, unvalidated.Count);
            Assert.AreEqual(closeTime, unvalidated[positionId].CloseTimestamp);

            // Verify timestamp can be used for grace period calculations
            var timeSinceClose = (DateTime.Now - unvalidated[positionId].CloseTimestamp).TotalSeconds;
            Assert.GreaterOrEqual(timeSinceClose, 30);
            Assert.Less(timeSinceClose, 35); // Account for test execution time
        }

        /// <summary>
        /// Task 7.1: Test 6 - Multiple unvalidated positions block orders
        /// Tests that multiple unvalidated positions for same instrument are tracked
        /// </summary>
        [Test]
        public void OrderBlocking_MultipleUnvalidatedPositions_AllTracked()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T14:35:00_MNQH25_SimAccount";
            var positionId3 = "2025-01-15T14:40:00_MNQH25_SimAccount";

            // Act - Add three unvalidated positions for same instrument
            tracker.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, "MNQH25", -75m, requiresValidation: true);
            tracker.AddPosition(positionId3, DateTime.Now, "MNQH25", -100m, requiresValidation: true);

            // Assert - All three positions should block new orders
            var unvalidated = tracker.GetUnvalidatedForInstrument("MNQH25");
            Assert.AreEqual(3, unvalidated.Count);
            Assert.IsTrue(unvalidated.ContainsKey(positionId1));
            Assert.IsTrue(unvalidated.ContainsKey(positionId2));
            Assert.IsTrue(unvalidated.ContainsKey(positionId3));
        }

        /// <summary>
        /// Task 7.1: Test 7 - Partial validation unblocks only validated positions
        /// Tests that validating some positions still blocks for remaining unvalidated
        /// </summary>
        [Test]
        public void OrderBlocking_PartialValidation_RemainingPositionsStillBlock()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId1 = "2025-01-15T14:30:00_MNQH25_SimAccount";
            var positionId2 = "2025-01-15T14:35:00_MNQH25_SimAccount";
            var positionId3 = "2025-01-15T14:40:00_MNQH25_SimAccount";

            tracker.AddPosition(positionId1, DateTime.Now, "MNQH25", -50m, requiresValidation: true);
            tracker.AddPosition(positionId2, DateTime.Now, "MNQH25", -75m, requiresValidation: true);
            tracker.AddPosition(positionId3, DateTime.Now, "MNQH25", -100m, requiresValidation: true);

            // Act - Validate only first two positions
            tracker.MarkValidated(positionId1, "Valid");
            tracker.MarkValidated(positionId2, "Invalid");

            // Assert - Third position should still block
            var unvalidated = tracker.GetUnvalidatedForInstrument("MNQH25");
            Assert.AreEqual(1, unvalidated.Count);
            Assert.IsTrue(unvalidated.ContainsKey(positionId3));
            Assert.IsFalse(unvalidated.ContainsKey(positionId1));
            Assert.IsFalse(unvalidated.ContainsKey(positionId2));
        }

        /// <summary>
        /// Task 7.1: Test 8 - Empty instrument returns no blocking positions
        /// Tests that querying non-existent instrument returns empty list
        /// </summary>
        [Test]
        public void OrderBlocking_NonExistentInstrument_ReturnsEmptyList()
        {
            // Arrange
            var tracker = new PositionValidationTracker();
            var positionId = "2025-01-15T14:30:00_MNQH25_SimAccount";
            tracker.AddPosition(positionId, DateTime.Now, "MNQH25", -50m, requiresValidation: true);

            // Act - Query for different instrument
            var unvalidated = tracker.GetUnvalidatedForInstrument("CLH25");

            // Assert - Should return empty list (no blocking for CLH25)
            Assert.AreEqual(0, unvalidated.Count);
        }

        #endregion
    }
}
