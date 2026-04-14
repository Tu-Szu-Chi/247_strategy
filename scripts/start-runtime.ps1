param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$HistoryStartDate = "2023-01-01",
    [string]$UnderlyingFutureSymbol = "TXFR1",
    [int]$ExpiryCount = 2,
    [int]$AtmWindow = 20,
    [string]$LogFile = "logs/run-runtime.log"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

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

Write-Host "Starting runtime..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $RegistryFullPath"
Write-Host "History start date: $HistoryStartDate"
Write-Host "Timeframes: 1m only"
Write-Host "Option universe: TXO recent $ExpiryCount expiries, ATM +/- $AtmWindow"
Write-Host "Underlying future symbol: $UnderlyingFutureSymbol"
Write-Host "Log file: $LogFullPath"

& $PythonExe -m qt_platform.cli.main `
  --config $ConfigPath `
  run-runtime `
  --registry $RegistryPath `
  --history-start-date $HistoryStartDate `
  --timeframes 1m `
  --run-forever `
  --expiry-count $ExpiryCount `
  --atm-window $AtmWindow `
  --underlying-future-symbol $UnderlyingFutureSymbol `
  --log-file $LogFile
