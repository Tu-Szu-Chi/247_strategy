# Data Pipeline

這份文件描述資料從 vendor source 進到平台內部 storage 的路徑，目標是保持 source 可替換。

## Pipeline Goals

- provider 可替換
- canonical model 穩定
- historical 與 live 分流
- derived table 不直接承載 vendor payload

## Historical Pipeline

### Current v1

`FinMind -> provider adapter -> canonical Bar -> repository -> bars_1d / bars_1m`

說明：
- `1d`
  - 來源是 `TaiwanFuturesDaily`
  - 直接正規化成 `Bar`
- `1m`
  - 來源是 `TaiwanFuturesTick`
  - 先在 provider 內聚成 1 分 K
  - 再寫入 `bars_1m`

### Future direction

應該支援多個 historical source：
- FinMind
- broker historical API
- local archive files

它們都應該實作 `HistoricalBarProvider`，輸出 canonical `Bar`。

## Live Pipeline

### Planned v1.1 direction

`Broker socket -> live provider adapter -> canonical Tick -> raw_ticks`

然後再分兩條：

1. `raw_ticks -> minute bar aggregator -> bars_1m`
2. `raw_ticks -> state aggregator -> quote_state_1m`

### Why no direct snapshot -> bars_1m

即時 snapshot 通常只能代表：
- 某個時點的 market state
- 或每個合約最近一筆狀態

它不等於：
- 這一分鐘內所有成交序列
- 可完整重建 minute OHLCV 的 tick stream

所以 snapshot 不應直接產生 `bars_1m`。

## Canonical Model Layers

### Vendor payload
- vendor-specific
- 例如 FinMind JSON / Shioaji callback object / KGI callback payload

### Provider adapter
- 封裝 vendor SDK 或 HTTP API
- 不讓 vendor 細節外溢

### Normalizer
- 把 vendor payload 映射成 canonical model

### Canonical model
- `Bar`
- `CanonicalTick` (planned)
- `QuoteState1m` (planned)

### Repository / Aggregator
- 只處理 canonical model

## Source Replacement Rule

替換資料源時，理想上只需要新增：
- provider adapter
- normalizer

不應影響：
- strategy
- backtest
- reporting
- sync planning

如果替換 source 時需要大改下游，表示 canonical boundary 設計失敗。

## Registry-Driven Sync

### Input
- `config/symbols.csv`
- `start_date`
- `end_date`
- `timeframes`

### Planner
- `plan-sync`
- 估算：
  - symbol 數
  - 日期數
  - request 數
  - runtime
  - bootstrap / catch_up / repair 模式

### Executor
- `sync-registry` (in progress)
- 初期先支援：
  - historical bootstrap
  - catch-up
- minute-level repair 之後再補

## Current Recommendation

- historical:
  - FinMind
- first live source:
  - Shioaji preferred
- second live source:
  - KGI SUPER PY

原因：
- Shioaji 的 Python 文件、streaming 類型與 callback/binding 說明較成熟
- KGI 保留為第二 provider，不與 schema 綁死
