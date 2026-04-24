<#
.SYNOPSIS
  Download + SHA256-verify external dependencies for the Windows build.
.DESCRIPTION
  Fetches:
    1. python-<VERSION>-embed-amd64.zip from python.org (SHA256-pinned)
    2. MicrosoftEdgeWebView2Setup.exe from download.microsoft.com (moving target; no pin)
  Both land in windows/payload/externals/. Idempotent: skips any file that
  already exists with a matching SHA256.

  Compatible with Windows PowerShell 5.1 and PowerShell 7+.
  Preferred: pwsh (PowerShell 7). Works unchanged on 5.1.

  Version pinning intentional. When bumping Python, update the three
  constants below AND re-verify SHA256 against python.org.
#>

$ErrorActionPreference = "Stop"

# --- VERIFY THESE BEFORE COMMITTING -----------------------------------------
$PINNED_PYTHON_VERSION = "3.11.9"
$PINNED_PYTHON_URL     = "https://www.python.org/ftp/python/$PINNED_PYTHON_VERSION/python-$PINNED_PYTHON_VERSION-embed-amd64.zip"
$PINNED_PYTHON_SHA256  = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
# ----------------------------------------------------------------------------

$WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
# WebView2 bootstrapper is a moving target; we download fresh each build (no hash pin).

$RepoRoot     = Resolve-Path "$PSScriptRoot\..\..\"
$PayloadRoot  = Join-Path $RepoRoot "windows\payload"
$ExternalsDir = Join-Path $PayloadRoot "externals"

New-Item -ItemType Directory -Force -Path $ExternalsDir | Out-Null

function Get-FileSha256 {
    param([string]$Path)
    (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

function Download-IfNeeded {
    param(
        [string]$Url,
        [string]$DestPath,
        [string]$ExpectedSha256
    )
    if (Test-Path $DestPath) {
        if (-not $ExpectedSha256) {
            Write-Host "  $DestPath exists (no hash pin, keeping existing copy)"
            return
        }
        $actual = Get-FileSha256 -Path $DestPath
        if ($actual -eq $ExpectedSha256.ToLower()) {
            Write-Host "  $DestPath exists with matching hash, skipping"
            return
        }
        Write-Host "  $DestPath has mismatched hash, re-downloading"
        Remove-Item $DestPath -Force
    }
    Write-Host "  Downloading $Url -> $DestPath ..."
    Invoke-WebRequest -Uri $Url -OutFile $DestPath -UseBasicParsing
    if ($ExpectedSha256) {
        $actual = Get-FileSha256 -Path $DestPath
        if ($actual -ne $ExpectedSha256.ToLower()) {
            throw "SHA256 mismatch for $DestPath. Expected $ExpectedSha256, got $actual."
        }
    }
}

Write-Host "Fetching Python $PINNED_PYTHON_VERSION embeddable distribution..."
Download-IfNeeded `
    -Url $PINNED_PYTHON_URL `
    -DestPath (Join-Path $ExternalsDir "python-embed.zip") `
    -ExpectedSha256 $PINNED_PYTHON_SHA256

Write-Host "Fetching WebView2 bootstrapper..."
Download-IfNeeded `
    -Url $WEBVIEW2_URL `
    -DestPath (Join-Path $ExternalsDir "MicrosoftEdgeWebview2Setup.exe") `
    -ExpectedSha256 $null

Write-Host ""
Write-Host "External dependencies ready under $ExternalsDir"
