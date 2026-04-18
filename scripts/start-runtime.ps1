param(
    [string]$ConfigPath = "config/config.yaml",
    [string]$RegistryPath = "config/symbols.csv",
    [string]$UnderlyingFutureSymbol = "MTXFR1",
    [int]$ExpiryCount = 2,
    [int]$AtmWindow = 20,
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000,
    [string]$WebLogFile = "logs/serve-option-power.log",
    [string]$LiveLogFile = "logs/record-live-registry.log",
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

foreach ($LogFile in @($WebLogFile, $LiveLogFile)) {
    $LogFullPath = Join-Path $RepoRoot $LogFile
    $LogDir = Split-Path -Parent $LogFullPath
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir | Out-Null
    }
}

$TmpDir = Join-Path $RepoRoot "tmp"
if (-not (Test-Path $TmpDir)) {
    New-Item -ItemType Directory -Path $TmpDir | Out-Null
}

$RegistryRows = Import-Csv -Path $RegistryFullPath
$NonOptionRows = @($RegistryRows | Where-Object {
    $instrumentType = ("" + $_.instrument_type).Trim().ToLower()
    $instrumentType -ne "option"
})
$FilteredRegistryPath = Join-Path $TmpDir "live_registry_non_option.csv"
if ($NonOptionRows.Count -gt 0) {
    $NonOptionRows | Export-Csv -Path $FilteredRegistryPath -NoTypeInformation -Encoding UTF8
} else {
    @(
        [pscustomobject]@{
            symbol = "TXFR1"
            market = "TAIFEX"
            instrument_type = "future"
            enabled = "true"
        }
    ) | Export-Csv -Path $FilteredRegistryPath -NoTypeInformation -Encoding UTF8
}

$WebArgs = @(
    "-m", "qt_platform.cli.main",
    "--config", $ConfigPath,
    "serve-option-power",
    "--option-root", "AUTO",
    "--expiry-count", $ExpiryCount,
    "--atm-window", $AtmWindow,
    "--underlying-future-symbol", $UnderlyingFutureSymbol,
    "--host", $Host,
    "--port", $Port,
    "--log-file", $WebLogFile
)
if ($DatabaseUrl) {
    $WebArgs = @("-m", "qt_platform.cli.main", "--config", $ConfigPath, "serve-option-power", "--database-url", $DatabaseUrl, "--option-root", "AUTO", "--expiry-count", $ExpiryCount, "--atm-window", $AtmWindow, "--underlying-future-symbol", $UnderlyingFutureSymbol, "--host", $Host, "--port", $Port, "--log-file", $WebLogFile)
}

$LiveArgs = @(
    "-m", "qt_platform.cli.main",
    "--config", $ConfigPath,
    "record-live-registry",
    "--registry", $FilteredRegistryPath,
    "--expiry-count", $ExpiryCount,
    "--atm-window", $AtmWindow,
    "--underlying-future-symbol", $UnderlyingFutureSymbol,
    "--run-forever",
    "--log-file", $LiveLogFile
)
if ($DatabaseUrl) {
    $LiveArgs = @("-m", "qt_platform.cli.main", "--config", $ConfigPath, "record-live-registry", "--database-url", $DatabaseUrl, "--registry", $FilteredRegistryPath, "--expiry-count", $ExpiryCount, "--atm-window", $AtmWindow, "--underlying-future-symbol", $UnderlyingFutureSymbol, "--run-forever", "--log-file", $LiveLogFile)
}

Write-Host "Starting live runtime..." -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host "Config: $ConfigFullPath"
Write-Host "Registry (all): $RegistryFullPath"
Write-Host "Registry (non-option live): $FilteredRegistryPath"
Write-Host "Option roots: AUTO nearest two"
Write-Host "Underlying future symbol: $UnderlyingFutureSymbol"
Write-Host "Web UI: http://${Host}:$Port/"
Write-Host "Web log: $(Join-Path $RepoRoot $WebLogFile)"
Write-Host "Live log: $(Join-Path $RepoRoot $LiveLogFile)"

$LiveProc = Start-Process `
    -FilePath $PythonExe `
    -ArgumentList $LiveArgs `
    -WorkingDirectory $RepoRoot `
    -PassThru `
    -WindowStyle Normal

try {
    & $PythonExe @WebArgs
}
finally {
    if ($LiveProc -and -not $LiveProc.HasExited) {
        Stop-Process -Id $LiveProc.Id -Force
    }
}
