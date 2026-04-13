# qt-platform

Research-first quantitative trading platform for Taiwan index futures.

## Scope

- Historical data ingestion from FinMind
- Session-aware storage and gap scanning
- Event-driven backtesting on 1-minute bars
- CLI-driven workflow and HTML report generation

## Quick Start

1. Copy `config/config.yaml.example` to `config/config.yaml`
2. Copy `config/symbols.csv.example` to `config/symbols.csv`
3. Copy `.env.example` to `.env` and set `FINMIND_TOKEN`
4. If you want live recording through Shioaji, also set `SH_API_KEY` and `SH_SECRET_KEY`
4. Start TimescaleDB
5. Run sync or backtest commands against either `sqlite:///local.db` or `postgresql://...`

```bash
docker compose up -d
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml scan-gaps --symbol MTX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00 --session-scope day_and_night
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml plan-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml sync-registry --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backfill --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --start-date 2024-01-01 --end-date 2024-01-31 --timeframe 1m
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml import-csv-folder --database-url postgresql://postgres:postgres@localhost:5432/trading --folder tmp --pattern '*.csv' --chunk-size 10000
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml preview-option-universe --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live --database-url postgresql://postgres:postgres@localhost:5432/trading --symbols TXFR1 --max-events 10
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live-stub --database-url postgresql://postgres:postgres@localhost:5432/trading --ticks-file tmp/stub_ticks.jsonl --symbols TXO
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml doctor --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --timeframe 1m
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml resolve-contract --symbol MTX --date 2024-01-18
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backtest --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX_MAIN --start 2024-01-03T08:45:00 --end 2024-01-03T13:44:00 --timeframe 1m
```

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

### `plan-sync`
- 用途: 在真正補資料前先估算 request 成本
- 適合情境:
  - 想知道某段歷史資料要花多少 FinMind request
  - 想確認目前是 `bootstrap`、`catch_up` 還是 `repair`
  - 想先看 registry 內哪些 symbol 會被同步
- 會輸出:
  - 總 request 預估
  - 每個 timeframe 的 request 拆分
  - 每個 symbol 的同步模式與缺失日期

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml plan-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
```

### `sync-registry`
- 用途: 依照 `config/symbols.csv` 批次補齊歷史資料
- 適合情境:
  - 初次建庫
  - 新環境匯入舊 DB 後補齊缺的日期
  - 想固定用同一份 registry 管理要追蹤的 universe
- 目前行為:
  - 執行 `bootstrap` / `catch_up`
  - `repair` 預設跳過，除非明確加 `--allow-repair`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml sync-registry --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
```

### `backfill`
- 用途: 手動補某個 symbol 的特定時間範圍
- 適合情境:
  - 臨時補某一段 `MTX 1m`
  - 單獨補某支股票日線
  - 針對 `TXO` 先測一天或幾天的 option chain

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backfill --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --start-date 2024-01-01 --end-date 2024-01-31 --timeframe 1m
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

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml import-csv-folder --database-url postgresql://postgres:postgres@localhost:5432/trading --folder tmp --pattern '*.csv' --chunk-size 10000
```

### `record-live-stub`
- 用途: 用 stub tick 檔驗證 live recorder 路徑
- 適合情境:
  - 還沒接真實券商 websocket 前，先測資料契約
  - 驗證 `raw_ticks -> bars_1m` 聚合是否正確
- 目前行為:
  - 讀一個 JSON Lines 檔
  - 轉成 `CanonicalTick`
  - 落到 `raw_ticks`
  - 同步聚合一批 `bars_1m`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live-stub --database-url postgresql://postgres:postgres@localhost:5432/trading --ticks-file tmp/stub_ticks.jsonl --symbols TXO
```

### `record-live`
- 用途: 透過真實 live provider 將即時 tick 落到 `raw_ticks`，並同步聚合成 `bars_1m`
- 目前支援:
  - `provider=shioaji`
- 適合情境:
  - 開盤中先開始累積自建歷史 tick 資料
  - 驗證 `raw_ticks -> bars_1m` 的真實 live 路徑
