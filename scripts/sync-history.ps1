param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$StartDate = "2026-04-14",
    [string]$SyncTime = "00:01",
    [string]$SessionScope = "day_and_night",
    [string]$LogFile = "logs/history-sync.log",
    [string]$DatabaseUrl = "",
    [switch]$RunForever
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

$LogFullPath = Join-Path $RepoRoot $LogFile
$LogDir = Split-Path -Parent $LogFullPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

try {
    [void][datetime]::ParseExact($StartDate, "yyyy-MM-dd", $null)
}
catch {
    throw "StartDate must be in yyyy-MM-dd format: $StartDate"
}

try {
    [void][datetime]::ParseExact($SyncTime, "HH:mm", $null)
}
catch {
    throw "SyncTime must be in HH:mm format: $SyncTime"
}

$Args = @(
    "-m", "qt_platform.cli.main",
    "--config", $ConfigPath,
    "history-sync",
    "--registry", $RegistryPath,
    "--start-date", $StartDate,
    "--sync-time", $SyncTime,
    "--session-scope", $SessionScope,
    "--log-file", $LogFile
)

if ($RunForever) {
    $Args += "--run-forever"
}

if ($DatabaseUrl) {
    $Args = @(
        "-m", "qt_platform.cli.main",
        "--config", $ConfigPath,
        "history-sync",
        "--database-url", $DatabaseUrl,
        "--registry", $RegistryPath,
        "--start-date", $StartDate,
        "--sync-time", $SyncTime,
        "--session-scope", $SessionScope,
        "--log-file", $LogFile
    )
    if ($RunForever) {
        $Args += "--run-forever"
    }
}

Write-Host "Starting history sync..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $RegistryFullPath"
Write-Host "Start date: $StartDate"
Write-Host "Sync time: $SyncTime"
Write-Host "Run forever: $RunForever"
Write-Host "Log file: $LogFullPath"

& $PythonExe @Args
