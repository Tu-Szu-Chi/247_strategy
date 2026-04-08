# Schema Notes

這份文件是給你快速掌握系統核心資料結構用的。  
平常先看這份，真的要改行為或 debug 再回去看 code。

## Core Domain

### `Bar`
- 定義位置: `src/qt_platform/domain.py`
- 用途: 平台內部統一的市場資料格式
- 欄位:
  - `ts`
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

### `Signal`
- 用途: 策略輸出的交易意圖
- 關鍵欄位:
  - `ts`
  - `side`
  - `size`
  - `reason`

### `Fill`
- 用途: 回測引擎撮合後的成交
- V1 規則:
  - signal 在當前 bar close 產生
  - fill 在下一根 bar open 成交

### `Trade`
- 用途: 完整開平倉紀錄

## Storage

### `bars_1m`
- 位置: SQLite schema 與 TimescaleDB DDL
- 主鍵:
  - `ts`
  - `symbol`
  - `contract_month`
  - `session`
- 設計重點:
  - `symbol` 與 `contract_month` 分開存
  - `session` 明確保留 `day/night`
  - `source` 保留來源可追溯性
  - `v1 canonical intraday store` 是這張表，raw tick 不落庫

### `bars_1d`
- 用途: 日資料獨立儲存
- 原則:
  - 與 `bars_1m` 分開
  - 禁止把日資料寫進 `bars_1m`

### `sync_state`
- 用途: 記錄同步游標
- 主鍵:
  - `source`
  - `symbol`
  - `timeframe`
  - `session_scope`

## Provider Contract

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
- 即使 `1m` 由 tick 聚合而來，最終也只寫入 `bars_1m`
- `1d` 一律寫入 `bars_1d`
- 實際限制: `TaiwanFuturesTick` 需要 FinMind Sponsor 等級，free token 無法抓取

## Session Rules

### Session 分類
- `day`: 08:45 - 13:45
- `night`: 15:00 - 次日 05:00

### 為什麼重要
- 夜盤跨自然日，所以不能只靠 calendar date 思考資料與回測
- `ts` 是 bar 時間，不等於交易日概念

## 結論

你不需要只靠看 code。  
`SCHEMA.md` 值得保留，因為它把真正要記住的語意固定下來，之後加 provider、換 storage、補 execution 時比較不容易把欄位語意搞混。
