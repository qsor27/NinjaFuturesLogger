<#
.SYNOPSIS
  Copies the Setup Gate NinjaScript into NinjaTrader 8 and backs up the files it replaces.
.DESCRIPTION
  Run from the repo root:  powershell -ExecutionPolicy Bypass -File ninjascript\install-gate.ps1
  Then in NinjaTrader: New -> NinjaScript Editor -> press F5 to compile, and restart NinjaTrader.
  Use -WhatIf to see what would be copied without changing anything.
#>
param([switch]$WhatIf)

$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$custom = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NinjaTrader 8\bin\Custom'
if (-not (Test-Path $custom)) { throw "NinjaTrader custom folder not found: $custom" }

$gateDir = Join-Path $custom 'AddOns\NinjaFuturesLoggerGate'
$indicators = Join-Path $custom 'Indicators'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$files = @()
$files += Get-ChildItem (Join-Path $source 'Gate') -Filter *.cs
$files += Get-ChildItem (Join-Path $source 'GateNt') -Filter *.cs

Write-Host "Setup Gate files -> $gateDir"
foreach ($f in $files) { Write-Host "  $($f.Name)" }
Write-Host "ExecutionExporter.cs -> $indicators (existing copy backed up as ExecutionExporter.cs.bak-$stamp)"
if ($WhatIf) { Write-Host 'WhatIf: nothing copied.'; return }

New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
Get-ChildItem $gateDir -Filter *.cs | Remove-Item -Force
foreach ($f in $files) { Copy-Item $f.FullName -Destination $gateDir -Force }

$exporter = Join-Path $indicators 'ExecutionExporter.cs'
if (Test-Path $exporter) { Copy-Item $exporter -Destination "$exporter.bak-$stamp" -Force }
Copy-Item (Join-Path $source 'ExecutionExporter.cs') -Destination $exporter -Force

Write-Host ''
Write-Host 'Done. In NinjaTrader: New -> NinjaScript Editor -> F5 (compile), then restart NinjaTrader.'
Write-Host "Then edit $([Environment]::GetFolderPath('MyDocuments'))\NinjaFuturesLogger\setup_gate_settings.txt and set GatedAccounts=Sim101 for the Sim test."
