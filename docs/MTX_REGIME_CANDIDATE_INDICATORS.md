# MTX Regime Candidate Indicators

這份文件是 `MTX regime filter` 的候選指標研究筆記。

目的不是定義最終 schema，也不是直接產生進出場策略，而是先把值得嘗試的 6 個指標拆清楚：

- 它想回答什麼問題
- 需要哪些現有資料
- 第一版可以怎麼計算
- 哪些參數值得調
- 適合接到 `trend_score`、`chop_score`、`reversal_risk` 的哪一部分

目前可用資料：

- `bars_1m`: `open/high/low/close/volume/up_ticks/down_ticks/session/trading_day`
- `raw_ticks`: `price/size/tick_direction/bid_side_total_vol/ask_side_total_vol/session/trading_day`
- `option-power snapshot`: `pressure_index`、`pressure_index_weighted`、各合約 cumulative / rolling 1m power

## 設計原則

- 所有指標都必須能用已落庫資料 replay，避免只在 live 才算得出來。
- 日盤與夜盤獨立計算，不跨 session 累積。
- 指標先作為 regime/context，不直接當買賣訊號。
- 先保留可解讀欄位，再用少量 composite score 加總。
- 參數要能調，不要把 window、threshold、權重寫死成不可研究的常數。

## 1. ADX / Choppiness

### 想回答的問題

現在的盤是真的有趨勢，還是只是看起來波動很大但其實來回洗？

`directional_efficiency_15m` 已經在回答類似問題，但它比較簡化。ADX / Choppiness 可以補足兩件事：

- ADX: 最近推進是否持續集中在同一方向。
- Choppiness: 最近波動是否大多消耗在來回震盪，而不是乾淨位移。

### 資料來源

- 主要用 `bars_1m.open/high/low/close`
- 可選擇用 `volume` 做輔助權重，但第一版不需要

### 第一版欄位草案

- `adx_14`: 14 根 1m bar 的 ADX。
- `plus_di_14`: +DI。
- `minus_di_14`: -DI。
- `di_bias_14`: `plus_di_14 - minus_di_14`，表示方向偏多或偏空。
- `choppiness_14`: 14 根 1m bar 的 Choppiness Index。

### 初始解讀

- `adx_14` 高、`choppiness_14` 低：比較像趨勢盤。
- `adx_14` 低、`choppiness_14` 高：比較像盤整盤。
- `adx_14` 高但 `di_bias_14` 與 tick flow 相反：可能提高 `reversal_risk`。

### 可調參數

- `adx_window`: 14、20、30。
- `chop_window`: 14、20、30。
- `adx_trend_threshold`: 初始可測 20、25、30。
- `chop_threshold`: 初始可測 55、60、65。

### 接入 composite score

- `trend_score`: ADX 高、Choppiness 低時加分。
- `chop_score`: ADX 低、Choppiness 高時加分。
- `reversal_risk`: ADX 高但短線 tick flow / CVD 開始反向時加分。

### 研究注意

ADX 會慢半拍，不能用來抓第一根突破。它比較適合用來確認「突破後是否進入可延續狀態」。

## 2. Opening Range State

### 想回答的問題

這一盤是不是走出典型的開盤定方向？突破開盤區間後，是延續還是假突破？

台指期日盤與夜盤都有明確開盤節奏，opening range 對 regime filter 很直觀。

### 資料來源

- `bars_1m.high/low/close/session/trading_day`
- 日盤與夜盤分開定義 opening range

### 第一版欄位草案

- `opening_range_minutes`: 使用的開盤區間分鐘數，初始 15。
- `opening_range_high`: 本 session 開盤前 N 分鐘高點。
- `opening_range_low`: 本 session 開盤前 N 分鐘低點。
- `opening_range_width_bps`: opening range 寬度相對開盤區間中點的 bps。
- `opening_range_state`: `inside` / `breakout_up` / `breakout_down` / `not_ready`。
- `opening_range_extension_bps`: close 超出 opening range 的距離。
- `opening_range_false_break_count`: 突破後又回到 range 內的次數。

### 初始解讀

- range 不寬，突破後持續在 range 外：偏趨勢。
- range 很寬，突破後很快回 range 內：偏假突破或震盪。
- 多次上下突破又回來：提高 `chop_score`。

### 可調參數

- `opening_range_minutes`: 5、10、15、30。
- `min_range_width_bps`: 過窄時避免被一兩跳噪音誤判突破。
- `breakout_buffer_bps`: 突破需要超出 range 幾個 bps 才成立。
- `false_break_return_minutes`: 突破後幾分鐘內回 range 算假突破。

### 接入 composite score

- `trend_score`: 有效突破且 `directional_efficiency`、CVD、option pressure 同向時加分。
- `chop_score`: `false_break_count` 高、反覆回 range 內時加分。
- `reversal_risk`: 突破方向與 tick flow / CVD 反向時加分。

### 研究注意

Opening range 對 session 開始時間很敏感。實作時要完全依照現有 `session` 與 `trading_day` 邏輯，不能用自然日切分。

## 3. Range Compression / Expansion

