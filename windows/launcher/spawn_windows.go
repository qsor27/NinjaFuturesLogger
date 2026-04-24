//go:build windows

package main

import (
	"context"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

// jobHandle is kept for the lifetime of the launcher. When the launcher
// exits (clean or crash), the OS closes all handles the process owns;
// because the job has KILL_ON_JOB_CLOSE, any assigned child processes
// terminate at the same time. This prevents orphaned pythonw.exe processes
// if the launcher dies unexpectedly.
var jobHandle windows.Handle

// SpawnPython starts the bundled Python interpreter running main.py with
// the given port and data directory env vars. The child is assigned to a
// Windows Job Object so orphans can't linger if this launcher crashes.
// stderr is captured into stderrSink. stdout is discarded.
func SpawnPython(
	ctx context.Context,
	installDir string,
	port int,
	dataDir string,
	stderrSink io.Writer,
) (*exec.Cmd, error) {
	pythonw := filepath.Join(installDir, "python", "pythonw.exe")
	script := filepath.Join(installDir, "app", "main.py")

	cmd := exec.CommandContext(ctx, pythonw, script)
	cmd.Env = append(cmd.Environ(),
		fmt.Sprintf("FTL_PORT=%d", port),
		fmt.Sprintf("FTL_DATA_DIR=%s", dataDir),
		fmt.Sprintf("PYTHONPATH=%s;%s",
			filepath.Join(installDir, "site-packages"),
			filepath.Join(installDir, "app"),
		),
	)
	// CREATE_SUSPENDED so we can assign the process to our Job Object BEFORE
	// it starts executing. This closes a race window where the child could
	// run and spawn its own children outside the job.
	const createSuspended = 0x00000004
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: createSuspended,
	}
	cmd.Stderr = stderrSink
	cmd.Stdout = io.Discard

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start python: %w", err)
	}

	if err := ensureJobObject(); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("create job object: %w", err)
	}

	processHandle, err := windows.OpenProcess(
		windows.PROCESS_ALL_ACCESS, false, uint32(cmd.Process.Pid),
	)
	if err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("open child process: %w", err)
	}
	defer windows.CloseHandle(processHandle)

	if err := windows.AssignProcessToJobObject(jobHandle, processHandle); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("assign to job: %w", err)
	}

	if err := resumePrimaryThread(cmd.Process.Pid); err != nil {
		_ = cmd.Process.Kill()
		return nil, fmt.Errorf("resume child thread: %w", err)
	}

	return cmd, nil
}

// ensureJobObject creates a process-wide job object with
// JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. Idempotent.
func ensureJobObject() error {
	if jobHandle != 0 {
		return nil
	}
	h, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return err
	}

	var info windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	_, err = windows.SetInformationJobObject(
		h,
		windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)),
		uint32(unsafe.Sizeof(info)),
	)
	if err != nil {
		_ = windows.CloseHandle(h)
		return err
	}
	jobHandle = h
	return nil
}

// resumePrimaryThread enumerates threads of the given process and resumes
// the first one (the primary thread, suspended at CreateProcess time via
// CREATE_SUSPENDED).
func resumePrimaryThread(pid int) error {
	snapshot, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPTHREAD, 0)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(snapshot)

	var te windows.ThreadEntry32
	te.Size = uint32(unsafe.Sizeof(te))
	if err := windows.Thread32First(snapshot, &te); err != nil {
		return err
	}
	for {
		if te.OwnerProcessID == uint32(pid) {
			th, err := windows.OpenThread(windows.THREAD_SUSPEND_RESUME, false, te.ThreadID)
			if err == nil {
				_, _ = windows.ResumeThread(th)
				_ = windows.CloseHandle(th)
				return nil
			}
		}
		if err := windows.Thread32Next(snapshot, &te); err != nil {
			return fmt.Errorf("no primary thread found for pid %d: %w", pid, err)
		}
	}
}
