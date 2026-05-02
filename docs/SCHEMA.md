# Schema Notes

這份文件固定目前平台內部 canonical model 與主要 storage table 的語意。

## Core Domain

### `Bar`

定義位置：

- `src/qt_platform/domain.py`

主要欄位：

- `ts`
- `trading_day`
- `symbol`
- `instrument_key`
- `contract_month`
- `session`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `open_interest`
- `source`
- `build_source`
- `strike_price`
- `call_put`

### `CanonicalTick`

定義位置：

- `src/qt_platform/domain.py`

主要欄位：

- `ts`
- `trading_day`
- `symbol`
- `instrument_key`
- `contract_month`
- `strike_price`
- `call_put`
- `session`
- `price`
- `size`
- `tick_direction`
- `total_volume`
- `bid_side_total_vol`
- `ask_side_total_vol`
- `source`
- `payload_json`

## Storage Tables

### `bars_1m`

用途：

- 回測主資料
- historical query
- replay chart bars

來源：

- FinMind tick aggregation
- broker-exported 1m CSV import
- live canonical tick aggregation

### `bars_1d`

用途：

- 日資料研究
- bootstrap / higher timeframe reference

### `raw_ticks`

用途：

- live tick archive
- replay / monitor rebuild source
- `bars_1m` aggregation upstream

原則：

- append-only
- 保留 canonical 欄位
- 可保留 vendor payload 方便追查

### `sync_state`

用途：

- historical sync cursor / progress state

## Session Rules

共用交易時段規則在：

- `src/qt_platform/trading_calendar.py`

目前 session 分類：

- `day`: `08:45 - 13:45`
- `night`: `15:00 - 次日 05:00`

`trading_day` 規則：

- 日盤：`trading_day = ts.date()`
- 夜盤 `15:00-23:59`：`trading_day = ts.date()`
- 夜盤 `00:00-05:00`：`trading_day = 前一個日曆日`

## MTX / Market-State

MTX market-state adapter 在：

- `src/qt_platform/market_state/mtx.py`

這是 research / monitor / replay 使用的 market-state layer。  
對外 snapshot 仍保留 `regime` 欄位相容，但內部不應再新增新的 root-level `regime.py` 類型邊界。
