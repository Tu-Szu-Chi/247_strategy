# Operations

這份文件只保留目前可直接執行的操作流程，避免混入已刪除或已改名的舊 CLI。

## Scope

- Python 3.10+
- Windows 11 以 `PowerShell` 為主
- Ubuntu / Linux 以 `.sh` scripts 為主
- 正式 DB 建議使用 PostgreSQL / TimescaleDB

## 1. Bootstrap

### Windows

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .[web,live,reports,kronos]
Copy-Item config\config.yaml.example config\config.yaml
Copy-Item config\symbols.csv.example config\symbols.csv
Copy-Item .env.example .env
docker compose up -d
```

### Ubuntu / Linux

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .[web,live,reports,kronos]
cp config/config.yaml.example config/config.yaml
cp config/symbols.csv.example config/symbols.csv
cp .env.example .env
docker compose up -d
```

`.env` 至少要設定：

```bash
FINMIND_TOKEN=your_token
```

若要跑 live，也要補：

```bash
SH_API_KEY=your_key
SH_SECRET_KEY=your_secret
```

正式主機建議把 `config/config.yaml` 設成：

```yaml
database:
  url: "postgresql://postgres:postgres@localhost:5432/trading"
```

## 2. First Checks

### Windows

```powershell
.\.venv\Scripts\python.exe -m qt_platform.cli.main --config config/config.yaml data doctor --symbol MTX --timeframe 1m
```

### Ubuntu / Linux

```bash
.venv/bin/python -m qt_platform.cli.main --config config/config.yaml data doctor --symbol MTX --timeframe 1m
```

可再跑一次 focused test：

```bash
PYTHONPATH=src python -m pytest tests/test_option_power_replay.py -q
```

## 3. Historical Sync

目前對應 CLI 是 `data sync`，不是舊的 `history-sync`。

### Windows

```powershell
.\scripts\sync-history.ps1 -StartDate 2024-01-01
```

### Ubuntu / Linux

```bash
./scripts/sync-history.sh --start-date 2024-01-01
```

等價 CLI：

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml data sync --start-date 2024-01-01
```

## 4. Gap Scan

目前對應 CLI 是 `data gaps`，不是舊的 `scan-gaps`。

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml data gaps --symbol MTX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00 --session-scope day_and_night
```

## 5. CSV Import

目前對應 CLI 是 `data import`，不是舊的 `import-csv-folder`。

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml data import --folder tmp --pattern '*.csv'
```

## 6. Live Monitor / Research UI

目前對應 CLI 是 `monitor live`，不是舊的 `serve-option-power`。

### Windows

```powershell
.\scripts\start-monitor-live.ps1
```

### Ubuntu / Linux

```bash
./scripts/start-option-power.sh
```

這會提供：

- live monitor
- replay API
- research live UI
- research replay UI

預設入口：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/research/live`
- `http://127.0.0.1:8000/research/replay`

## 7. Replay UI

### Windows

```powershell
.\scripts\start-monitor-replay.ps1
```

### Ubuntu / Linux

```bash
./scripts/start-monitor-replay.sh
```

等價 CLI：

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml monitor replay --start 2026-04-30T08:45:00 --end 2026-05-01T00:30:00
```

## 8. Backtest

目前對應 CLI 是 `backtest run`，不是舊的單層 `backtest ...`。

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml backtest run --symbol MTX_MAIN --start 2024-01-03T08:45:00 --end 2024-01-03T13:44:00 --timeframe 1m
```

## 9. Kronos Probability Build

### Windows

```powershell
.\scripts\kronos-build.ps1
```

### Ubuntu / Linux

```bash
./scripts/kronos-build.sh
```

等價 CLI：

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml kronos probability --symbol MTX --start 2026-04-30T08:45:00 --end 2026-05-01T00:30:00 --target 10m:50 --output reports/mtx-probability.json
```

## 10. Notes

- 若文件與 CLI/help 不一致，以 `src/qt_platform/cli/*.py` 為準。
- 若文件與 code path 不一致，以 `src/qt_platform/*` 為準。
- 若是研究性長文，先看 `docs/README.md` 判斷它是不是 historical note。
