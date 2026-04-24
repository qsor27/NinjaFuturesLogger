//go:build windows

package main

import "golang.org/x/sys/windows/registry"

func readRegistryDataDir() (string, error) {
	k, err := registry.OpenKey(
		registry.CURRENT_USER,
		`Software\NinjaFuturesLogger`,
		registry.QUERY_VALUE,
	)
	if err != nil {
		return "", err
	}
	defer k.Close()
	val, _, err := k.GetStringValue("DataDir")
	if err != nil {
		return "", err
	}
	return val, nil
}
