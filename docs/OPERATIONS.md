# Operations

這份文件回答四個實務問題：

1. 如何備份資料庫
2. 如何在新環境安裝 Python 依賴
3. 如何把舊資料導入新 DB
4. 如何用一個指令補全指定時間範圍的歷史資料

## 0. 先講清楚 DB 定位

目前專案同時支援 `SQLite` 與 `PostgreSQL/TimescaleDB`，兩者定位不同：

- `SQLite`
  - 預設值目前是 `config/config.yaml -> database.url = sqlite:///local.db`
  - 適合本機 smoke test、單次回測、小規模驗證
  - 很多我先前的快速測試，若沒有顯式帶 `--database-url postgresql://...`，就會落到這裡
- `PostgreSQL/TimescaleDB`
  - 適合正式長期資料庫
  - 適合你接下來在 Windows 主機做的歷史補齊與長時間 `record-live`
  - 你要把它視為正式主庫

這代表：

- 如果你在 `doctor`、`sync-registry`、`run-runtime` 沒明確帶 `--database-url`，而 `config/config.yaml` 仍是 `sqlite:///local.db`，資料就會寫進 SQLite，不會進 TimescaleDB
- 目前你看到「TimescaleDB 沒資料」的主因，大概率不是同步失敗，而是指令其實打到 `local.db`

正式機器建議直接把 `config/config.yaml` 改成：

```yaml
database:
  url: "postgresql://postgres:postgres@localhost:5432/trading"
```

這樣之後大部分命令就不用每次手動加 `--database-url`

## 1. 資料庫備份

## SQLite

### 備份
```bash
cp local.db backup/local-$(date +%Y%m%d-%H%M%S).db
```

### 還原
```bash
cp backup/local-20260410-210000.db local.db
```

SQLite 適合：
- 本機開發
- 快速 smoke test
- 小型單機研究環境

## PostgreSQL / TimescaleDB

### 邏輯備份
```bash
pg_dump postgresql://postgres:postgres@localhost:5432/trading > backup/trading-$(date +%Y%m%d-%H%M%S).sql
```

### 還原
```bash
psql postgresql://postgres:postgres@localhost:5432/trading < backup/trading-20260410-210000.sql
```

### 只備份重要表
```bash
pg_dump \
  --table=bars_1m \
  --table=bars_1d \
  --table=sync_state \
  postgresql://postgres:postgres@localhost:5432/trading > backup/trading-core.sql
```

PostgreSQL / TimescaleDB 適合：
- 長期研究環境
- 較大量歷史資料
- 後續接 live data

## 2. 新環境 Python 依賴安裝

### 最小步驟
```bash
python3.10 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
```

### 設定檔
```bash
cp config/config.yaml.example config/config.yaml
cp config/symbols.csv.example config/symbols.csv
cp .env.example .env
```

然後在 `.env` 設定：
```bash
FINMIND_TOKEN=your_token
```

### 啟動 TimescaleDB
```bash
docker compose up -d
```

## 2A. Windows 主機建議流程

如果你要把 Windows 當正式 live 主機，建議：

1. 安裝 `Python 3.10+`
2. 安裝 `Docker Desktop`
3. 專案根目錄建立 `.venv`
4. 啟動 `TimescaleDB`
5. 把 `config/config.yaml` 的 `database.url` 改成 PostgreSQL
6. 用 `doctor` 確認
7. 再跑 `run-runtime`

### PowerShell 安裝範例
```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item config\config.yaml.example config\config.yaml
Copy-Item config\symbols.csv.example config\symbols.csv
Copy-Item .env.example .env
docker compose up -d
```

### Windows 下建議的 `config/config.yaml`
```yaml
app:
  timezone: "Asia/Taipei"
  session_mode: "day_and_night"

database:
  url: "postgresql://postgres:postgres@localhost:5432/trading"
```

### Windows 下檢查指令
```powershell
.\.venv\Scripts\python.exe -m qt_platform.cli.main --config config/config.yaml doctor --symbol 2330 --timeframe 1m
```

## 3. 舊資料導入新 DB

## 情境 A: 舊環境也是 SQLite

直接複製 `.db` 檔即可：
```bash
cp /path/from/old/local.db ./local.db
```

## 情境 B: 舊環境是 PostgreSQL / TimescaleDB

先在舊環境匯出：
```bash
pg_dump postgresql://postgres:postgres@old-host:5432/trading > trading.sql
```

