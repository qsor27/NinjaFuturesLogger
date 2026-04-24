package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// ResolveDataDir returns the data directory for NinjaFuturesLogger.
//
// Priority:
//  1. FTL_LAUNCHER_DATA_DIR_OVERRIDE env var (used by tests and dev)
//  2. HKCU\Software\NinjaFuturesLogger\DataDir registry value (production, Windows only)
//  3. %LOCALAPPDATA%\NinjaFuturesLogger\data (final fallback, Windows)
func ResolveDataDir() (string, error) {
	if override := os.Getenv("FTL_LAUNCHER_DATA_DIR_OVERRIDE"); override != "" {
		return override, nil
	}
	if regPath, err := readRegistryDataDir(); err == nil && regPath != "" {
		return regPath, nil
	}
	local := os.Getenv("LOCALAPPDATA")
	if local == "" {
		return "", fmt.Errorf("LOCALAPPDATA not set and no override provided")
	}
	return filepath.Join(local, "NinjaFuturesLogger", "data"), nil
}

// ReadPort returns the configured Windows port (defaults to 8000).
func ReadPort(dataDir string) (int, error) {
	configPath := filepath.Join(dataDir, "config", "app.json")
	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return 8000, nil
		}
		return 0, fmt.Errorf("read app.json: %w", err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(data, &parsed); err != nil {
		return 0, fmt.Errorf("parse app.json: %w", err)
	}
	windowsVal, ok := parsed["windows"].(map[string]any)
	if !ok {
		return 8000, nil
	}
	portVal, ok := windowsVal["port"]
	if !ok {
		return 8000, nil
	}
	switch v := portVal.(type) {
	case float64:
		return int(v), nil
	case int:
		return v, nil
	default:
		return 0, fmt.Errorf("windows.port has unexpected type: %T", portVal)
	}
}

// WritePort persists a new port value into the `windows.port` field of
// app.json, preserving all other fields. Atomic tmp+rename.
func WritePort(dataDir string, port int) error {
	configPath := filepath.Join(dataDir, "config", "app.json")
	var parsed map[string]any
	data, err := os.ReadFile(configPath)
	if err == nil {
		if err := json.Unmarshal(data, &parsed); err != nil {
			return fmt.Errorf("parse app.json: %w", err)
		}
	} else if os.IsNotExist(err) {
		parsed = map[string]any{}
		if err := os.MkdirAll(filepath.Dir(configPath), 0o755); err != nil {
			return err
		}
	} else {
		return fmt.Errorf("read app.json: %w", err)
	}
	w, ok := parsed["windows"].(map[string]any)
	if !ok {
		w = map[string]any{}
	}
	w["port"] = port
	parsed["windows"] = w
	out, err := json.MarshalIndent(parsed, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal app.json: %w", err)
	}
	tmp := configPath + ".tmp"
	if err := os.WriteFile(tmp, out, 0o644); err != nil {
		return fmt.Errorf("write tmp: %w", err)
	}
	return os.Rename(tmp, configPath)
}
