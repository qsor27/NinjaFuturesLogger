package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLogger_WritesEntriesToFile(t *testing.T) {
	tmp := t.TempDir()
	logPath := filepath.Join(tmp, "launcher.log")

	lg, err := NewLogger(logPath)
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}

	lg.Info("starting up", "port", 8000)
	lg.Warn("port conflict", "port", 8000, "fallback", 8001)
	lg.Error("boom", "detail", "something broke")
	lg.Close()

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	content := string(data)
	for _, needle := range []string{
		"starting up",
		"port=8000",
		"port conflict",
		"fallback=8001",
		"boom",
		"detail=\"something broke\"",
		"INFO",
		"WARN",
		"ERROR",
	} {
		if !strings.Contains(content, needle) {
			t.Errorf("log missing %q; got:\n%s", needle, content)
		}
	}
}

func TestLogger_CreatesParentDirectories(t *testing.T) {
	tmp := t.TempDir()
	logPath := filepath.Join(tmp, "nested", "deep", "launcher.log")

	lg, err := NewLogger(logPath)
	if err != nil {
		t.Fatalf("NewLogger: %v", err)
	}
	lg.Info("hello")
	lg.Close()

	if _, err := os.Stat(logPath); err != nil {
		t.Errorf("log file not created: %v", err)
	}
}
