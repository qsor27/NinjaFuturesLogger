//go:build windows

package main

import (
	"fmt"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	singletonMutexName = `Global\NinjaFuturesLogger.Singleton`
	windowClassName    = "NinjaFuturesLoggerMain"
)

// AcquireSingletonOrFocus tries to acquire a global named mutex. If another
// instance already holds it, locates the existing window by class name
// and brings it to the foreground, then returns ErrAlreadyRunning. The
// caller should exit 0 on that signal.
func AcquireSingletonOrFocus() error {
	name, err := windows.UTF16PtrFromString(singletonMutexName)
	if err != nil {
		return fmt.Errorf("utf16 convert mutex name: %w", err)
	}
	handle, err := windows.CreateMutex(nil, false, name)
	if err != nil {
		// CreateMutex sets GetLastError to ERROR_ALREADY_EXISTS when the
		// named mutex already exists; in that case err may be non-nil too.
		if err == windows.ERROR_ALREADY_EXISTS {
			focusExistingWindow()
			return ErrAlreadyRunning
		}
		return fmt.Errorf("CreateMutex: %w", err)
	}
	// Even when the handle is valid, GetLastError reports ERROR_ALREADY_EXISTS
	// if another process got there first. Check it explicitly.
	if windows.GetLastError() == windows.ERROR_ALREADY_EXISTS {
		_ = windows.CloseHandle(handle)
		focusExistingWindow()
		return ErrAlreadyRunning
	}
	// Hold the handle for the process lifetime. We don't close it; the OS
	// releases it when the process exits.
	_ = handle
	return nil
}

func focusExistingWindow() {
	user32 := windows.NewLazySystemDLL("user32.dll")
	findWindow := user32.NewProc("FindWindowW")
	setForeground := user32.NewProc("SetForegroundWindow")
	showWindow := user32.NewProc("ShowWindow")

	className, _ := syscall.UTF16PtrFromString(windowClassName)
	hwnd, _, _ := findWindow.Call(uintptr(unsafe.Pointer(className)), 0)
	if hwnd == 0 {
		return
	}
	const SW_RESTORE = 9
	showWindow.Call(hwnd, SW_RESTORE)
	setForeground.Call(hwnd)
}
