 # 設定環境變數與路徑
     $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
     $RepoRoot = if ($ScriptDir) { Split-Path -Parent $ScriptDir } else { Get-Location }
     Set-Location $RepoRoot
     $env:PYTHONPATH = "src"
    
     # 尋找虛擬環境的 Python，若無則使用系統的 py
     $PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
     if (-not (Test-Path $PythonExe)) {
        $PythonExe = "py"
    }
   
    # 準備參數陣列
    $CliArgs = @(
        "-m", "qt_platform.cli.main",
        "--config", "config/config.yaml",
        "build-mtx-probability-series",
        "--symbol", "MTX",
        "--start", "2026-04-30T08:45:00",
        "--end", "2026-05-01T00:30:00",
        "--history-start", "2026-04-14T08:45:00",
        "--output", "reports/mtx-probability-bounded-2026-04-30_2026-04-30_LB300_small.json"
    )
   
    # 執行
    Write-Host "Executing build-mtx-probability-series..." -ForegroundColor Cyan
    & $PythonExe @CliArgs