### 想回答的問題

市場是不是先壓縮、再擴張、再往單一方向延續？

這是從 TradingView 常見 squeeze / breakout 類策略拆出的 regime 概念。重點不是看到波動放大就追，而是確認放大前是否有壓縮，放大後是否有效率。

### 資料來源

- `bars_1m.high/low/close/volume`
- 可搭配既有 `range_ratio_5m_30m`

### 第一版欄位草案

- `range_width_5m_bps`: 最近 5m high-low range。
- `range_width_30m_bps`: 最近 30m high-low range。
- `range_width_percentile_60m`: 目前短線 range 在最近 60m 中的分位數。
- `compression_score`: range 是否處於低分位，範圍 0-100。
- `expansion_score`: 壓縮後是否開始擴張，範圍 0-100。
- `compression_expansion_state`: `compressed` / `expanding` / `expanded` / `normal`。

### 初始解讀

- `compressed`: 盤很窄，等待方向，不代表可追。
- `expanding` 且 `directional_efficiency` 高：可能開始趨勢。
- `expanded` 但效率低：高波動洗盤，不適合把它當乾淨趨勢。

### 可調參數

- `short_window`: 5、10。
- `long_window`: 30、60。
- `percentile_lookback`: 60、120。
- `compression_percentile`: 20%、25%、30%。
- `expansion_multiplier`: 1.5、2.0、2.5。

### 接入 composite score

- `trend_score`: 從 `compressed` 轉 `expanding`，且效率、CVD、option pressure 同向時加分。
- `chop_score`: 長時間 `compressed` 或 `expanded` 但效率低時加分。
- `reversal_risk`: 擴張後很快失敗、價格回到 range 中心時加分。

### 研究注意

這個指標最容易被過度解讀。第一版應該只標記狀態，不直接決定方向。

## 4. Session CVD / Price Divergence

### 想回答的問題

主動買賣量是否真的支持價格方向？有沒有出現價格創高但 CVD 沒跟、或價格創低但 CVD 沒跟的背離？

這是 TradingView order flow / cumulative delta 類指標最值得搬到本專案的部分，因為我們有 `raw_ticks.tick_direction` 與 `size`。

### 資料來源

- `raw_ticks.price`
- `raw_ticks.size`
- `raw_ticks.tick_direction`
- `raw_ticks.session`

### 第一版欄位草案

- `session_cvd`: 本 session 累積 signed volume。
- `cvd_5m_delta`: 最近 5m CVD 變化。
- `cvd_15m_delta`: 最近 15m CVD 變化。
- `cvd_5m_slope`: 最近 5m CVD 斜率。
- `price_cvd_divergence_15m`: `none` / `bearish` / `bullish`。
- `cvd_price_alignment`: `aligned_up` / `aligned_down` / `diverged` / `neutral`。

signed volume 草案：

```text
tick_direction = up   -> +size
tick_direction = down -> -size
other                 -> 0
```

### 初始解讀

- 價格上漲且 CVD 上升：多方推動比較可信。
- 價格下跌且 CVD 下降：空方推動比較可信。
- 價格創高但 CVD 沒創高：多方推動減弱，可能提高反轉風險。
- 價格創低但 CVD 沒創低：空方推動減弱，可能提高反彈風險。

### 可調參數

- `cvd_short_window`: 5、10。
- `cvd_medium_window`: 15、30。
- `pivot_lookback`: 10、15、20。
- `divergence_min_price_move_bps`: 避免小波動誤判背離。
- `divergence_min_cvd_delta`: 避免 CVD 小幅差異誤判。

### 接入 composite score

- `trend_score`: 價格方向與 CVD 同向時加分。
- `chop_score`: CVD 來回穿越 0 或短窗方向反覆翻轉時加分。
- `reversal_risk`: 價格與 CVD 背離時加分。

### 研究注意

`tick_direction` 是方向 proxy，不等於完整逐筆買賣盤判定。第一版要保留 `unknown` 或 0，不應硬分到任一側。

## 5. Price Impact Per Signed Volume

### 想回答的問題

主動買賣量進來時，價格推不推得動？如果很多主動買但價格不漲，可能是上方吸收；很多主動賣但價格不跌，可能是下方承接。

這可以補足 CVD 的盲點。CVD 只看力道方向，price impact 看力道是否真的改變價格。

### 資料來源

- `raw_ticks.price/size/tick_direction`
- 也可用 `bars_1m.close` 做較粗版本

### 第一版欄位草案

- `signed_volume_5m`: 最近 5m signed volume。
- `price_change_5m_bps`: 最近 5m 價格變化。
- `price_impact_5m`: `price_change_5m_bps / abs(signed_volume_5m)`。
- `absorption_score_5m`: signed volume 大但 price change 小時提高。
- `impact_direction`: `efficient_up` / `efficient_down` / `absorbed_buying` / `absorbed_selling` / `neutral`。

### 初始解讀

- signed volume 大、價格同向移動大：推動有效。
- signed volume 大、價格不動：吸收，可能是假突破或反轉前兆。
- signed volume 小、價格移動大：市場很薄，趨勢可能快但也容易滑。

