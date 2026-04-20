param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$UnderlyingFutureSymbol = "MXFR1",
    [int]$ExpiryCount = 2,
    [int]$AtmWindow = 20,
    [string]$CallPut = "both",
    [string]$SessionScope = "day_and_night",
    [string]$LogFile = "logs/runtime.log",
    [string]$DatabaseUrl = ""
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

$Args = @(
    "-m", "qt_platform.cli.main",
    "--config", $ConfigPath,
    "runtime",
    "--registry", $RegistryPath,
    "--expiry-count", $ExpiryCount,
    "--atm-window", $AtmWindow,
    "--underlying-future-symbol", $UnderlyingFutureSymbol,
    "--call-put", $CallPut,
    "--session-scope", $SessionScope,
    "--log-file", $LogFile
)

if ($DatabaseUrl) {
    $Args = @(
        "-m", "qt_platform.cli.main",
        "--config", $ConfigPath,
        "runtime",
        "--database-url", $DatabaseUrl,
        "--registry", $RegistryPath,
        "--expiry-count", $ExpiryCount,
        "--atm-window", $AtmWindow,
        "--underlying-future-symbol", $UnderlyingFutureSymbol,
        "--call-put", $CallPut,
        "--session-scope", $SessionScope,
        "--log-file", $LogFile
    )
}

Write-Host "Starting runtime..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $RegistryFullPath"
Write-Host "Underlying future symbol: $UnderlyingFutureSymbol"
Write-Host "Option roots: AUTO nearest $ExpiryCount"
Write-Host "ATM window: $AtmWindow"
Write-Host "Log file: $LogFullPath"

& $PythonExe @Args
