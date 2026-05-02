# qt-platform

Research-first quantitative trading platform for Taiwan index futures.

## Scope

- Historical data ingestion from FinMind
- Session-aware storage and gap scanning
- Event-driven backtesting on 1-minute bars
- Two operational programs: `runtime` and `history-sync`

## Quick Start

### 新電腦 / 新環境啟用步驟

先講清楚：

- `config/config.yaml` 目前預設 `database.url = sqlite:///local.db`
- 所以你如果沒有額外帶 `--database-url postgresql://...`，資料會先寫進 `local.db`
- 若你要把 `TimescaleDB` 當正式主庫，建議直接把 `config/config.yaml` 改成 PostgreSQL
- Windows 主機若是你接下來要長時間跑正式流程，應該直接使用 PostgreSQL/TimescaleDB，不要再用 SQLite 當主庫
- `pytest` 現在是 required dependency，基本安裝就會帶進來

1. 安裝 Python 3.10+ 與 Docker Desktop。
2. Clone 專案並切到 repo 根目錄。
3. 建立虛擬環境並啟用。
4. 安裝專案依賴。
5. 複製設定檔模板。
6. 在 `.env` 設定 `FINMIND_TOKEN`。
7. 若要跑 live recording，再補 `SH_API_KEY` 與 `SH_SECRET_KEY`。
8. 若這台是正式主機，把 `config/config.yaml` 的 `database.url` 改成 PostgreSQL。
9. 啟動 TimescaleDB。
10. 先跑 `doctor` 確認 config、DB、schema、token 都正常。
11. 再依用途執行 `history-sync`、`runtime`、`serve-option-power` 或 `backtest`。

### 1. 建立 Python 環境

Windows PowerShell:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[web,live,reports,kronos]
```

macOS / Linux:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .[web,live,reports,kronos]
```

若你只需要核心功能，可改成：

```bash
pip install -e .
```

### 2. 複製設定檔

Windows PowerShell:

```powershell
Copy-Item config/config.yaml.example config/config.yaml
Copy-Item config/symbols.csv.example config/symbols.csv
Copy-Item .env.example .env
```

macOS / Linux:

```bash
cp config/config.yaml.example config/config.yaml
cp config/symbols.csv.example config/symbols.csv
cp .env.example .env
```

接著編輯：

- `.env`
  - 必填：`FINMIND_TOKEN`
  - live 才需要：`SH_API_KEY`、`SH_SECRET_KEY`
- `config/config.yaml`
  - 本機簡單測試可保留 `sqlite:///local.db`
  - 正式環境建議改成 `postgresql://postgres:postgres@localhost:5432/trading`

### 3. 啟動資料庫

```bash
docker compose up -d
```

### 4. 驗證環境

先用 `doctor` 做第一次驗證：

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml doctor --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --timeframe 1m
```

若你暫時只用 SQLite，可拿掉 `--database-url ...`：

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml doctor --symbol MTX --timeframe 1m
```

也可以順手確認測試框架已可用：

```bash
PYTHONPATH=src python -m pytest tests/test_option_power_replay.py -q
```

### 5. 常用啟動指令

```bash
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml scan-gaps --symbol MTX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00 --session-scope day_and_night
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml history-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml history-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --run-forever --sync-time 15:05
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml runtime --database-url postgresql://postgres:postgres@localhost:5432/trading --registry config/symbols.csv
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml runtime --database-url postgresql://postgres:postgres@localhost:5432/trading --registry config/symbols.csv --max-events 200
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml import-csv-folder --database-url postgresql://postgres:postgres@localhost:5432/trading --folder tmp --pattern '*.csv' --chunk-size 10000
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml resolve-contract --symbol MTX --date 2024-01-18
PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml backtest --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX_MAIN --start 2024-01-03T08:45:00 --end 2024-01-03T13:44:00 --timeframe 1m
```

若你要搬到 Windows 主機，請直接看 [OPERATIONS.md](/Users/quentin-tu/Documents/247_strategy/docs/OPERATIONS.md)。那份文件已補：

- SQLite vs TimescaleDB 定位
- Windows PowerShell 安裝步驟
- `runtime` 正式啟動方式
- `history-sync` history 補齊方式
- DB 備份與還原方式

## Frontend Dev

前端 UI 現在改成 `React + Vite + TypeScript`，本地開發建議直接前後端分開跑：

```bash
cd frontend
npm install
npm run dev
```

Vite dev server 預設在 `http://127.0.0.1:5173`，會 proxy `/api/*` 和 `/ws/*` 到本地 `FastAPI`。
若你要讓 `FastAPI` 直接提供 SPA 靜態檔，先執行：

