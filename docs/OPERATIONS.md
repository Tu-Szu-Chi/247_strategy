# Operations

這份文件回答四個實務問題：

1. 如何備份資料庫
2. 如何在新環境安裝 Python 依賴
3. 如何把舊資料導入新 DB
4. 如何用一個指令補全指定時間範圍的歷史資料

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
