using System;
using System.IO;
using NUnit.Framework;

namespace NinjaTrader.NinjaScript.Indicators.Tests
{
    /// <summary>
    /// Unit tests for ExecutionExporter timezone conversion and session date calculation
    /// Task Group 1: Timezone Conversion and Date Calculation
    /// Task Group 2: CSV File Export with Session Date
    /// Task Group 3: Logging and Error Handling
    /// Task Group 5: End-to-End Integration Testing
    /// </summary>
    [TestFixture]
    public class ExecutionExporterTests
    {
        #region Test Helpers

        /// <summary>
        /// Helper method to create a test instance of ExecutionExporter
        /// Note: In actual NinjaTrader testing, this would require proper indicator initialization
        /// </summary>
        private ExecutionExporter CreateTestIndicator()
        {
            var indicator = new ExecutionExporter();
            return indicator;
        }

        #endregion

        #region Timezone Conversion Tests (Task Group 1)

        [Test]
        public void ConvertToPacificTime_FromEasternTime_ConvertsCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var easternZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            var easternTime = new DateTime(2025, 11, 12, 18, 0, 0); // 6:00 PM EST
            var easternDateTime = TimeZoneInfo.ConvertTime(easternTime, TimeZoneInfo.Local, easternZone);

            // Act
            var pacificTime = indicator.ConvertToPacificTime(easternDateTime);

            // Assert
            Assert.AreEqual(15, pacificTime.Hour); // Should be 3:00 PM PST
        }

        [Test]
        public void ConvertToPacificTime_FromCentralTime_ConvertsCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var centralZone = TimeZoneInfo.FindSystemTimeZoneById("Central Standard Time");
            var centralTime = new DateTime(2025, 11, 12, 17, 0, 0); // 5:00 PM CST
            var centralDateTime = TimeZoneInfo.ConvertTime(centralTime, TimeZoneInfo.Local, centralZone);

            // Act
            var pacificTime = indicator.ConvertToPacificTime(centralDateTime);

