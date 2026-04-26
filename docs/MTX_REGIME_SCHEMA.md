# MTX Regime Schema

這份文件定義第一版 `MTX regime features` 的資料契約。

重點：

- 這是 schema，不等於一定要落 DB
- 目前先用於 replay / research 畫面
- 後端先保證欄位名稱與計算語意穩定
- 之後若要改成落表或做回放比較，直接沿用這份 schema

## 設計原則

第一版只做「可解讀」的盤勢特徵，不做黑盒預測。

所以欄位分成兩層：

1. 原始特徵
2. 綜合分數

原始特徵負責描述市場狀態，綜合分數則負責讓你盤中快速閱讀。

## Snapshot 粒度

- 每個 replay / live snapshot 都可以附帶一份 `regime` payload
- payload 表示「在這個時間點，依照當下已知資料計算出的盤勢狀態」
- 日盤與夜盤各自獨立，不跨 session 累積

## Fields

### generated_at

- type: `datetime`
- 說明：這份 regime snapshot 對應的時間點

### session

- type: `string`
- 值域：`day` / `night` / `unknown`
- 說明：盤別

### close

- type: `float | null`
- 說明：最新可用的 MTX 1 分 K 收盤價

### session_vwap

- type: `float | null`
- 說明：本盤到目前為止的 VWAP

### vwap_distance_bps

- type: `float`
- 說明：`(close - session_vwap) / session_vwap * 10000`
- 解讀：
  - 絕對值大：價格明顯偏離本盤平均成本
  - 接近 0：價格持續回到中軸附近

### directional_efficiency_15m

- type: `float`
- 範圍：理論上 `0 ~ 1`
- 說明：最近 15 分鐘淨位移除以同區間總 range
- 解讀：
  - 高：偏趨勢
  - 低：偏盤整或來回洗

### vwap_cross_count_15m

- type: `int`
- 說明：最近 15 分鐘 close 上下穿越 VWAP 的次數
- 解讀：
  - 高：偏糾結、偏盤整
  - 低：偏單邊

### tick_imbalance_5m

- type: `float`
- 範圍：理論上 `-1 ~ +1`
- 說明：最近 5 分鐘 `up_ticks` / `down_ticks` 方向不平衡
- 解讀：
  - 越接近 `+1`：多方主動較明顯
  - 越接近 `-1`：空方主動較明顯
  - 接近 `0`：偏拉扯

### trade_intensity_5m

- type: `int`
- 說明：最近 5 分鐘成交 tick 筆數
- 解讀：看市場是否活化

### trade_intensity_ratio_30m

- type: `float`
- 說明：最近 5 分鐘 tick 筆數，相對於最近 30 分鐘基準密度的比值
- 解讀：
  - `> 1`：近期節奏加速
  - `< 1`：近期節奏偏慢

### range_ratio_5m_30m

- type: `float`
- 範圍：理論上 `0 ~ 1`
- 說明：最近 5 分鐘 range 占最近 30 分鐘總 range 的比例
- 解讀：
  - 高：短時間波動擴張
  - 低：仍在較小區間內震盪

## Composite Scores

以下三個欄位是研究用的 product signal，不宣稱是通用金融工程標準。

### trend_score

- type: `int`
- 範圍：`0 ~ 100`
- 來源：
  - directional efficiency
  - VWAP 偏離
  - VWAP 穿越次數
  - tick imbalance
  - trade intensity ratio
  - range ratio
- 解讀：
  - 越高越像可延續的趨勢盤

### chop_score

- type: `int`
- 範圍：`0 ~ 100`
- 來源：
  - 低 directional efficiency
  - 高 VWAP 穿越次數
  - 低 VWAP 偏離
  - 低 tick imbalance
  - 低 range ratio
- 解讀：
  - 越高越像盤整或難做盤

### reversal_risk

- type: `int`
- 範圍：`0 ~ 100`
- 來源：
  - 15m 方向與 5m 方向是否衝突
  - 15m 方向與 5m tick flow 是否衝突
  - 價格相對 VWAP 方向與短線 flow 是否衝突
- 解讀：
  - 越高越要小心原趨勢可能在鈍化或反手

### regime_label

- type: `string`
- 值域：
  - `trend`
  - `chop`
  - `reversal_risk`
  - `transition`
  - `no_data`
- 說明：第一版粗分類標籤

## 第一版定位

這份 schema 的用途是：

- 讓 replay 頁面可以直接觀察特徵效果
- 讓我們之後比較不同公式時有固定欄位口徑
- 先驗證哪些欄位真的對你的判盤有幫助

這份 schema 的用途不是：

- 直接保證可獲利
- 直接變成自動下單策略
- 在沒有 review 的情況下當唯一決策依據
