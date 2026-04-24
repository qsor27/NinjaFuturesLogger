# Windows installer — build instructions and smoke-test checklist

## Local build prereqs

- **Go 1.22+** — `winget install GoLang.Go` (or use an existing install; `build-launcher.ps1` checks PATH first, then falls back to `C:\Program Files\Go\bin\go.exe`)
- **Inno Setup 6** — `winget install JRSoftware.InnoSetup` (either per-user or machine-wide works; `build-installer.ps1` finds ISCC.exe in both)
- **PowerShell 5.1 or 7** — 5.1 ships with Windows; 7 is optional
- Python 3.11 is NOT required to BUILD the installer — the embeddable distribution is downloaded and bundled. But it IS required to run the pytest suite locally for regression testing.

## Local build (end-to-end)

From the repo root:

```powershell
pwsh windows/build/fetch-externals.ps1
pwsh windows/build/assemble-payload.ps1
pwsh windows/build/build-launcher.ps1
pwsh windows/build/build-installer.ps1
```

(Use `powershell -File ...` instead of `pwsh` if PowerShell 7 isn't installed.)

Output: `windows/installer/Output/NinjaFuturesLogger-Setup-<version>.exe` (~48 MB).

Each script is idempotent. If any step fails, fix the cause and re-run just that step.

## CI build

Tagging a stable semver release (`v*.*.*`, no pre-release suffix) triggers `.github/workflows/windows-installer.yml`, which runs all four scripts on `windows-latest` and attaches the `.exe` to the GitHub Release. Dev tags like `v1.2.3-dev.4` build the Docker image only — the Windows installer is intentionally skipped so the in-app "check for updates" banner only surfaces deliberate releases.

Manual re-runs via the Actions UI's **Run workflow** button also produce an installer, uploaded as a workflow artifact (not attached to a release).

## End-to-end smoke-test checklist

Run on a clean Windows 10 22H2+ or Windows 11 machine (or VM with a fresh user profile — WebView2 runtime state matters). Fresh VMs take ~10 minutes to spin up on Hyper-V with a Windows dev image.

### Install

- [ ] Double-click `NinjaFuturesLogger-Setup-<version>.exe`.
- [ ] **No UAC prompt** appears (per-user install).
- [ ] Wizard shows Welcome → License → Destination (default `%LOCALAPPDATA%\Programs\NinjaFuturesLogger`) → Data dir page (default `%LOCALAPPDATA%\NinjaFuturesLogger\data`) → Start Menu → Tasks → Ready → Installing.
- [ ] If WebView2 runtime is missing, the installer silently runs the bootstrapper during Installing.
- [ ] Completes in under 2 minutes on a modern SSD.
- [ ] Final page offers "Launch NinjaFuturesLogger" checked by default.

### First launch

- [ ] Clicking Launch opens a WebView2 window within 5 s.
- [ ] Window is titled "NinjaFuturesLogger".
- [ ] First-run wizard shows. Click through.
- [ ] If you have NinjaTrader 8 installed locally, the wizard detects it and offers to install the ExecutionExporter. Click Install.
- [ ] Follow the 4 NT compile steps (F11, F5, add indicator to any chart).
- [ ] Back in the wizard, "Receiving executions ✓" appears within 60 s of the first CSV being written.

### Single-instance enforcement

- [ ] With the app running, double-click the Start Menu shortcut again.
- [ ] No second window appears. The existing window comes to the foreground.
- [ ] Task Manager shows exactly **one** `NinjaFuturesLogger.exe` and **one** `pythonw.exe`.

### Port conflict

- [ ] Close the app. Start another process on port 8000 (e.g., `python -m http.server 8000`).
- [ ] Launch NinjaFuturesLogger. Launcher falls back to 8001 and persists it to `%LOCALAPPDATA%\NinjaFuturesLogger\data\config\app.json`.
- [ ] WebView2 window loads `http://127.0.0.1:8001/`.

### Data persistence

- [ ] Close the app. Verify `app.db` exists under the chosen data dir.
- [ ] Launch again. Trade data still shows.

### Error dialog

- [ ] Temporarily corrupt `app.json` (invalid JSON) to force a startup failure.
- [ ] Launch the app. A Windows MessageBox appears titled "NinjaFuturesLogger" with "What happened:", "What to try:", and "More detail:" sections pointing at `launcher.log`.
- [ ] Restore `app.json`.

### Uninstall

- [ ] Settings → Apps → NinjaFuturesLogger → Uninstall.
- [ ] Uninstaller prompts: "Also delete your trade data and logs?" (default NO).
- [ ] Answer NO. Uninstaller removes `%LOCALAPPDATA%\Programs\NinjaFuturesLogger\` but preserves `%LOCALAPPDATA%\NinjaFuturesLogger\data\`.
- [ ] Re-install. Data is intact.
- [ ] Re-uninstall. Answer YES. Data directory is gone.

**Known limitation:** the uninstall prompt always references the default data path. Users who installed with a custom data directory need to remove that manually — not detected at uninstall time because the registry entry is already gone by the time the prompt fires.

### Logs and support bundle

- [ ] While running, navigate to `/system/health` in the WebView2 window.
- [ ] Click "Download Support Bundle." Open the zip.
- [ ] Verify it contains `app.jsonl`, `python-stderr.log`, and `launcher.log`.

## Troubleshooting

### "Windows protected your PC"

v1 is unsigned. When a stranger downloads the installer from GitHub Releases, Windows SmartScreen shows a full-screen warning. Click "More info → Run anyway" to proceed. **This goes away once we buy a code-signing certificate** (tracked in the spec's deferred list).

### Launcher.log location

- Default data dir: `%LOCALAPPDATA%\NinjaFuturesLogger\data\logs\launcher.log`
- Custom data dir: `<chosen-dir>\logs\launcher.log` (check the registry at `HKCU\Software\NinjaFuturesLogger\DataDir` if you don't remember)

### "The app's internal server didn't respond within 30 seconds"

Means pythonw.exe started but didn't bind the port within 30 s. Check `python-stderr.log` next to `launcher.log` — the actual error (import failure, config parse error, etc.) will be there.
