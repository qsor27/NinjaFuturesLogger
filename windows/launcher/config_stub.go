//go:build !windows

package main

import "errors"

func readRegistryDataDir() (string, error) {
	return "", errors.New("registry not available on this platform")
}
