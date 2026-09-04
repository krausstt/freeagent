<#
.SYNOPSIS
  One-shot setup and proof of concept for Windows.

.DESCRIPTION
  Finds a real Python, installs the one dependency, checks whether your league
  needs cookies before asking for any, stores them locked to your account,
  polls ESPN once and prints your first weekly brief.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1

.NOTES
  Written for Windows PowerShell 5.1, which ships with Windows. No `&&`, no
  ternaries, no null-coalescing - those are PowerShell 7+ and fail on 5.1.
#>

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

function Write-Step($n, $msg) { Write-Host "`n==> [$n/6] $msg" -ForegroundColor Cyan }
function Write-Fail($msg)     { Write-Host $msg -ForegroundColor Red }

# --- 1. Find a real Python -------------------------------------------------
# `python` on a clean Windows install is usually the Microsoft Store alias stub
# under WindowsApps: it is not Python, it just prints an advert. Skip it.
function Find-Python {
    $candidates = @(
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python';  Args = @()     },
        @{ Exe = 'python3'; Args = @()     }
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -like '*\WindowsApps\*') { continue }   # Store alias stub
        try {
            $version = & $c.Exe @($c.Args + '--version') 2>&1
            if ($version -match 'Python (\d+)\.(\d+)') {
                $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                if ($major -eq 3 -and $minor -ge 10) {
                    return @{ Exe = $c.Exe; Args = $c.Args; Version = "$major.$minor" }
                }
            }
        } catch { continue }
    }
    return $null
}

Write-Step 1 'Looking for Python 3.10 or newer'
$py = Find-Python
if (-not $py) {
    Write-Fail 'No usable Python found.'
    Write-Host ''
    Write-Host 'Install it, then re-run this script:' -ForegroundColor Yellow
    Write-Host '    winget install --id Python.Python.3.12 -e'
    Write-Host ''
    Write-Host 'Then CLOSE and REOPEN PowerShell so PATH refreshes.'
    Write-Host 'If `python` prints a Microsoft Store advert, turn off the alias:'
    Write-Host '  Settings > Apps > Advanced app settings > App execution aliases'
    Write-Host '  and switch off both "python.exe" and "python3.exe".'
    exit 1
}
$PY = $py.Exe
$PYARGS = $py.Args
Write-Host "Found Python $($py.Version) via '$PY $($PYARGS -join ' ')'"

# --- 2. Dependencies -------------------------------------------------------
Write-Step 2 'Installing dependencies'
& $PY @($PYARGS + @('-m', 'pip', 'install', '--user', '--quiet', '-r', 'requirements.txt'))
if ($LASTEXITCODE -ne 0) { Write-Fail 'pip install failed.'; exit 1 }
& $PY @($PYARGS + @('-c', 'import requests; print("requests", requests.__version__)'))

# --- 3. Offline proof ------------------------------------------------------
Write-Step 3 'Running the offline test suite (no network, no credentials)'
$failed = $false
foreach ($t in @('tests\test_engine.py', 'tests\test_season.py', 'tests\test_brief.py')) {
    & $PY @($PYARGS + @($t))
    if ($LASTEXITCODE -ne 0) { $failed = $true }
}
if ($failed) { Write-Fail 'Tests failed - stopping before touching ESPN.'; exit 1 }

# --- 4. Does the league even need cookies? ---------------------------------
$LeagueId = $env:ESPN_LEAGUE_ID
if (-not $LeagueId) { $LeagueId = '461530087' }
$Season = $env:ESPN_SEASON
if (-not $Season) { $Season = '2026' }

Write-Step 4 "Checking whether league $LeagueId is readable without cookies"
& $PY @($PYARGS + @('-m', 'ffdraft.cli', '--league-id', $LeagueId, '--season', $Season, 'verify'))
$needCookies = ($LASTEXITCODE -ne 0)

if ($needCookies) {
    Write-Host ''
    Write-Host 'League is private. Two cookies needed from a logged-in espn.com tab:' -ForegroundColor Yellow
    Write-Host '  F12 -> Application -> Cookies -> https://www.espn.com'
    Write-Host '  Copy espn_s2 (long) and SWID (keep the curly braces).'
    Write-Host 'Input is hidden and is not written to your history.' -ForegroundColor DarkGray
    Write-Host ''
    $secureS2 = Read-Host '  espn_s2' -AsSecureString
    $secureSwid = Read-Host '  SWID' -AsSecureString
    $s2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureS2))
    $swid = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSwid))
    if ([string]::IsNullOrWhiteSpace($s2) -or [string]::IsNullOrWhiteSpace($swid)) {
        Write-Fail 'Both values are required.'; exit 1
    }
    & $PY @($PYARGS + @('tools\find_league.py', '--league-id', $LeagueId,
                        '--season', $Season, '--espn-s2', $s2, '--swid', $swid))
    $s2 = $null; $swid = $null
    [GC]::Collect()
} else {
    Write-Host 'League is public - no cookies needed.' -ForegroundColor Green
    & $PY @($PYARGS + @('tools\find_league.py', '--league-id', $LeagueId, '--season', $Season))
}
if ($LASTEXITCODE -ne 0) { Write-Fail 'Could not save the league config.'; exit 1 }

# --- 5 & 6. Poll and brief -------------------------------------------------
Write-Step 5 'Polling ESPN once'
& $PY @($PYARGS + @('tools\poll_espn.py'))
if ($LASTEXITCODE -ne 0) { Write-Fail 'Poll failed - see the message above.'; exit 1 }

Write-Step 6 'Your first weekly brief'
& $PY @($PYARGS + @('tools\weekly_brief.py', '--write'))

Write-Host ''
Write-Host ('-' * 66)
Write-Host 'Done.' -ForegroundColor Green
Write-Host '  data\live\latest.json      the raw snapshot'
Write-Host '  data\live\brief-latest.md  the brief'
Write-Host '  dashboard\index.html       open in a browser'
Write-Host ''
Write-Host 'To run it automatically every 3 hours:'
Write-Host '  powershell -ExecutionPolicy Bypass -File deploy\Register-PollTask.ps1'
Write-Host ('-' * 66)
