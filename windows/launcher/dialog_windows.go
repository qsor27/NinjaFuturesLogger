//go:build windows

package main

import (
	"fmt"

	"golang.org/x/sys/windows"
)

const (
	mbIconError     = 0x00000010
	mbOK            = 0x00000000
	mbSetForeground = 0x00010000
	mbTopMost       = 0x00040000
)

// ShowFatalError displays a modal Win32 error dialog to the user. Title
// is short; body is a user-friendly multi-paragraph explanation. Blocks
// until the user clicks OK.
func ShowFatalError(title, body string) {
	titleUTF16, _ := windows.UTF16PtrFromString(title)
	bodyUTF16, _ := windows.UTF16PtrFromString(body)
	_, _ = windows.MessageBox(0, bodyUTF16, titleUTF16,
		mbIconError|mbOK|mbSetForeground|mbTopMost)
}

// BuildFatalMessage assembles a user-friendly error message explaining
// what failed, what the user can try, and where to find more detail.
// If logPath is empty, the "More detail" section is omitted (useful when
// the failure occurred before the log file was opened).
func BuildFatalMessage(what string, err error, logPath string) string {
	var body string
	body += "NinjaFuturesLogger couldn't start.\r\n\r\n"
	body += "What happened:\r\n"
	body += fmt.Sprintf("  %s\r\n\r\n", what)
	if err != nil {
		body += fmt.Sprintf("Details: %v\r\n\r\n", err)
	}
	body += "What to try:\r\n"
	body += "  1. Make sure NinjaFuturesLogger isn't already running.\r\n"
	body += "  2. Restart your computer if you recently installed or updated the app.\r\n"
	body += "  3. Reinstall the app if the problem continues.\r\n\r\n"
	if logPath != "" {
		body += "More detail:\r\n"
		body += fmt.Sprintf("  Logs are at %s\r\n", logPath)
		body += "  Include them if you file a support request.\r\n"
	}
	return body
}