- 注意:
  - `--symbols` 可傳 Shioaji 的精確合約代碼，例如 `TXFR1`、`TXO20250418000C`
  - 或改用高階選擇權模式:
    - `--option-root TXO`
    - `--expiry-count 2` 代表最近兩個到期日
    - `--atm-window 20` 代表每個到期日取 ATM 上下各 20 個履約價
  - 需要先安裝 `shioaji`
  - `.env` 需要 `SH_API_KEY` 與 `SH_SECRET_KEY`
  - `TXON` 不是目前 SDK 內可直接訂閱的 contract code；`TXO` 是 option chain 群組，實際訂閱仍會展開為單一合約
  - 目前已加入 `api.usage()` 保護:
    - 每日流量上限預設 `500MB`
    - 使用率達 `99%` 會停止錄製
    - 上限與比例可在 `config/config.yaml` 的 `shioaji` 區塊調整
  - `record-live` 已改成 batch 落庫，適合長時間錄製，不會把所有 ticks 累積在記憶體裡
  - 啟動時只會輸出摘要 log:
    - `connected`
    - `subscribed`
    - 最後的錄製結果或錯誤
    - 不會再逐條輸出 `Subscribe ok`
  - 每次錄製都會產生 `run_id`
    - 寫入 `live_run_metadata`
    - 同步寫入 `minute_force_features_1m.run_id`
    - 後續可用來對齊同一次錄製的 option universe
  - 若加上 `--run-forever`:
    - 非交易時段會等到下一次 session 開始
    - 流量達門檻會等到下一次每日重置時間再自動恢復
    - 每日重置時間預設視為 `Asia/Taipei 00:00 + 60 秒`

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live --database-url postgresql://postgres:postgres@localhost:5432/trading --symbols TXFR1 --max-events 10

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live --database-url postgresql://postgres:postgres@localhost:5432/trading --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1 --max-events 200

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live --database-url postgresql://postgres:postgres@localhost:5432/trading --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1 --batch-size 500

PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml record-live --database-url postgresql://postgres:postgres@localhost:5432/trading --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1 --batch-size 500 --run-forever --session-scope day_and_night
```

### `preview-option-universe`
- 用途: 在真正訂閱前，先預覽 `TXO` 高階 resolver 會展開成哪些單一合約
- 適合情境:
  - 想先看最近兩個到期日 + ATM 視窗到底會訂閱多少口
  - 想避免超過 200 個訂閱上限
  - 想在開錄前先確認 universe 是否合理

```bash
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml preview-option-universe --option-root TXO --expiry-count 2 --atm-window 20 --underlying-future-symbol TXFR1
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
    - `--run-id <record-live 輸出的 run_id>`
- 適合情境:
  - 直接看最近兩個到期日、ATM 附近台指選的力道 proxy
  - 不想手動輸入每個履約價與月份
  - 想精準重現某次 `record-live` 當下實際訂閱的那一批合約

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
- `plan-sync` reads `config/symbols.csv` and estimates request cost before running any actual sync.
- `sync-registry` executes historical sync from `config/symbols.csv`. In the current phase it runs `bootstrap` and `catch_up`, while `repair` is intentionally skipped unless `--allow-repair` is passed.
- `1d` planning assumes FinMind bulk-daily requests can fetch all futures symbols for one date in one request.
- `1m` planning assumes one request per `symbol + date`, and currently checks `trading_day` presence only rather than minute-level completeness.
- `sync-registry` currently supports `TAIFEX futures 1d/1m`, `TWSE stocks 1d`, and `TAIFEX TXO 1d` through FinMind.
- `import-csv-folder` can import broker-exported 1-minute OHLCV CSV files directly into the repository layer.
- The current CSV importer expects columns `Symbol,Date,Time,Open,High,Low,Close,TotalVolume`, while optional `UpTicks/DownTicks` are supported when present.
- Broker CSV import stores optional `UpTicks/DownTicks` into `bars_1m.up_ticks` / `bars_1m.down_ticks`.
- `raw_ticks` is now a first-class table for future live recording. The current stub recorder can already persist canonical ticks and aggregate them into `bars_1m`.
- `TWOTC` is stored as an index-like series with `instrument_key=index:TWOTC`. A bare `instrument_key=index` would be too ambiguous once more indices are imported.
- `config/symbols.csv` now supports `instrument_type`, so futures / options / stocks can coexist in the registry without forcing the current provider to sync unsupported products.
- For Taiwan index options, `TXO` is the only FinMind `TaiwanOptionDaily` id currently kept in the active registry. Other TAIFEX option product codes should be re-added only after provider behavior is verified.
- `TaiwanOptionDaily` should use `v4` single-day windows. The older `v3 + date` path was observed to hang on real requests.
- Option daily storage must key on `instrument_key` instead of bare `symbol`, or one trading day of `TXO` chain data will overwrite itself.
- `TaiwanFuturesTick` requires a Sponsor-capable FinMind account. With a free-level token, `1m` backfill will fail upstream even though the pipeline is implemented.
- Important data structures are documented in `docs/SCHEMA.md`.
- Data-source boundaries and pipeline design are documented in `docs/DATA_PIPELINE.md`.
- Environment bootstrap / backup / restore / resync workflow is documented in `docs/OPERATIONS.md`.