再在新環境匯入：
```bash
psql postgresql://postgres:postgres@localhost:5432/trading < trading.sql
```

## 情境 C: 舊環境 SQLite -> 新環境 PostgreSQL

目前專案還沒有做正式 migration command。  
短期建議：

1. 保留舊 SQLite 作 archive
2. 在新 PostgreSQL 環境重新跑 `sync-registry`

理由：
- schema 正在演進
- 重新同步通常比寫一次性資料轉換器更穩

如果後續需要，我們可以再補：
- `import-sqlite-to-postgres`

## 4. 一個指令補全指定時間範圍歷史資料

核心指令：
```bash
.venv/bin/python -m qt_platform.cli.main \
  --config config/config.yaml \
  sync-registry \
  --database-url postgresql://postgres:postgres@localhost:5432/trading \
  --start-date 2023-01-01 \
  --end-date 2026-04-10
```

這個指令會：
- 讀 `config/symbols.csv`
- 先規劃 sync
- 再執行 historical bootstrap / catch-up

目前行為：
- `bootstrap`：會執行
- `catch_up`：會執行
- `repair`：預設跳過

如果之後你明確要讓 repair 也跑：
```bash
.venv/bin/python -m qt_platform.cli.main \
  --config config/config.yaml \
  sync-registry \
  --database-url postgresql://postgres:postgres@localhost:5432/trading \
  --start-date 2023-01-01 \
  --end-date 2026-04-10 \
  --allow-repair
```

但目前不建議預設打開，因為 minute-level repair semantics 還沒完全定稿。

## 4A. Windows 下一個指令補歷史 + 進 live

如果 Windows 主機是正式主機，建議直接用：

```powershell
.\.venv\Scripts\python.exe -m qt_platform.cli.main `
  --config config/config.yaml `
  run-runtime `
  --registry config/symbols.csv `
  --history-start-date 2023-01-01 `
  --timeframes 1m `
  --run-forever `
  --expiry-count 2 `
  --atm-window 20
```

這個指令會：

1. 用一個主 CLI 同時開兩條 thread
2. thread A: 回補今天之前的歷史資料
   - 目前建議只補 `1m`
   - 這樣可節省 request，不補 `future 1d` 與 `option 1d`
3. thread B: 立即開始 live 錄製
   - `symbols.csv` 內的股票
   - `MTX/MXF` 對應近月 live 合約
   - `TXO` 最近兩個到期日、ATM `±20`

注意：

- `TXO 1m` 歷史目前仍不由 FinMind 自動補，這部分目前是 live recorder 自建資料
- `TWSE stock 1m` 歷史現在已支援 `FinMind TaiwanStockPriceTick -> bars_1m`
- `run-runtime` 若不帶 `--database-url`，會採用 `config/config.yaml` 裡的 `database.url`

### Windows 一鍵啟動腳本

專案已提供：

```powershell
.\scripts\start-runtime.ps1
```

預設行為：

- 使用 `config/config.yaml`
- 使用 `config/symbols.csv`
- `history-start-date = 2023-01-01`
- 只補 `1m`
- `run-forever`
- `TXO` 最近兩個到期日、`ATM ±20`

若要改起始日期：

```powershell
.\scripts\start-runtime.ps1 -HistoryStartDate 2024-01-01
```

## Recommended Migration Workflow

新環境最穩的啟用流程：

1. 安裝 Python 與依賴
2. 準備 `.env`, `config.yaml`, `symbols.csv`
3. 啟動 PostgreSQL / TimescaleDB
4. 如果有舊 DB，先還原備份
5. 跑 `doctor`
6. 跑 `sync-registry` 補齊指定時間範圍

### 檢查指令
```bash
.venv/bin/python -m qt_platform.cli.main --config config/config.yaml doctor --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --timeframe 1m
```

## 補充：目前哪些資料真的可自動補

- `TAIFEX future 1d`
  - 可補
- `TAIFEX future 1m`
  - 可補
- `TWSE stock 1d`
  - 可補
- `TWSE stock 1m`
  - 可補，走 `FinMind TaiwanStockPriceTick -> bars_1m`
- `TAIFEX option 1d`
  - 可補，根 symbol 以 `TXO` 為 root，實際區分靠 `contract_date`
- `TAIFEX option 1m`
  - 目前不走 FinMind historical 自動補
  - 目前策略是靠 live recorder 自建