### 可調參數

- `impact_window`: 3、5、10。
- `large_signed_volume_percentile`: 70%、80%、90%。
- `low_price_move_bps`: 2、3、5 bps。
- `impact_normalization`: 用 raw signed volume、tick count、或 percentile-normalized signed volume。

### 接入 composite score

- `trend_score`: signed volume 與價格同向，且 impact 有效時加分。
- `chop_score`: 大量雙向成交但 impact 低時加分。
- `reversal_risk`: 單向 signed volume 很大但價格不跟時加分。

### 研究注意

不同時段成交量基準差很多，最好用同 session 的 rolling percentile 做 normalizer，避免開盤與盤中冷清時段互相比較失真。

## 6. Option Pressure Alignment

### 想回答的問題

選擇權力道與 MTX 本身是否互相確認？還是 option-power 很強，但 MTX 價格、CVD、regime 都沒有跟？

這是本專案和一般 TradingView 單商品策略最大的差異，也是最可能形成優勢的地方。

### 資料來源

- MTX `bars_1m.close`
- MTX `raw_ticks.tick_direction/size`
- option-power `pressure_index`
- option-power `pressure_index_weighted`
- option-power rolling 1m pressure 或各合約 `power_1m_delta`

### 第一版欄位草案

- `option_pressure_1m`: 最近 1m option pressure。
- `option_pressure_session`: session cumulative option pressure。
- `option_pressure_direction`: `up` / `down` / `neutral`。
- `mtx_price_direction_5m`: MTX 最近 5m 價格方向。
- `mtx_cvd_direction_5m`: MTX 最近 5m CVD 方向。
- `option_mtx_alignment`: `aligned_up` / `aligned_down` / `option_leads` / `mtx_leads` / `diverged` / `neutral`.
- `option_pressure_divergence_score`: 0-100。

### 初始解讀

- option pressure、MTX 價格、MTX CVD 同向：訊號可信度提高。
- option pressure 強，但 MTX 價格不動：可能是吸收、尚未發動，或只是選擇權局部熱點。
- MTX 已突破，但 option pressure 沒跟：突破可信度下降。
- cumulative pressure 還強，但 1m pressure 反向：可能是趨勢鈍化。

### 可調參數

- `pressure_neutral_threshold`: 小於多少視為 neutral。
- `pressure_strong_threshold`: 大於多少視為 strong。
- `alignment_window`: 1、3、5。
- `price_direction_min_bps`: MTX 移動超過多少才算方向成立。
- `cvd_direction_min_delta`: CVD 變化超過多少才算方向成立。

### 接入 composite score

- `trend_score`: option pressure、MTX price、MTX CVD 同向時加分。
- `chop_score`: option pressure 強但 MTX range/efficiency 很低時加分。
- `reversal_risk`: cumulative 與 1m pressure 反向，或 option pressure 與 MTX CVD/price 背離時加分。

### 研究注意

Option pressure 不應直接覆蓋 MTX regime。比較好的角色是 confirmation / divergence layer：當 MTX 自己已經乾淨，option-power 提高信心；當 MTX 自己很亂，option-power 再強也應該降權。

## 建議研究順序

1. 先做 `ADX / Choppiness` 與 `Range Compression / Expansion`，因為只依賴 `bars_1m`，最容易 replay 與檢查。
2. 再做 `Session CVD / Price Divergence` 與 `Price Impact Per Signed Volume`，因為它們能直接利用 `raw_ticks` 的優勢。
3. 接著做 `Opening Range State`，它很有台指期盤中特性，但需要確認 session 開盤時間與假突破定義。
4. 最後做 `Option Pressure Alignment`，因為它需要把 MTX regime 與 option-power snapshot 的時間軸對齊。

## 初始 Composite Score 草案

第一版可以先不改現有分數，只把新欄位顯示在 replay/research UI。等肉眼 review 後，再用以下方向接入：

### trend_score candidates

- `adx_14` 高
- `choppiness_14` 低
- opening range 有效突破
- 壓縮後擴張，且 `directional_efficiency` 高
- MTX 價格與 CVD 同向
- price impact 有效
- option pressure 與 MTX 同向

### chop_score candidates

- `adx_14` 低
- `choppiness_14` 高
- opening range 反覆假突破
- range 長時間壓縮但未擴張
- 高成交但 low price impact
- option pressure 強但 MTX 價格不動

### reversal_risk candidates

- 價格與 CVD 背離
- signed volume 大但價格不跟
- opening range 突破失敗
- cumulative option pressure 與 rolling 1m pressure 反向
- ADX 高但短線 tick flow / CVD 已反向

## 不建議第一版就做的事

- 不先把所有 TradingView entry/exit 規則搬進來。
- 不把單一指標直接當成 buy/sell。
- 不用未確認的未來 bar 來判斷 pivot，避免 replay 看起來準、live 卻不可用。
- 不把 day session 與 night session 的狀態混在一起。
- 不先落 DB schema，等 replay 研究確認欄位有用後再決定是否持久化。
