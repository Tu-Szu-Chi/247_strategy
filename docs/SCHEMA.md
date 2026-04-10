# Schema Notes

這份文件固定平台內部「canonical data model」的語意。  
原則是：上游 data source 可以換，但下游 storage / backtest / strategy 不應該跟著換欄位語意。

## Design Principles

- `historical` 與 `live` 是兩條不同資料路徑
- `source payload` 不直接進策略層
- 平台內部只吃 canonical model
- `bars_1m` 是 derived data，不是 vendor-native raw data
- `source` 可替換，但 canonical schema 盡量不變

## Core Domain

### `Bar`
- 定義位置: `src/qt_platform/domain.py`
- 用途: 平台內部統一的 bar 格式
- 關鍵欄位:
  - `ts`
  - `trading_day`
  - `symbol`
  - `contract_month`
  - `session`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`
  - `open_interest`
  - `source`

### 未來要補的 canonical event

這兩個還沒正式落地，但 schema 與 pipeline 已先定義：

#### `CanonicalTick`
- 用途: 平台內部統一的 raw trade event
- 建議欄位:
  - `ts`
  - `instrument_key`
  - `symbol`
  - `contract_month`
  - `strike_price`
  - `call_put`
  - `price`
  - `size`
  - `tick_type`
  - `total_volume`
  - `source`
  - `payload_json`

#### `QuoteState1m`
- 用途: 盤中策略使用的 minute-level market state
- 建議欄位:
  - `ts`
  - `instrument_key`
  - `symbol`
  - `contract_month`
  - `strike_price`
  - `call_put`
  - `last_price`
  - `last_size`
  - `tick_count`
  - `buy_tick_volume`
  - `sell_tick_volume`
  - `bid_side_total_vol`
  - `ask_side_total_vol`
  - `source`

## Storage

### `instrument_registry`
- 目前實體形式: `config/symbols.csv`
- 未來可升級成 DB table
- 用途:
  - 定義要同步哪些 instrument
  - 隔離 strategy universe 與 vendor symbol
- 建議欄位:
  - `instrument_key`
  - `market`
  - `instrument_type`
  - `symbol`
  - `root_symbol`
  - `enabled`
  - `metadata_json`

目前 `config/symbols.csv` 已實際支援：
- `symbol`
- `market`
- `instrument_type`
- `enabled`

### `bars_1m`
- 用途: 回測主資料
- 來源:
  - 現在: FinMind `tick -> 1m aggregation`
  - 未來: broker live ticks `-> 1m aggregation`
- 原則:
  - 只存 1 分 K 結果，不存 raw tick
  - `1m` 與 `1d` 分表
  - 需保留 `source`
  - 目前已落地 `instrument_key`
  - 目前已落地 `strike_price`
  - 目前已落地 `call_put`
  - 目前已落地 `build_source`
    - 例如 `finmind_tick_agg`
    - `shioaji_tick_agg`
    - `kgi_tick_agg`

### `bars_1d`
- 用途: 日資料研究與 bootstrap
- 原則:
  - 與 `bars_1m` 分開
  - 不允許日資料寫進 `bars_1m`
  - `source` / `build_source` 語意與 `bars_1m` 相同
  - 目前也保留 `instrument_key / strike_price / call_put`

### `raw_ticks`
- 目前尚未落地
- 用途:
  - 接 broker live tick feed
  - 建立自有歷史 tick 庫
  - 作為 `bars_1m` 與 `quote_state_1m` 的上游
- 原則:
  - append-only
  - 保留 vendor payload 方便追查

### `quote_state_1m`
- 目前尚未落地
- 用途:
  - 盤中決策
  - 不進 backtest 主 bar store
- 原則:
  - 與 `bars_1m` 分開
  - 語意是 market state，不是 OHLCV
  - 不應被誤用成歷史回測 bar

### `sync_state`
- 用途: 記錄同步游標
- 主鍵:
  - `source`
  - `symbol`
  - `timeframe`
  - `session_scope`

## Provider Abstraction

## 現在的 provider

### `BaseProvider.fetch_history(...)`
- 輸入:
  - `symbol`
  - `start_date`
  - `end_date`
  - `timeframe`
  - `session_scope`
- 輸出:
  - `list[Bar]`

### `FinMindAdapter`
- `timeframe=1d`: `TaiwanFuturesDaily`
- `timeframe=1m`: `TaiwanFuturesTick` 聚合成 1 分 K
- `1d` 一律寫入 `bars_1d`
- `1m` 一律寫入 `bars_1m`

## 接下來的 provider 方向

平台應拆成至少兩種 provider interface：

### `HistoricalBarProvider`
- 直接產出 canonical `Bar`
- 例如:
  - FinMind futures daily
  - FinMind futures tick aggregated to 1m

### `LiveTickProvider`
- 產出 canonical `CanonicalTick`
- 例如:
  - Shioaji futures/options tick callback
  - KGI SUPER PY tick subscription

重點不是「策略直接換 provider」，而是：
- vendor SDK -> provider adapter -> normalizer -> canonical model

這樣替換 source 時，理論上只需要新增：
- provider adapter
- payload normalizer

下游 storage / aggregation / strategy 不必跟著改 vendor-specific 欄位。

## Session Rules

### Session 分類
- `day`: 08:45 - 13:45
- `night`: 15:00 - 次日 05:00

### `trading_day`
- 日盤 bar: `trading_day = ts.date()`
- 夜盤 15:00-23:59: `trading_day = ts.date()`
- 夜盤 00:00-05:00: `trading_day = 前一個日曆日`

### 為什麼重要
- 夜盤跨自然日，所以不能只靠 calendar date 思考資料與回測
- `scan-gaps` 只會把 session 內應該存在的 bar 視為缺口

## MTX Contract Rule

- v1 先實作 `MTX` 月契約規則，不處理週契約 `MX1/MX2/MX4/MX5`
- 月契約最後交易日以該月份 `第 3 個星期三` 判定
- 若 `trading_day` 已超過當月最後交易日，主月切到次月

### `MTX_MAIN`
- 不是上游 provider symbol
- 讀取時會先查 `MTX`
- 再依每根 bar 的 `trading_day` 選出對應主月 `contract_month`

## Current Scope

- 先把 `history data + backtest` 做穩
- `live` 先只規劃 schema，不急著接 broker socket
- `raw_bidask` 先不做
- 未來 live 路徑以 `raw_ticks -> bars_1m / quote_state_1m` 為主
