param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$UnderlyingFutureSymbol = "MXFR1",
    [string]$ReplayUnderlyingSymbol = "MTX",
    [int]$ExpiryCount = 2,
    [int]$AtmWindow = 20,
    [string]$CallPut = "both",
    [string]$SessionScope = "day_and_night",
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8000,
    [double]$SnapshotIntervalSeconds = 10.0,
    [double]$ReadyTimeoutSeconds = 15.0,
    [string]$LogFile = "logs/serve-monitor-live.log",
    [string]$DatabaseUrl = "",
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
    "live",
    "--registry", $RegistryPath,
    "--expiry-count", $ExpiryCount,
    "--atm-window", $AtmWindow,
    "--underlying-future-symbol", $UnderlyingFutureSymbol,
    "--replay-underlying-symbol", $ReplayUnderlyingSymbol,
    "--call-put", $CallPut,
    "--session-scope", $SessionScope,
    "--host", $ListenHost,
    "--port", $Port,
    "--snapshot-interval-seconds", $SnapshotIntervalSeconds,
    "--ready-timeout-seconds", $ReadyTimeoutSeconds,
    "--log-file", $LogFile
)

if ($Simulation) {
    $CliArgs += "--simulation"
}

if ($DatabaseUrl) {
    $CliArgs = @(
        "-m", "qt_platform.cli.main",
        "monitor",
        "live",
        "--database-url", $DatabaseUrl,
        "--registry", $RegistryPath,
        "--expiry-count", $ExpiryCount,
        "--atm-window", $AtmWindow,
        "--underlying-future-symbol", $UnderlyingFutureSymbol,
        "--replay-underlying-symbol", $ReplayUnderlyingSymbol,
        "--call-put", $CallPut,
        "--session-scope", $SessionScope,
        "--host", $ListenHost,
        "--port", $Port,
        "--snapshot-interval-seconds", $SnapshotIntervalSeconds,
        "--ready-timeout-seconds", $ReadyTimeoutSeconds,
        "--log-file", $LogFile
    )
    if ($Simulation) {
        $CliArgs += "--simulation"
    }
}

Write-Host "Starting monitor live web..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $(Join-Path $RepoRoot $RegistryPath)"
Write-Host "Live underlying future symbol: $UnderlyingFutureSymbol"
Write-Host "Replay underlying symbol: $ReplayUnderlyingSymbol"
Write-Host "Option roots: AUTO nearest $ExpiryCount"
Write-Host "ATM window: $AtmWindow"
Write-Host "Host: $ListenHost"
Write-Host "Port: $Port"
Write-Host "Research Replay URL: http://$ListenHost`:$Port/research/replay"
Write-Host "Research Live URL: http://$ListenHost`:$Port/research/live"
Write-Host "Legacy URL: http://$ListenHost`:$Port/legacy-option-power"
Write-Host "Log file: $LogFullPath"

& $PythonExe @CliArgs
