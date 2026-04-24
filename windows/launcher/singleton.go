package main

import "errors"

// ErrAlreadyRunning is returned by AcquireSingletonOrFocus when another
// launcher instance is already running (we focused its window; caller
// should exit 0).
var ErrAlreadyRunning = errors.New("another instance is already running")