```bash
cd frontend
npm run build
```

build 完成後，`serve-option-power` / `serve-option-power-replay` 的 `/` 與 `/research` 會直接回傳 `frontend/dist`。

現在 `serve-option-power` 也會一併掛上 replay API：

- live data subscribe
- live data record
- `symbols.csv` 內 `stock` 的 live ticks 與 `bars_1m`
- 手動建立 replay session：`POST /api/option-power/replay/sessions`

也就是說，若你的需求是同時看 `Research Live` 與 `Research Replay`，通常只需要啟動一個 `serve-option-power` process。

舊版純 HTML/JS option power 頁面已移除，UI 以 `frontend/` 內的 React app 為唯一入口。

## CLI 指令說明

### `doctor`
- 用途: 檢查目前執行環境是否健康
- 適合情境:
  - 剛換新環境
  - 不確定 DB schema 是否完整
  - 想確認 FinMind token 是否有效
  - 想看某個 symbol/timeframe 目前有多少資料
- 會輸出:
  - `finmind_user_info`
  - `database_connectivity`
  - `schema`
  - `symbol_data`
  - `latest_bar_ts`
  - `sync_cursor`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml doctor --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --timeframe 1m
```

### `history-sync`
- 用途: 完全依照 `symbols.csv` 回補 registry 內標的的 `1d/1m`
- 規則:
  - 預設只補到昨天
  - 逐個檢查 `timeframe + symbol + trading_day`
  - 已存在就 skip，不重抓
  - 每個 `symbol + trading_day` 都會輸出進度 log
- 適合情境:
  - 初次建庫
  - 每日固定時間補前一日
  - 避免與 live `runtime` 重複抓當日資料

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml history-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml history-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --run-forever --sync-time 15:05
```

### `scan-gaps`
- 用途: 掃描指定時間區間內缺了哪些 1 分 K
- 適合情境:
  - 懷疑 DB 資料有殘缺
  - 想先確認缺口，再決定是否做 repair
- 注意:
  - 目前是 session-aware
  - 會避開非交易時段，不會把日夜盤之間的休市區誤判成 gap

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml scan-gaps --symbol MTX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00 --session-scope day_and_night
```

### `backtest`
- 用途: 對已落庫的 `bars_1m` / `bars_1d` 執行回測
- 適合情境:
  - 驗證 `MTX_MAIN` 或單一 symbol 的策略表現
  - 產出 HTML 報表
- 目前內建:
  - `sma-cross`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backtest --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX_MAIN --start 2024-01-03T08:45:00 --end 2024-01-03T13:44:00 --timeframe 1m
```

### `resolve-contract`
- 用途: 解析 `MTX` 在某個交易日對應的主月契約
- 適合情境:
  - 想確認結算日前後主月切換結果
  - 驗證 `MTX_MAIN` 視圖所依賴的月契約規則

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml resolve-contract --symbol MTX --date 2024-01-18
```

### `import-csv-folder`
- 用途: 將券商或外部來源匯出的 `1m OHLCV CSV` 批次匯入 DB
- 適合情境:
  - 你已從券商先下載歷史資料
  - 想把資料直接匯入 TimescaleDB 作為 v1 初始庫
  - 後續持續把整理好的 CSV 丟到資料夾再重複匯入
- 目前格式要求:
  - 必須有 `Symbol,Date,Time,Open,High,Low,Close,TotalVolume`
  - `UpTicks/DownTicks` 目前先忽略
- 備註:
  - 匯入器已支援 chunked upsert，適合大檔
  - `TWOTC` 會存成 `instrument_key=index:TWOTC`
  - `MXF*` 會以 `symbol=MTX` 匯入，並依 `trading_day` 補上月契約 `contract_month`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml import-csv-folder --database-url postgresql://postgres:postgres@localhost:5432/trading --folder tmp --pattern '*.csv' --chunk-size 10000
```

### `runtime`
- 用途: 長時間常駐的 live 錄製程式
- 備註:
  - 目前仍可用，但正式 live 主流程已優先改由 `serve-option-power` 承接
- 固定 universe:
  - `MTX` live tick
  - 最近兩檔台指選擇權 roots 的 live tick
  - `symbols.csv` 內 `stock`
