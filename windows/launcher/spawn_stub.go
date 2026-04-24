//go:build !windows

package main

import (
	"context"
	"errors"
	"io"
	"os/exec"
)

func SpawnPython(
	_ context.Context,
	_ string, _ int, _ string,
	_ io.Writer,
) (*exec.Cmd, error) {
	return nil, errors.New("SpawnPython not implemented on this platform")
}
