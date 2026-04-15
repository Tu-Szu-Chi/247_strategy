param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$StartDate = "2023-01-01",
    [string]$EndDate = "",
    [string]$Timeframes = "1d,1m",
    [string]$SessionScope = "day_and_night",
    [switch]$AllowRepair,
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

if (-not $EndDate) {
    $EndDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
}

$Args = @(
    "-m", "qt_platform.cli.main",
    "--config", $ConfigPath,
    "sync-registry",
    "--registry", $RegistryPath,
    "--start-date", $StartDate,
    "--end-date", $EndDate,
    "--timeframes", $Timeframes,
    "--session-scope", $SessionScope
)

if ($DatabaseUrl) {
    $Args = @("-m", "qt_platform.cli.main", "--config", $ConfigPath, "sync-registry", "--database-url", $DatabaseUrl, "--registry", $RegistryPath, "--start-date", $StartDate, "--end-date", $EndDate, "--timeframes", $Timeframes, "--session-scope", $SessionScope)
}

if ($AllowRepair) {
    $Args += "--allow-repair"
}

Write-Host "Syncing history..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry: $RegistryFullPath"
Write-Host "Start date: $StartDate"
Write-Host "End date: $EndDate"
Write-Host "Timeframes: $Timeframes"
Write-Host "Session scope: $SessionScope"
Write-Host "Allow repair: $AllowRepair"

& $PythonExe @Args