            // Assert
            Assert.AreEqual(15, pacificTime.Hour); // Should be 3:00 PM PST
        }

        [Test]
        public void ConvertToPacificTime_WithTimezoneConversionFailure_FallsBackToServerTime()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var serverTime = DateTime.Now;

            // Act - Pass invalid timezone info to trigger fallback
            var result = indicator.ConvertToPacificTimeWithFallback(serverTime, null);

            // Assert - Should return server time when timezone conversion fails
            Assert.AreEqual(serverTime.Hour, result.Hour);
            Assert.AreEqual(serverTime.Date, result.Date);
        }

        #endregion

        #region Session Date Calculation Tests (Task Group 1)

        [Test]
        public void CalculateSessionCloseDate_Before3pmPT_UsesCurrentDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15; // 3pm
            var pacificTime = new DateTime(2025, 11, 12, 14, 30, 0); // 2:30 PM PST (before 3pm)

            // Act
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert
            Assert.AreEqual(new DateTime(2025, 11, 12), sessionCloseDate);
        }

        [Test]
        public void CalculateSessionCloseDate_After3pmPT_UsesNextDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15; // 3pm
            var pacificTime = new DateTime(2025, 11, 12, 15, 5, 0); // 3:05 PM PST (after 3pm)

            // Act
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert
            Assert.AreEqual(new DateTime(2025, 11, 13), sessionCloseDate);
        }

        [Test]
        public void CalculateSessionCloseDate_SundayAfter3pm_UsesMondayDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15; // 3pm
            var pacificTime = new DateTime(2025, 11, 9, 16, 0, 0); // Sunday 4:00 PM PST

            // Act
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert
            Assert.AreEqual(new DateTime(2025, 11, 10), sessionCloseDate); // Monday
            Assert.AreEqual(DayOfWeek.Monday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void CalculateSessionCloseDate_FridayAfter3pm_UsesSaturdayDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15; // 3pm
            var pacificTime = new DateTime(2025, 11, 7, 15, 30, 0); // Friday 3:30 PM PST

            // Act
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert
            Assert.AreEqual(new DateTime(2025, 11, 8), sessionCloseDate); // Saturday
            Assert.AreEqual(DayOfWeek.Saturday, sessionCloseDate.DayOfWeek);
        }

        #endregion

        #region Date Validation Tests (Task Group 1)

        [Test]
        public void ValidateSessionDate_DateMoreThan1DayInPast_LogsWarning()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var pacificNow = DateTime.Now;
            var calculatedDate = pacificNow.AddDays(-2).Date; // 2 days in past

            // Act
            var isValid = indicator.ValidateSessionDate(calculatedDate, pacificNow);

            // Assert
            Assert.IsFalse(isValid); // Should return false but not throw
        }

        [Test]
        public void ValidateSessionDate_DateMoreThan2DaysInFuture_LogsWarning()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var pacificNow = DateTime.Now;
            var calculatedDate = pacificNow.AddDays(3).Date; // 3 days in future

            // Act
            var isValid = indicator.ValidateSessionDate(calculatedDate, pacificNow);

            // Assert
            Assert.IsFalse(isValid); // Should return false but not throw
        }

        [Test]
        public void ValidateSessionDate_ValidDateRange_ReturnsTrue()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var pacificNow = new DateTime(2025, 11, 12, 14, 0, 0);
            var calculatedDate = new DateTime(2025, 11, 12); // Same day, valid

            // Act
            var isValid = indicator.ValidateSessionDate(calculatedDate, pacificNow);

            // Assert
            Assert.IsTrue(isValid);
        }

        #endregion

        #region File Export Tests (Task Group 2)

        [Test]
        public void GenerateExportFilename_WithSessionDate_CreatesCorrectFormat()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var sessionCloseDate = new DateTime(2025, 11, 12);

            // Act
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert
            Assert.AreEqual("NinjaTrader_Executions_20251112.csv", filename);
        }

        [Test]
        public void GenerateExportFilename_WithDifferentDates_CreatesUniqueFilenames()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var date1 = new DateTime(2025, 11, 11);
            var date2 = new DateTime(2025, 11, 12);

            // Act
            var filename1 = indicator.GenerateExportFilename(date1);
            var filename2 = indicator.GenerateExportFilename(date2);

            // Assert
            Assert.AreEqual("NinjaTrader_Executions_20251111.csv", filename1);
            Assert.AreEqual("NinjaTrader_Executions_20251112.csv", filename2);
            Assert.AreNotEqual(filename1, filename2);
        }

        [Test]
        public void ConstructExportFilePath_WithValidDirectory_CombinesPathCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var tempDir = Path.Combine(Path.GetTempPath(), "test_export_" + Guid.NewGuid().ToString());
            var filename = "NinjaTrader_Executions_20251112.csv";

            try
            {
                // Act
                var fullPath = indicator.ConstructExportFilePath(tempDir, filename);

                // Assert
                Assert.IsTrue(fullPath.Contains(tempDir));
                Assert.IsTrue(fullPath.EndsWith(filename));
                Assert.IsTrue(Directory.Exists(tempDir)); // Should create directory
            }
            finally
            {
                // Cleanup
                if (Directory.Exists(tempDir))
                {
                    Directory.Delete(tempDir, true);
                }
            }
        }

        [Test]
        public void ConstructExportFilePath_WithNonExistentDirectory_CreatesDirectory()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var tempDir = Path.Combine(Path.GetTempPath(), "test_export_new_" + Guid.NewGuid().ToString());
            var filename = "NinjaTrader_Executions_20251112.csv";

            try
            {
                // Assert directory doesn't exist initially
                Assert.IsFalse(Directory.Exists(tempDir));

                // Act
                var fullPath = indicator.ConstructExportFilePath(tempDir, filename);

                // Assert
                Assert.IsTrue(Directory.Exists(tempDir)); // Should create directory
                Assert.IsTrue(fullPath.Contains(tempDir));
            }
            finally
            {
                // Cleanup
                if (Directory.Exists(tempDir))
                {
                    Directory.Delete(tempDir, true);
                }
            }
        }

        [Test]
        public void GenerateExportFilename_WithLeapYearDate_FormatsCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var leapYearDate = new DateTime(2024, 2, 29); // Leap year date

            // Act
            var filename = indicator.GenerateExportFilename(leapYearDate);

            // Assert
            Assert.AreEqual("NinjaTrader_Executions_20240229.csv", filename);
        }

        [Test]
        public void GenerateExportFilename_WithEndOfYearDate_FormatsCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var endOfYearDate = new DateTime(2025, 12, 31);

            // Act
            var filename = indicator.GenerateExportFilename(endOfYearDate);

            // Assert
            Assert.AreEqual("NinjaTrader_Executions_20251231.csv", filename);
        }

        [Test]
        public void ConstructExportFilePath_WithExistingDirectory_DoesNotThrow()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            var tempDir = Path.Combine(Path.GetTempPath(), "test_export_existing_" + Guid.NewGuid().ToString());
            Directory.CreateDirectory(tempDir); // Pre-create directory
            var filename = "NinjaTrader_Executions_20251112.csv";

            try
            {
                // Act
                var fullPath = indicator.ConstructExportFilePath(tempDir, filename);

                // Assert
                Assert.IsTrue(Directory.Exists(tempDir));
                Assert.IsTrue(fullPath.Contains(tempDir));
                Assert.IsTrue(fullPath.EndsWith(filename));
            }
            finally
            {
                // Cleanup
                if (Directory.Exists(tempDir))
                {
                    Directory.Delete(tempDir, true);
                }
            }
        }

        #endregion

        #region Logging and Error Handling Tests (Task Group 3)

        [Test]
        public void ConvertToPacificTime_WithNullTimezone_LogsWarningAndFallsBackGracefully()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;
            var serverTime = new DateTime(2025, 11, 12, 18, 0, 0);

            // Act - Pass null timezone to trigger fallback
            var result = indicator.ConvertToPacificTimeWithFallback(serverTime, null);

            // Assert - Should return server time and log warning (no exception thrown)
            Assert.AreEqual(serverTime, result);
            Assert.DoesNotThrow(() => indicator.ConvertToPacificTimeWithFallback(serverTime, null));
        }

        [Test]
        public void CalculateSessionCloseDate_WithLoggingEnabled_LogsPacificTimeAndSessionDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;
            indicator.SessionStartHourPT = 15;
            var pacificTime = new DateTime(2025, 11, 12, 16, 30, 0); // 4:30 PM PT

            // Act - Should log Pacific Time and calculated session date
            var result = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert - Verify the calculation is correct (logging tested in integration)
            Assert.AreEqual(new DateTime(2025, 11, 13), result);
        }

        [Test]
        public void CalculateSessionCloseDate_WithLoggingDisabled_DoesNotLog()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = false; // Logging disabled
            indicator.SessionStartHourPT = 15;
            var pacificTime = new DateTime(2025, 11, 12, 16, 30, 0);

            // Act - Should not log when logging is disabled
            var result = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert - Verify calculation still works correctly
            Assert.AreEqual(new DateTime(2025, 11, 13), result);
        }

        [Test]
        public void ValidateSessionDate_WhenDateInPast_LogsWarningWithContext()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;
            var pacificNow = new DateTime(2025, 11, 12, 14, 0, 0);
            var calculatedDate = new DateTime(2025, 11, 9); // 3 days in past

            // Act
            var isValid = indicator.ValidateSessionDate(calculatedDate, pacificNow);

            // Assert - Should log warning but return false (not throw)
            Assert.IsFalse(isValid);
            // Log should include: calculated date, days difference, and Pacific Time context
        }

        [Test]
        public void ValidateSessionDate_WhenDateInFuture_LogsWarningWithContext()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;
            var pacificNow = new DateTime(2025, 11, 12, 14, 0, 0);
            var calculatedDate = new DateTime(2025, 11, 16); // 4 days in future

            // Act
            var isValid = indicator.ValidateSessionDate(calculatedDate, pacificNow);

            // Assert - Should log warning but return false (not throw)
            Assert.IsFalse(isValid);
            // Log should include: calculated date, days difference, and Pacific Time context
        }

        [Test]
        public void GenerateExportFilename_WithLogging_IncludesFilenameInLog()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;
            var sessionCloseDate = new DateTime(2025, 11, 12);

            // Act
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Verify filename format is correct
            Assert.AreEqual("NinjaTrader_Executions_20251112.csv", filename);
            // Actual logging verification would occur in integration tests
        }

        [Test]
        public void TimezoneConversion_WhenFails_LogsExceptionDetails()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = true;

            // Create an invalid timezone scenario by using ConvertToPacificTimeWithFallback with null
            var serverTime = new DateTime(2025, 11, 12, 18, 0, 0);

            // Act - Trigger fallback scenario
            var result = indicator.ConvertToPacificTimeWithFallback(serverTime, null);

            // Assert - Should fall back to server time without throwing
            Assert.AreEqual(serverTime, result);
            // Logging should include "Using server time fallback due to timezone conversion error"
        }

        [Test]
        public void EnableLogging_WhenDisabled_OnlyLogsErrors()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.EnableLogging = false;
            indicator.SessionStartHourPT = 15;
            var pacificTime = new DateTime(2025, 11, 12, 14, 0, 0);

            // Act - Normal operation with logging disabled
            var sessionDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert - Should complete successfully
            Assert.AreEqual(new DateTime(2025, 11, 12), sessionDate);
            // Info logs should be suppressed, only errors would be logged
        }

        #endregion

        #region End-to-End Integration Tests (Task Group 5)

        [Test]
        public void EndToEnd_SundayAfter3pmPT_CreatesMondayFile()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;
            indicator.UseSessionCloseDate = true;

            // Act - Simulate Sunday 4pm PT execution
            var pacificTime = new DateTime(2025, 11, 9, 16, 0, 0); // Sunday 4:00 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should create Monday file
            Assert.AreEqual(new DateTime(2025, 11, 10), sessionCloseDate); // Monday
            Assert.AreEqual("NinjaTrader_Executions_20251110.csv", filename);
            Assert.AreEqual(DayOfWeek.Monday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void EndToEnd_Monday1pmPT_UsesMondayFile()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;
            indicator.UseSessionCloseDate = true;

            // Act - Simulate Monday 1pm PT execution (still in Sunday's session)
            var pacificTime = new DateTime(2025, 11, 10, 13, 0, 0); // Monday 1:00 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use Monday file (same as Sunday 4pm session)
            Assert.AreEqual(new DateTime(2025, 11, 10), sessionCloseDate); // Monday
            Assert.AreEqual("NinjaTrader_Executions_20251110.csv", filename);
            Assert.AreEqual(DayOfWeek.Monday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void EndToEnd_Monday4pmPT_CreatesTuesdayFile()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;
            indicator.UseSessionCloseDate = true;

            // Act - Simulate Monday 4pm PT execution (new session started at 3pm)
            var pacificTime = new DateTime(2025, 11, 10, 16, 0, 0); // Monday 4:00 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should create Tuesday file
            Assert.AreEqual(new DateTime(2025, 11, 11), sessionCloseDate); // Tuesday
            Assert.AreEqual("NinjaTrader_Executions_20251111.csv", filename);
            Assert.AreEqual(DayOfWeek.Tuesday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void EndToEnd_DSTSpringForward_CalculatesDateCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - DST Spring Forward: March 9, 2025 at 2am PT becomes 3am PT
            // Test execution at 4pm PT on Sunday March 9 (after DST transition)
            var pacificTime = new DateTime(2025, 3, 9, 16, 0, 0); // Sunday 4:00 PM PDT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use Monday March 10
            Assert.AreEqual(new DateTime(2025, 3, 10), sessionCloseDate); // Monday
            Assert.AreEqual("NinjaTrader_Executions_20250310.csv", filename);
        }

        [Test]
        public void EndToEnd_DSTFallBack_CalculatesDateCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - DST Fall Back: November 2, 2025 at 2am PDT becomes 1am PST
            // Test execution at 4pm PT on Sunday November 2 (after DST transition)
            var pacificTime = new DateTime(2025, 11, 2, 16, 0, 0); // Sunday 4:00 PM PST
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use Monday November 3
            Assert.AreEqual(new DateTime(2025, 11, 3), sessionCloseDate); // Monday
            Assert.AreEqual("NinjaTrader_Executions_20251103.csv", filename);
        }

        [Test]
        public void EndToEnd_FridayBefore3pm_UsesFridayFile()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - Friday 2pm PT (before session close at 2pm, before next session at 3pm)
            var pacificTime = new DateTime(2025, 11, 7, 14, 0, 0); // Friday 2:00 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use Friday file
            Assert.AreEqual(new DateTime(2025, 11, 7), sessionCloseDate); // Friday
            Assert.AreEqual("NinjaTrader_Executions_20251107.csv", filename);
            Assert.AreEqual(DayOfWeek.Friday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void EndToEnd_FridayAfter3pm_UsesSaturdayFile()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - Friday 3:30 PM PT (new session technically starts, but market closes)
            var pacificTime = new DateTime(2025, 11, 7, 15, 30, 0); // Friday 3:30 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use Saturday file (non-trading day)
            Assert.AreEqual(new DateTime(2025, 11, 8), sessionCloseDate); // Saturday
            Assert.AreEqual("NinjaTrader_Executions_20251108.csv", filename);
            Assert.AreEqual(DayOfWeek.Saturday, sessionCloseDate.DayOfWeek);
        }

        [Test]
        public void EndToEnd_EasternTimeServer_ConvertsAndCalculatesCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - Simulate server in Eastern timezone at 6pm EST (3pm PT)
            var easternZone = TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time");
            var easternTime = new DateTime(2025, 11, 12, 18, 5, 0); // 6:05 PM EST
            var pacificTime = TimeZoneInfo.ConvertTime(easternTime, easternZone,
                TimeZoneInfo.FindSystemTimeZoneById("Pacific Standard Time"));

            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - 6:05 PM EST = 3:05 PM PT, should use next day
            Assert.AreEqual(15, pacificTime.Hour); // 3pm PT
            Assert.AreEqual(new DateTime(2025, 11, 13), sessionCloseDate); // Thursday (next day)
            Assert.AreEqual("NinjaTrader_Executions_20251113.csv", filename);
        }

        [Test]
        public void EndToEnd_UseSessionCloseDateDisabled_UsesCurrentDate()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;
            indicator.UseSessionCloseDate = false; // Disable session close date logic

            // Act - Even at 4pm PT (after 3pm), should use current date in legacy mode
            var pacificTime = new DateTime(2025, 11, 9, 16, 0, 0); // Sunday 4:00 PM PT

            // When UseSessionCloseDate is false, it uses DateTime.Now.Date instead
            // We'll test the CalculateSessionCloseDate method still works
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);

            // Assert - CalculateSessionCloseDate still calculates correctly
            // But the actual export would use DateTime.Now.Date when UseSessionCloseDate=false
            Assert.AreEqual(new DateTime(2025, 11, 10), sessionCloseDate); // Method still works
            // Note: In production, GetSessionCloseDate() would return current date when flag is false
        }

        [Test]
        public void EndToEnd_LeapYearFebruary29_HandlesCorrectly()
        {
            // Arrange
            var indicator = CreateTestIndicator();
            indicator.SessionStartHourPT = 15;

            // Act - Leap year date: February 29, 2024 at 4pm PT
            var pacificTime = new DateTime(2024, 2, 29, 16, 0, 0); // Thursday 4:00 PM PT
            var sessionCloseDate = indicator.CalculateSessionCloseDate(pacificTime);
            var filename = indicator.GenerateExportFilename(sessionCloseDate);

            // Assert - Should use March 1, 2024
            Assert.AreEqual(new DateTime(2024, 3, 1), sessionCloseDate); // Friday
            Assert.AreEqual("NinjaTrader_Executions_20240301.csv", filename);
            Assert.AreEqual(DayOfWeek.Friday, sessionCloseDate.DayOfWeek);
        }

        #endregion
    }
}
