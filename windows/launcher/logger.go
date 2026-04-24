package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Logger is a minimal structured logger for the launcher. Thread-safe.
// Nil-safe: a nil *Logger is a no-op on all methods, so callers can log
// before the data directory is resolved without nil-guarding.
type Logger struct {
	mu sync.Mutex
	w  io.WriteCloser
}

// NewLogger opens (or creates/appends) a log file at path. Creates any
// missing parent directories. Returns an error only if the file can't be
// opened.
func NewLogger(path string) (*Logger, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return nil, err
	}
	return &Logger{w: f}, nil
}

// Close releases the underlying file. Safe to call on a nil *Logger.
func (l *Logger) Close() {
	if l == nil || l.w == nil {
		return
	}
	_ = l.w.Close()
}

func (l *Logger) Info(msg string, kv ...any)  { l.write("INFO ", msg, kv...) }
func (l *Logger) Warn(msg string, kv ...any)  { l.write("WARN ", msg, kv...) }
func (l *Logger) Error(msg string, kv ...any) { l.write("ERROR", msg, kv...) }

func (l *Logger) write(level, msg string, kv ...any) {
	if l == nil || l.w == nil {
		return
	}
	var sb strings.Builder
	sb.WriteString(time.Now().UTC().Format(time.RFC3339))
	sb.WriteString("  ")
	sb.WriteString(level)
	sb.WriteString("  ")
	sb.WriteString(msg)
	for i := 0; i+1 < len(kv); i += 2 {
		sb.WriteByte(' ')
		fmt.Fprintf(&sb, "%v", kv[i])
		sb.WriteByte('=')
		v := fmt.Sprintf("%v", kv[i+1])
		if strings.ContainsAny(v, " \t") {
			fmt.Fprintf(&sb, "%q", v)
		} else {
			sb.WriteString(v)
		}
	}
	sb.WriteByte('\n')

	l.mu.Lock()
	defer l.mu.Unlock()
	_, _ = io.WriteString(l.w, sb.String())
}
