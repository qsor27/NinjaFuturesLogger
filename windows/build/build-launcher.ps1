<#
.SYNOPSIS
  Build the Go launcher with embedded icon + version metadata.
#>

$ErrorActionPreference = "Stop"

$RepoRoot    = Resolve-Path "$PSScriptRoot\..\..\"
$LauncherDir = Join-Path $RepoRoot "windows\launcher"
$PayloadDir  = Join-Path $RepoRoot "windows\payload"

# Locate Go. Local dev typically has it at "C:\Program Files\Go\bin\go.exe";
# GitHub Actions' actions/setup-go@v5 puts it under C:\hostedtoolcache\...
# and adds it to PATH. Check PATH first, then the local-dev fallback.
$goOnPath = Get-Command go -ErrorAction SilentlyContinue
if ($goOnPath) {
    $GoExe = $goOnPath.Source
} elseif (Test-Path "C:\Program Files\Go\bin\go.exe") {
    $GoExe = "C:\Program Files\Go\bin\go.exe"
} else {
    throw "Go not found. Install via 'winget install GoLang.Go' (local) or add actions/setup-go@v5 (CI) and retry."
}
Write-Host "Using Go: $GoExe"
if (-not (Test-Path $PayloadDir)) {
    New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null
}

# Resolve the version. Patched into versioninfo.json at build time (numeric
# 4-part form) and injected into main.Version via -ldflags -X (display form).
. "$PSScriptRoot\resolve-version.ps1"
$v = Resolve-Version
Write-Host "Version: $($v.Display)  (numeric: $($v.Numeric))"

Push-Location $LauncherDir
try {
    Write-Host "Ensuring goversioninfo is installed..."
    & $GoExe install github.com/josephspurrier/goversioninfo/cmd/goversioninfo@latest
    if ($LASTEXITCODE -ne 0) { throw "go install goversioninfo failed" }

    $goBin = & $GoExe env GOBIN
    if (-not $goBin) { $goBin = Join-Path (& $GoExe env GOPATH) "bin" }
    $gvTool = Join-Path $goBin "goversioninfo.exe"
    if (-not (Test-Path $gvTool)) {
        throw "goversioninfo not found at $gvTool after install"
    }

    # Build a temp versioninfo with the real version. Keep the checked-in
    # template at 0.0.0 as a placeholder -- we always override here.
    $parts = $v.Numeric -split '\.'
    $tmplJson = Get-Content versioninfo.json -Raw | ConvertFrom-Json
    $tmplJson.FixedFileInfo.FileVersion.Major    = [int]$parts[0]
    $tmplJson.FixedFileInfo.FileVersion.Minor    = [int]$parts[1]
    $tmplJson.FixedFileInfo.FileVersion.Patch    = [int]$parts[2]
    $tmplJson.FixedFileInfo.FileVersion.Build    = [int]$parts[3]
    $tmplJson.FixedFileInfo.ProductVersion.Major = [int]$parts[0]
    $tmplJson.FixedFileInfo.ProductVersion.Minor = [int]$parts[1]
    $tmplJson.FixedFileInfo.ProductVersion.Patch = [int]$parts[2]
    $tmplJson.FixedFileInfo.ProductVersion.Build = [int]$parts[3]
    $tmplJson.StringFileInfo.FileVersion    = $v.Display
    $tmplJson.StringFileInfo.ProductVersion = $v.Display
    $tmpVersionInfo = Join-Path $LauncherDir "versioninfo.build.json"
    $tmplJson | ConvertTo-Json -Depth 10 | Set-Content $tmpVersionInfo -Encoding ascii

    Write-Host "Generating resource.syso from versioninfo.build.json..."
    # -64 produces a 64-bit COFF .syso; without it Go 1.20+ linker rejects
    # the default 32-bit COFF with "unknown relocation type 7".
    & $gvTool -64 -o resource.syso $tmpVersionInfo
    if ($LASTEXITCODE -ne 0) { throw "goversioninfo failed" }

    Write-Host "Building NinjaFuturesLogger.exe..."
    $out = Join-Path $PayloadDir "NinjaFuturesLogger.exe"
    # Inject the display version into main.Version (Go -ldflags -X).
    # Do NOT set GOOS/GOARCH — native Windows amd64 build; cross-compilation
    # env vars break .syso linking on newer Go versions.
    & $GoExe build -ldflags="-H=windowsgui -s -w -X main.Version=$($v.Display)" -o $out .
    if ($LASTEXITCODE -ne 0) { throw "go build failed" }

    $size = "{0:N0}" -f (Get-Item $out).Length
    Write-Host "Built: $out ($size bytes)"
} finally {
    $syso = Join-Path $LauncherDir "resource.syso"
    if (Test-Path $syso) { Remove-Item $syso }
    $tmpJson = Join-Path $LauncherDir "versioninfo.build.json"
    if (Test-Path $tmpJson) { Remove-Item $tmpJson }
    Pop-Location
}
