//go:build !windows

package main

import "fmt"

// ShowFatalError on non-Windows writes to stdout (used only by tests on
// Linux CI — production is Windows-only).
func ShowFatalError(title, body string) {
	fmt.Printf("[%s]\n%s\n", title, body)
}

// BuildFatalMessage — non-Windows variant with \n line endings (the
// Windows version uses \r\n for MessageBox compatibility).
func BuildFatalMessage(what string, err error, logPath string) string {
	msg := "NinjaFuturesLogger couldn't start.\n\n"
	msg += fmt.Sprintf("What happened:\n  %s\n\n", what)
	if err != nil {
		msg += fmt.Sprintf("Details: %v\n\n", err)
	}
	msg += "What to try:\n"
	msg += "  1. Make sure NinjaFuturesLogger isn't already running.\n"
	msg += "  2. Restart your computer if you recently installed or updated.\n"
	msg += "  3. Reinstall the app if the problem continues.\n\n"
	if logPath != "" {
		msg += fmt.Sprintf("More detail:\n  Logs are at %s\n", logPath)
	}
	return msg
}