- 行為:
  - 寫入 `raw_ticks`
  - 從 live tick 聚合出 `bars_1m`
  - 保持原本開盤/收盤等待與重啟邏輯
  - 不碰 `1d`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml runtime --database-url postgresql://postgres:postgres@localhost:5432/trading --registry config/symbols.csv

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml runtime --database-url postgresql://postgres:postgres@localhost:5432/trading --registry config/symbols.csv --max-events 200
```

### `option-minute-features`
- 用途: 專門查 live 錄進來的 `TXO bars_1m` 分鐘特徵
- 可用兩種模式:
  - 手動過濾:
    - `--contract-month`
    - `--strike-price`
    - `--call-put`
  - resolver 模式:
    - `--option-root TXO`
    - `--expiry-count 2`
    - `--atm-window 20`
    - `--underlying-future-symbol TXFR1`
  - run 對齊模式:
    - `--run-id <runtime 輸出的 run_id>`
- 適合情境:
  - 直接看最近兩個到期日、ATM 附近台指選的力道 proxy
  - 不想手動輸入每個履約價與月份
  - 想精準重現某次 `runtime` 當下實際訂閱的那一批合約

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml option-minute-features --database-url postgresql://postgres:postgres@localhost:5432/trading --start 2026-04-13T08:45:00 --end 2026-04-13T13:45:00 --contract-month 202604 --call-put call --limit 20

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml option-minute-features --database-url postgresql://postgres:postgres@localhost:5432/trading --start 2026-04-13T08:45:00 --end 2026-04-13T13:45:00 --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1 --call-put both --limit 20

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml option-minute-features --database-url postgresql://postgres:postgres@localhost:5432/trading --start 2026-04-13T08:45:00 --end 2026-04-13T13:45:00 --run-id live-20260413T224434-0bfe0f4b --limit 20
```

### `minute-features`
- 用途: 將某段 `bars_1m` 即時計算成統一口徑的 minute force features
- 適合情境:
  - 驗證 `up_ticks/down_ticks + volume` 的力道 proxy
  - 研究某商品在某段時間內的分鐘級方向強弱
  - 策略開發前先看 feature 長什麼樣
- 目前輸出欄位:
  - `tick_total = up_ticks + down_ticks`
  - `net_tick_count = up_ticks - down_ticks`
  - `tick_bias_ratio = net_tick_count / tick_total`
  - `volume_per_tick = volume / tick_total`
  - `force_score = tick_bias_ratio * volume`
- 注意:
  - 如果 `tick_total == 0`
    - `tick_bias_ratio = 0`
    - `volume_per_tick = null`
    - `force_score = 0`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml minute-features --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol 2330 --start 2025-04-11T09:01:00 --end 2025-04-11T09:10:00 --limit 5
```

## Notes

- V1 目前同時保存 `raw_ticks` 與聚合後的 `bars_1m`。`raw_ticks` 用於 live recorder 與後續可重建的研究資料，`bars_1m` 則是查詢與回測主資料。
- `1m` and `1d` are stored in separate tables (`bars_1m`, `bars_1d`). They are never mixed.
- SQLite remains available for local tests and simple experiments.
- PostgreSQL/TimescaleDB storage is supported through the repository layer.
- FinMind integration uses `urllib` to avoid forcing a runtime HTTP client.
- FinMind minute ingestion is implemented by aggregating `TaiwanFuturesTick` into 1-minute bars.
- The working primary symbol for current examples and smoke tests is `MTX`.
- `MTX_MAIN` is supported as a continuous monthly-contract view for read-side workflows such as backtest and doctor.
- `history-sync` uses `timeframe + symbol + trading_day` existence checks before requesting data.
- `history-sync` only syncs through yesterday, so it does not compete with `runtime` for same-day writes.
- `history-sync` is registry-driven and only covers symbols explicitly present in `config/symbols.csv`.
- `import-csv-folder` can import broker-exported 1-minute OHLCV CSV files directly into the repository layer.
- The current CSV importer expects columns `Symbol,Date,Time,Open,High,Low,Close,TotalVolume`, while optional `UpTicks/DownTicks` are supported when present.
- Broker CSV import stores optional `UpTicks/DownTicks` into `bars_1m.up_ticks` / `bars_1m.down_ticks`.
- `raw_ticks` is now a first-class table for future live recording. The current stub recorder can already persist canonical ticks and aggregate them into `bars_1m`.
- `TWOTC` is stored as an index-like series with `instrument_key=index:TWOTC`. A bare `instrument_key=index` would be too ambiguous once more indices are imported.
- `config/symbols.csv` is now used operationally for registry stocks in `serve-option-power`, `runtime`, and `history-sync`.
- `TaiwanFuturesTick` requires a Sponsor-capable FinMind account. With a free-level token, `1m` backfill will fail upstream even though the pipeline is implemented.
- Important data structures are documented in `docs/SCHEMA.md`.
- Data-source boundaries and pipeline design are documented in `docs/DATA_PIPELINE.md`.
- Environment bootstrap / backup / restore / resync workflow is documented in `docs/OPERATIONS.md`.
