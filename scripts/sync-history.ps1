param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$StartDate = "2023-01-01",
    [string]$EndDate = "",
    [string]$Timeframes = "1d,1m",
    [string]$SessionScope = "day_and_night",
    [switch]$AllowRepair,
    [string]$DatabaseUrl = "",
    [string]$DailyRunTime = "00:01",
    [int]$PollIntervalSeconds = 30
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot
$env:PYTHONPATH = "src"

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Python virtualenv not found: $PythonExe"
}

$ConfigFullPath = Join-Path $RepoRoot $ConfigPath
if (-not (Test-Path $ConfigFullPath)) {
    throw "Config file not found: $ConfigFullPath"
}

$RegistryFullPath = Join-Path $RepoRoot $RegistryPath
if (-not (Test-Path $RegistryFullPath)) {
    throw "Registry file not found: $RegistryFullPath"
}

if ($PollIntervalSeconds -lt 1) {
    throw "PollIntervalSeconds must be >= 1"
}

try {
    $ParsedStartDate = [datetime]::ParseExact($StartDate, "yyyy-MM-dd", $null)
}
catch {
    throw "StartDate must be in yyyy-MM-dd format: $StartDate"
}

try {
    $ParsedDailyRunTime = [datetime]::ParseExact($DailyRunTime, "HH:mm", $null)
}
catch {
    throw "DailyRunTime must be in HH:mm format: $DailyRunTime"
}

function Invoke-HistorySync {
    param(
        [datetime]$RunStartDate,
        [datetime]$RunEndDate
    )

    if ($RunEndDate -lt $RunStartDate) {
        Write-Host "Skip sync because end date $($RunEndDate.ToString('yyyy-MM-dd')) is earlier than start date $($RunStartDate.ToString('yyyy-MM-dd'))." -ForegroundColor Yellow
        return
    }

    $Args = @(
        "-m", "qt_platform.cli.main",
        "--config", $ConfigPath,
        "sync-registry",
        "--registry", $RegistryPath,
        "--start-date", $RunStartDate.ToString("yyyy-MM-dd"),
        "--end-date", $RunEndDate.ToString("yyyy-MM-dd"),
        "--timeframes", $Timeframes,
        "--session-scope", $SessionScope
    )

    if ($DatabaseUrl) {
        $Args = @(
            "-m", "qt_platform.cli.main",
            "--config", $ConfigPath,
            "sync-registry",
            "--database-url", $DatabaseUrl,
            "--registry", $RegistryPath,
            "--start-date", $RunStartDate.ToString("yyyy-MM-dd"),
            "--end-date", $RunEndDate.ToString("yyyy-MM-dd"),
            "--timeframes", $Timeframes,
            "--session-scope", $SessionScope
        )
    }

    if ($AllowRepair) {
        $Args += "--allow-repair"
    }

    Write-Host "Syncing history..." -ForegroundColor Cyan
    Write-Host "Range: $($RunStartDate.ToString('yyyy-MM-dd')) -> $($RunEndDate.ToString('yyyy-MM-dd'))"
    & $PythonExe @Args
}

function Get-NextScheduledRun {
    param(
        [datetime]$ReferenceTime
    )

    $ScheduledToday = Get-Date -Year $ReferenceTime.Year -Month $ReferenceTime.Month -Day $ReferenceTime.Day -Hour $ParsedDailyRunTime.Hour -Minute $ParsedDailyRunTime.Minute -Second 0
    if ($ReferenceTime -lt $ScheduledToday) {
        return $ScheduledToday
    }
    return $ScheduledToday.AddDays(1)
}

$ContinuousMode = -not $EndDate

Write-Host "History sync script starting..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $RegistryFullPath"
Write-Host "Start date: $($ParsedStartDate.ToString('yyyy-MM-dd'))"
Write-Host "Timeframes: $Timeframes"
Write-Host "Session scope: $SessionScope"
Write-Host "Allow repair: $AllowRepair"
Write-Host "Continuous mode: $ContinuousMode"

if (-not $ContinuousMode) {
    try {
        $ParsedEndDate = [datetime]::ParseExact($EndDate, "yyyy-MM-dd", $null)
    }
    catch {
        throw "EndDate must be in yyyy-MM-dd format: $EndDate"
    }

    Write-Host "End date: $($ParsedEndDate.ToString('yyyy-MM-dd'))"
    Invoke-HistorySync -RunStartDate $ParsedStartDate -RunEndDate $ParsedEndDate
    return
}

Write-Host "Daily run time: $DailyRunTime"
Write-Host "Poll interval seconds: $PollIntervalSeconds"

$InitialEndDate = (Get-Date).Date.AddDays(-1)
Invoke-HistorySync -RunStartDate $ParsedStartDate -RunEndDate $InitialEndDate
$LastSyncedEndDate = $InitialEndDate

while ($true) {
    $Now = Get-Date
    $NextRunAt = Get-NextScheduledRun -ReferenceTime $Now
    Write-Host "Waiting until $($NextRunAt.ToString('yyyy-MM-dd HH:mm:ss')) for next daily sync." -ForegroundColor DarkGray

    while ((Get-Date) -lt $NextRunAt) {
        $RemainingSeconds = ($NextRunAt - (Get-Date)).TotalSeconds
        if ($RemainingSeconds -le 0) {
            break
        }
        Start-Sleep -Seconds ([math]::Min($PollIntervalSeconds, [int][math]::Ceiling($RemainingSeconds)))
    }

    $TargetEndDate = (Get-Date).Date.AddDays(-1)
    $RunStartDate = $LastSyncedEndDate.AddDays(1)
    if ($RunStartDate -lt $ParsedStartDate) {
        $RunStartDate = $ParsedStartDate
    }

    if ($TargetEndDate -lt $RunStartDate) {
        Write-Host "No new completed trading day to sync. Last synced end date: $($LastSyncedEndDate.ToString('yyyy-MM-dd'))" -ForegroundColor Yellow
        continue
    }

    Invoke-HistorySync -RunStartDate $RunStartDate -RunEndDate $TargetEndDate
    $LastSyncedEndDate = $TargetEndDate
}
