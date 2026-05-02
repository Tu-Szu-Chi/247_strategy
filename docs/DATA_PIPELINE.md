# Data Pipeline

這份文件描述目前 codebase 內已落地的資料路徑，只寫現在真的存在的邊界。

## Goals

- provider 可替換
- canonical model 穩定
- historical 與 live 分流
- downstream 不直接依賴 vendor payload

## Historical

目前 historical pipeline 是：

`FinMind -> provider adapter -> canonical Bar -> repository -> bars_1d / bars_1m`

說明：

- `1d`
  - 來源是 FinMind daily futures data
  - 正規化成 canonical `Bar`
- `1m`
  - 來源是 FinMind futures tick data
  - 先聚合成 `Bar`
  - 再寫入 `bars_1m`

目前對外 CLI 是：

- `data sync`
- `data gaps`
- `data import`
- `data doctor`

## Live

目前 live pipeline 是：

`Broker socket -> live provider adapter -> CanonicalTick -> raw_ticks -> 1m aggregation -> bars_1m`

另外 monitor/live 會並行維護研究用 state：

- option pressure state
- MTX market-state snapshot
- replay/live indicator series
- optional Kronos probability metrics

重要原則：

- snapshot 不直接等於 minute OHLCV
- `bars_1m` 來自 canonical ticks 的聚合
- monitor snapshot 是 research / UI state，不是歷史主儲存格式

## Canonical Layers

### Vendor payload

- vendor-specific callback / JSON

### Provider adapter

- 封裝 vendor SDK / HTTP API
- 把 vendor 細節隔離在 provider 內

### Canonical model

- `Bar`
- `CanonicalTick`

### Repository / Aggregator

- repository 處理 storage
- aggregator 處理 replay/live snapshot materialization

## Replacement Rule

替換資料源時，理想上只需要改：

- provider adapter
- payload normalizer

不應大改：

- storage schema
- strategy
- backtest
- reporting
- replay/live API contract

## Session / Trading-Day Boundary

共用交易時段邏輯現在在：

- `src/qt_platform/trading_calendar.py`

MTX market-state adapter 現在在：

- `src/qt_platform/market_state/mtx.py`

這兩個都是基礎邊界，不應再把相同規則散落到 provider、storage、monitor 各處。
