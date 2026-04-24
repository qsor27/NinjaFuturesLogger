# NinjaFuturesLogger launcher

Small Go binary that orchestrates the bundled Python interpreter for the
Windows installer. Not used in Docker dev.

## Build

From `windows/launcher/`:

```powershell
go build -ldflags="-H=windowsgui" -o NinjaFuturesLogger.exe
```

The `-H=windowsgui` flag prevents a console window from opening when the
user launches the app. An icon and version metadata are embedded by the
`windows/build/build-launcher.ps1` script (uses `goversioninfo`).

## Responsibilities

1. Resolve the data directory (registry -> %LOCALAPPDATA%).
2. Acquire a singleton mutex; focus existing window if already running.
3. Resolve the port; prompt the user on conflict; persist on change.
4. Spawn `python\pythonw.exe app\main.py` with env vars.
5. Capture child stderr to `<data>\logs\python-stderr.log`.
6. TCP-probe `127.0.0.1:<port>` to verify startup; show error dialog on failure.
7. Wait for the child to exit; exit with the same code.
