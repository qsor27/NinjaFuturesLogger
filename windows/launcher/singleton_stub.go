//go:build !windows

package main

// AcquireSingletonOrFocus on non-Windows is a no-op. Unit tests that run
// on Linux CI simply don't exercise the real mutex; Windows smoke tests
// verify the real behavior.
func AcquireSingletonOrFocus() error {
	return nil
}
