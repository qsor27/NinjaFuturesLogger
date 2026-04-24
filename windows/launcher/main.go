package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

// Version is set at build time via `-ldflags -X main.Version=v1.2.3`.
// Matches the Docker image tag and the Windows installer filename — all
// three come from windows/build/resolve-version.ps1.
var Version = "dev"

// lg is set once ResolveDataDir succeeds. Before that, fatalError has no
// log to write to (falls back to MessageBox-only).
var lg *Logger

func main() {
	if err := AcquireSingletonOrFocus(); err != nil {
		if errors.Is(err, ErrAlreadyRunning) {
			os.Exit(0)
		}
		fatalError("Couldn't acquire the singleton lock.", err, "")
	}

	dataDir, err := ResolveDataDir()
	if err != nil {
		fatalError("Couldn't find a place to store your data.", err, "")
	}
	logDir := filepath.Join(dataDir, "logs")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		fatalError("Couldn't create the logs directory.", err, "")
	}
	logPath := filepath.Join(logDir, "launcher.log")
	lg, _ = NewLogger(logPath)
	defer lg.Close()

	lg.Info("launcher_start", "version", Version, "data_dir", dataDir)

	port, err := ReadPort(dataDir)
	if err != nil {
		fatalError("Couldn't read configuration.", err, logPath)
	}
	lg.Info("port_read", "port", port)

	// Probe the port; if busy, persist default+1 and retry once. A richer
	// Win32 picker dialog is tracked as a future improvement -- today a
	// single fallback keeps the happy path simple and the error path loud.
	if err := TryBind(port); err != nil {
		lg.Warn("port_in_use", "port", port, "error", err.Error())
		newPort := port + 1
		if err := TryBind(newPort); err != nil {
			lg.Error("port_fallback_failed", "port", port, "fallback", newPort)
			fatalError(
				fmt.Sprintf(
					"Ports %d and %d are both busy. Close whatever is using them and try again.",
					port, newPort,
				),
				err, logPath,
			)
		}
		if err := WritePort(dataDir, newPort); err != nil {
			fatalError("Couldn't save the new port.", err, logPath)
		}
		lg.Info("port_fallback", "from", port, "to", newPort)
		port = newPort
	}

	installDir, err := currentInstallDir()
	if err != nil {
		fatalError("Couldn't find the app install directory.", err, logPath)
	}

	stderrPath := filepath.Join(logDir, "python-stderr.log")
	stderrFile, err := os.OpenFile(stderrPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		fatalError("Couldn't open python-stderr.log.", err, logPath)
	}
	defer stderrFile.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	lg.Info("spawning_python", "install_dir", installDir, "port", port)
	cmd, err := SpawnPython(ctx, installDir, port, dataDir, stderrFile)
	if err != nil {
		fatalError("Couldn't start the Python server.", err, logPath)
	}

	healthCtx, healthCancel := context.WithTimeout(ctx, 30*time.Second)
	defer healthCancel()
	if err := WaitForServer(healthCtx, port); err != nil {
		lg.Error("healthcheck_failed", "port", port, "error", err.Error())
		_ = cmd.Process.Kill()
		fatalError(
			"The app's internal server didn't respond within 30 seconds.\r\n"+
				"Check python-stderr.log (in the logs folder) for the actual error.",
			err, logPath,
		)
	}
	lg.Info("healthcheck_ok", "port", port)

	if err := cmd.Wait(); err != nil {
		lg.Error("python_exit_nonzero", "error", err.Error())
		fatalError(
			"The Python server stopped unexpectedly.\r\n"+
				"Check python-stderr.log (in the logs folder) for the actual error.",
			err, logPath,
		)
	}
	lg.Info("launcher_clean_exit")
}

func currentInstallDir() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Dir(exe), nil
}

// fatalError writes to the launcher log (if available), shows a
// user-visible MessageBox with what / try / where, then exits 1.
func fatalError(what string, err error, logPath string) {
	if lg != nil {
		detail := ""
		if err != nil {
			detail = err.Error()
		}
		lg.Error("fatal_error", "what", what, "detail", detail)
	}
	ShowFatalError("NinjaFuturesLogger", BuildFatalMessage(what, err, logPath))
	os.Exit(1)
}
