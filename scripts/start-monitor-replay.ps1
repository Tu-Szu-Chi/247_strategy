param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$UnderlyingFutureSymbol = "MXFR1",
    [string]$ReplayUnderlyingSymbol = "MTX",
    [string]$CallPut = "both",
    [string]$SessionScope = "day_and_night",
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000,
    [double]$SnapshotIntervalSeconds = 10.0,
    [double]$ReadyTimeoutSeconds = 15.0,
    [string]$LogFile = "logs/serve-monitor-replay.log",
    [string]$DatabaseUrl = "",
    [string]$KronosJson = "reports/mtx-probability-bounded-2026-04-30_2026-04-30_LB300.json",
    [switch]$Simulation
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

$LogFullPath = Join-Path $RepoRoot $LogFile
$LogDir = Split-Path -Parent $LogFullPath
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$CliArgs = @(
    "-m", "qt_platform.cli.main",
    "monitor",
    "replay",
    # "--config", $ConfigPath,
    "--start", "2026-04-30T08:45:00",
    "--end", "2026-05-01T00:30:00",
    "--kronos-series-json", $KronosJson,
    "--host", $ListenHost,
    "--port", $Port,
    "--snapshot-interval-seconds", $SnapshotIntervalSeconds,
    "--log-file", $LogFile
)

if ($Simulation) {
    $CliArgs += "--simulation"
}

Write-Host "Starting replay web..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Host: $ListenHost"
Write-Host "Port: $Port"
Write-Host "Research Replay URL: http://$ListenHost`:$Port/research/replay"
Write-Host "Research Live URL: http://$ListenHost`:$Port/research/live"
Write-Host "Legacy URL: http://$ListenHost`:$Port/legacy-option-power"
Write-Host "Log file: $LogFullPath"

& $PythonExe @CliArgs
