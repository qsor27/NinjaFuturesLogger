<#
.SYNOPSIS
  Resolve the app version from git + CI env for the Windows build.
.DESCRIPTION
  Returns a PSCustomObject with:
    Display  — human-readable version, e.g. "v1.2.3" or "v1.2.3-5-gabc1234"
    Numeric  — dotted 4-part numeric for Windows FileVersion field, e.g. "1.2.3.5"
    GitSha   — short git SHA, e.g. "abc1234"
    BuiltAt  — UTC ISO 8601 timestamp

  Resolution order for Display:
    1. GITHUB_REF_NAME when triggered by a tag push (CI authoritative)
    2. git describe --tags --always --dirty (local + CI manual dispatch)
    3. "0.0.0-dev" fallback

  Meant to be dot-sourced by the other build scripts:
    . "$PSScriptRoot\resolve-version.ps1"
    $v = Resolve-Version
    Write-Host $v.Display
#>

function Resolve-Version {
    [CmdletBinding()]
    param()

    # Prefer the CI-supplied tag when the workflow was triggered by a tag push.
    if ($env:GITHUB_REF -like 'refs/tags/*' -and $env:GITHUB_REF_NAME) {
        $display = $env:GITHUB_REF_NAME
    } else {
        $display = (& git describe --tags --always --dirty 2>$null)
        if ([string]::IsNullOrWhiteSpace($display)) { $display = "0.0.0-dev" }
    }

    $sha = (& git rev-parse --short HEAD 2>$null)
    if ([string]::IsNullOrWhiteSpace($sha)) { $sha = "unknown" }

    $builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    # Parse Display into a strict 4-part numeric for Windows FileVersion.
    # Accepted shapes:
    #   v1.2.3               -> 1.2.3.0
    #   1.2.3                -> 1.2.3.0
    #   v1.2.3-5-gabc1234    -> 1.2.3.5   (commits past tag in the 4th slot)
    #   anything else        -> 0.0.0.0
    $numeric = "0.0.0.0"
    if ($display -match '^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+)-g[0-9a-f]+)?') {
        $build = if ($matches[4]) { $matches[4] } else { "0" }
        $numeric = "$($matches[1]).$($matches[2]).$($matches[3]).$build"
    }

    [PSCustomObject]@{
        Display = $display
        Numeric = $numeric
        GitSha  = $sha
        BuiltAt = $builtAt
    }
}
