<#
.SYNOPSIS
  Assemble the Windows installer payload: Python + deps + app source.
.DESCRIPTION
  Produces this structure under windows/payload/:
    python/                   (extracted embeddable distribution)
    site-packages/            (pip-installed from requirements-windows.txt)
    app/                      (repo Python source)
    ninjascript/              (ExecutionExporter.cs)
    externals/                (already populated by fetch-externals.ps1)
#>

$ErrorActionPreference = "Stop"

$RepoRoot    = Resolve-Path "$PSScriptRoot\..\..\"
$PayloadRoot = Join-Path $RepoRoot "windows\payload"
$Externals   = Join-Path $PayloadRoot "externals"
$PythonDir   = Join-Path $PayloadRoot "python"
$SitePkgs    = Join-Path $PayloadRoot "site-packages"
$AppDir      = Join-Path $PayloadRoot "app"
$NinjaDir    = Join-Path $PayloadRoot "ninjascript"

if (-not (Test-Path (Join-Path $Externals "python-embed.zip"))) {
    throw "externals/python-embed.zip missing. Run fetch-externals.ps1 first."
}

Write-Host "Clearing previous payload (preserving externals/)..."
foreach ($d in @($PythonDir, $SitePkgs, $AppDir, $NinjaDir)) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

Write-Host "Extracting Python embeddable..."
Expand-Archive -Path (Join-Path $Externals "python-embed.zip") -DestinationPath $PythonDir -Force

# Unlock site-packages + app imports in the embeddable distribution's ._pth.
# The embeddable ships with "#import site" commented out and PYTHONPATH
# ignored (._pth enables "isolated" mode). We must explicitly list every
# directory we want on sys.path:
#   ..\site-packages   — pip-installed Flask, pydantic, waitress, etc.
#   ..\app             — our Python source (app.py, routes/, services/, ...)
# Without ..\app, `from app import create_app` fails with ModuleNotFoundError
# even though app.py sits right next to main.py — because the script dir
# isn't auto-added to sys.path under ._pth isolation.
$pthFile = Get-ChildItem $PythonDir -Filter "python3*._pth" | Select-Object -First 1
if ($null -eq $pthFile) {
    throw "Could not find python3*._pth in $PythonDir"
}
Write-Host "Unlocking imports via $($pthFile.Name)..."
$content = Get-Content $pthFile.FullName
$content = $content | ForEach-Object {
    if ($_ -match "^#import site") { "import site" } else { $_ }
}
$content += "..\site-packages"
$content += "..\app"
$content | Set-Content $pthFile.FullName -Encoding ascii

Write-Host "Bootstrapping pip into the embedded interpreter..."
$getPipPath = Join-Path $Externals "get-pip.py"
if (-not (Test-Path $getPipPath)) {
    Write-Host "  Downloading get-pip.py..."
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath -UseBasicParsing
}
& (Join-Path $PythonDir "python.exe") $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip.py failed with exit $LASTEXITCODE" }

Write-Host "Installing requirements-windows.txt into site-packages/..."
New-Item -ItemType Directory -Force -Path $SitePkgs | Out-Null
& (Join-Path $PythonDir "python.exe") -m pip install `
    --target=$SitePkgs `
    --no-warn-script-location `
    -r (Join-Path $RepoRoot "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit $LASTEXITCODE" }

Write-Host "Copying app source..."
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
# Top-level .py files (app.py, config.py, db.py, main.py, wsgi.py, etc.)
Get-ChildItem $RepoRoot -File -Filter "*.py" | Copy-Item -Destination $AppDir -Force
# Module directories, excluding everything that isn't app code.
$excludeDirs = @(
    "tests", "docs", "__pycache__", ".git", ".venv", "data", "windows",
    ".github", ".playwright-mcp", "inbox", ".pytest_cache", ".ruff_cache",
    "site-packages", "node_modules", "memory"
)
Get-ChildItem $RepoRoot -Directory | Where-Object { $excludeDirs -notcontains $_.Name } | ForEach-Object {
    Copy-Item $_.FullName -Destination $AppDir -Recurse -Force
}

Write-Host "Copying ninjascript..."
New-Item -ItemType Directory -Force -Path $NinjaDir | Out-Null
Copy-Item (Join-Path $RepoRoot "ninjascript\*.cs") -Destination $NinjaDir -Force

Write-Host ""
Write-Host "Payload assembled at $PayloadRoot"
Write-Host "  python/          $(if (Test-Path (Join-Path $PythonDir 'python.exe')) { 'OK' } else { 'MISSING' })"
Write-Host "  site-packages/   $(((Get-ChildItem $SitePkgs -Directory) | Measure-Object).Count) packages"
Write-Host "  app/             $(((Get-ChildItem $AppDir -Recurse -File) | Measure-Object).Count) files"
Write-Host "  ninjascript/     $(((Get-ChildItem $NinjaDir -File) | Measure-Object).Count) files"
