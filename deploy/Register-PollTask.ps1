<#
.SYNOPSIS
  Register the ESPN poll as a Windows Scheduled Task, every 3 hours.

.DESCRIPTION
  The Windows equivalent of the systemd timer. Runs as you, only when you are
  logged on, and refuses to register until a manual poll actually succeeds -
  so you never end up with a task quietly failing every three hours.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\Register-PollTask.ps1
  powershell -ExecutionPolicy Bypass -File deploy\Register-PollTask.ps1 -Unregister
#>
param(
    [switch]$Unregister,
    [int]$IntervalHours = 3
)

$ErrorActionPreference = 'Stop'
$TaskName = 'FreeAgent ESPN Poll'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    exit 0
}

$cfg = Join-Path $env:USERPROFILE '.ffdraft.json'
if (-not (Test-Path $cfg)) {
    Write-Host "No $cfg found. Run deploy\bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}

# Resolve the same Python the bootstrap found, so the task does not depend on
# whatever happens to be first on PATH when the scheduler fires.
$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd -and $pyCmd.Source -notlike '*\WindowsApps\*') {
    $exe = $pyCmd.Source; $argPrefix = '-3 '
} else {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd -or $pyCmd.Source -like '*\WindowsApps\*') {
        Write-Host 'No usable Python on PATH. Run deploy\bootstrap.ps1 first.' -ForegroundColor Red
        exit 1
    }
    $exe = $pyCmd.Source; $argPrefix = ''
}

Write-Host 'Verifying a poll succeeds before scheduling it...' -ForegroundColor Cyan
Push-Location $Root
& $exe ($argPrefix + 'tools\poll_espn.py').Split(' ')
$ok = ($LASTEXITCODE -eq 0)
Pop-Location
if (-not $ok) {
    Write-Host 'Poll failed. Fix that first; not scheduling a task that would only fail.' -ForegroundColor Red
    exit 1
}

$action = New-ScheduledTaskAction -Execute $exe `
    -Argument ($argPrefix + 'tools\poll_espn.py') -WorkingDirectory $Root

# Repeat indefinitely from the next quarter hour. Windows has no "Persistent="
# equivalent, so StartWhenAvailable catches up a run missed while asleep.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(15) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Polls ESPN Fantasy and writes a league snapshot.' `
    -Force | Out-Null

Write-Host ''
Write-Host "Registered '$TaskName', every $IntervalHours hours." -ForegroundColor Green
Write-Host '  Get-ScheduledTask -TaskName ''FreeAgent ESPN Poll'' | Get-ScheduledTaskInfo'
Write-Host '  Start-ScheduledTask -TaskName ''FreeAgent ESPN Poll''    # run now'
Write-Host '  ...\Register-PollTask.ps1 -Unregister                  # remove'
