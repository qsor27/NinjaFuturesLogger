package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestResolveDataDir_FallsBackToEnvOverride(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("FTL_LAUNCHER_DATA_DIR_OVERRIDE", tmp)
	got, err := ResolveDataDir()
	if err != nil {
		t.Fatalf("ResolveDataDir returned error: %v", err)
	}
	if got != tmp {
		t.Errorf("ResolveDataDir = %q, want %q", got, tmp)
	}
}

func TestReadPort_DefaultsTo8000WhenFileMissing(t *testing.T) {
	tmp := t.TempDir()
	got, err := ReadPort(tmp)
	if err != nil {
		t.Fatalf("ReadPort returned error: %v", err)
	}
	if got != 8000 {
		t.Errorf("ReadPort = %d, want 8000", got)
	}
}

func TestReadPort_ReadsExistingValue(t *testing.T) {
	tmp := t.TempDir()
	configDir := filepath.Join(tmp, "config")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatal(err)
	}
	payload := map[string]any{
		"windows": map[string]any{"port": 8765},
	}
	b, _ := json.Marshal(payload)
	if err := os.WriteFile(filepath.Join(configDir, "app.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := ReadPort(tmp)
	if err != nil {
		t.Fatalf("ReadPort returned error: %v", err)
	}
	if got != 8765 {
		t.Errorf("ReadPort = %d, want 8765", got)
	}
}

func TestWritePort_UpdatesFile(t *testing.T) {
	tmp := t.TempDir()
	configDir := filepath.Join(tmp, "config")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatal(err)
	}
	initial := map[string]any{
		"other":   "keep-me",
		"windows": map[string]any{"port": 8000},
	}
	b, _ := json.Marshal(initial)
	if err := os.WriteFile(filepath.Join(configDir, "app.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}

	if err := WritePort(tmp, 9123); err != nil {
		t.Fatalf("WritePort returned error: %v", err)
	}

	raw, err := os.ReadFile(filepath.Join(configDir, "app.json"))
	if err != nil {
		t.Fatal(err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(raw, &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed["other"] != "keep-me" {
		t.Errorf("other field lost: %v", parsed["other"])
	}
	w := parsed["windows"].(map[string]any)
	if w["port"].(float64) != 9123 {
		t.Errorf("port not updated: %v", w["port"])
	}
}
