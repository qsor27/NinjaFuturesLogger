<#
.SYNOPSIS
  Invoke Inno Setup against installer.iss to produce the final setup.exe.
.DESCRIPTION
  Locates ISCC.exe across standard install locations (machine-wide and
  per-user) and compiles windows/installer/installer.iss. The payload at
  windows/payload/ must already be assembled (see fetch-externals.ps1,
  assemble-payload.ps1, build-launcher.ps1).
#>

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path "$PSScriptRoot\..\..\"

# Find ISCC.exe across all common install locations.
$candidates = @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "Could not find ISCC.exe. Install Inno Setup 6: winget install JRSoftware.InnoSetup"
}
Write-Host "Using ISCC: $iscc"

$iss = Join-Path $RepoRoot "windows\installer\installer.iss"

Write-Host "Compiling $iss ..."
& $iscc $iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE"
}

$outputDir = Join-Path $RepoRoot "windows\installer\Output"
Write-Host ""
Get-ChildItem $outputDir -Filter "*.exe" | ForEach-Object {
    $size = "{0:N0}" -f $_.Length
    Write-Host "Built: $($_.FullName) ($size bytes)"
}
