# MTX Signal Logic

這份文件只講目前研究頁內真正生效的兩個訊號：

- `Bias Signal`
- `Signal State`

它不負責解釋所有 regime feature，也不解釋 UI 排版。
如果你想知道各個 feature 本身的白話意義，請看：

- [MTX_REGIME_FEATURES.md](/Users/quentin-tu/Documents/247_strategy/docs/MTX_REGIME_FEATURES.md)

---

## 1. 先講分工

目前畫面上的兩層方向訊號分工是：

- `Bias Signal`
  - 回答：現在偏多、偏空，還是中性？
  - 角色：第一層方向傾向
- `Signal State`
  - 回答：在 `Bias` 已經成立後，其他 `Trend / Flow / Range / Pressure` 是否也足夠支持？
  - 角色：第二層過濾後方向訊號

所以：

- `Bias` 比較寬鬆
- `Signal` 比較嚴格

兩者目前都不是 event-based。
現在都屬於「持續狀態」輸出。

---

## 2. 輸出定義

### Bias Signal

- `+1 = long`
- `0 = neutral`
- `-1 = short`

### Signal State

- `+1 = long`
- `0 = neutral`
- `-1 = short`

所以現在的 `Signal State` 已經不是之前那些版本：

- 不是 `try / confirm / reverse / leave`
- 也不是 `entry / add / exit`

它現在就是：

- `Bias` 再經過更多條件過濾後的 `long / neutral / short`

---

## 3. Bias Signal 邏輯

`Bias Signal` 用到的輸入只有四個：

- `pressure_index`
- `regime_state`
- `structure_state`
- `trade_intensity_ratio_30b`

### 3.1 中間變數

先定義：

- `pressureSide`
  - `pressure_index >= 2 => +1`
  - `pressure_index <= -2 => -1`
  - 其餘 `0`

- `pressureSlope`
  - `pressure_index - previous_pressure_index >= 2 => +1`
  - `pressure_index - previous_pressure_index <= -2 => -1`
  - 其餘 `0`
  - 所以像 `-20 -> -15` 是：
    - `pressureSide = -1`
    - `pressureSlope = +1`
  - 代表還在空方區，但空壓正在減弱，不應當成新的空方確認

- `active`
  - `trade_intensity_ratio_30b >= 0.95`
  - 但這個 ratio 現在是「最近 5 根 bar」相對於「最近 30 根 1m bar 基準」的比值
  - 不再直接用固定 30 分鐘時鐘窗
  - 日夜盤切換時會自然重置，不跨盤別混算

### 3.2 規則

#### 先過濾強度

如果：

- `active = false`

則直接輸出：

- `Bias = 0`

也就是市場太安靜時，不給方向傾向。

#### long bias

如果同時滿足：

- `structure_state > 0`
- `pressureSide > 0`
- `pressureSlope >= 0`
- `regime_state >= 0`

則輸出：

- `Bias = +1`

#### short bias

如果同時滿足：

- `structure_state < 0`
- `pressureSide < 0`
- `pressureSlope <= 0`
- `regime_state <= 0`

則輸出：

- `Bias = -1`

#### 次要 fallback

如果上面那組條件沒成立，還有次要判斷：

- `structure_state > 0` 且 `regime_state > 0`
  - `Bias = +1`
- `structure_state < 0` 且 `regime_state < 0`
  - `Bias = -1`

其餘都是：

- `Bias = 0`

### 3.3 白話理解

`Bias` 的核心哲學很簡單：

- `structure` 是最重要的骨架
- `pressure` 提供方向
- `regime` 不要強烈反對
- `intensity` 不要太冷

所以它不是在抓進場點，而是在回答：

- 這盤目前有沒有一個大致可接受的方向傾向？

---

## 4. Trend / Flow / Range 在 Signal 裡怎麼被使用

`Signal State` 不直接使用原始圖上所有線，而是先把它們轉成比較簡化的狀態。

### 4.1 Trend 相關

使用：

- `adx_14`
- `choppiness_14`
- `di_bias_14`

先得到：

- `trendReady`
  - `adx_14 >= 18`
  - 且 `choppiness_14 <= 62`

- `trendBiasDirection`
  - `di_bias_14 > 8 => +1`
  - `di_bias_14 < -8 => -1`
  - 其餘 `0`

白話：

- `trendReady` 在回答：現在有沒有趨勢環境
- `trendBiasDirection` 在回答：趨勢偏多還偏空

### 4.2 Flow 相關

使用：

- `cvd_5b_slope`
- `cvd_price_alignment`
- `price_cvd_divergence_15b`

先得到：

- `flowThreshold`
  - 最近 30 根 bar `abs(cvd_5b_slope)` 的 rolling `q65`
  - 再和 `1` 比較取較大值

- `flowDirection`
  - `cvd_5b_slope > flowThreshold => +1`
  - `cvd_5b_slope < -flowThreshold => -1`
  - 否則 `0`

- `opposingDivergence`
  - `price_cvd_divergence_15b === -biasValue`

白話：

- `flowDirection` 在看近端主動成交推力偏哪一邊
- `cvd_price_alignment` 在看價格與 CVD 是否同向
- `opposingDivergence` 在看價格與 CVD 是否明顯反著 bias

### 4.3 Range 相關

使用：

- `compression_expansion_state`

前端把它簡化成：

- `-1 = compressed`
- `0 = normal`
- `1 = expanding`

在 `Signal` 裡的使用方式很直接：

- 如果 `rangeStateValue < 0`
  - 直接不給 signal

也就是：

- 還在壓縮盤時，不讓 `Signal State` 放行

---

## 5. Signal State 邏輯

`Signal State` 的目的不是重新發明方向。
它是：

- 先接受 `Bias`
- 再檢查更多 supporting evidence

如果支持夠多，才保留方向。
否則退回 `neutral`

### 5.1 額外使用的輸入

除了 `Bias` 已經用過的資料外，`Signal State` 額外還用：

- `raw_pressure`
- `adx_14`
- `choppiness_14`
- `di_bias_14`
- `cvd_5b_slope`
- `cvd_price_alignment`
- `price_cvd_divergence_15b`
- `compression_expansion_state`

### 5.2 中間變數

#### pressureSide / pressureSlope

- `pressureSide`
  - `pressure_index >= 2 => +1`
  - `pressure_index <= -2 => -1`
  - 其餘 `0`
- `pressureSlope`
  - `pressure_index - previous_pressure_index >= 2 => +1`
  - `pressure_index - previous_pressure_index <= -2 => -1`
  - 其餘 `0`

#### active

- `trade_intensity_ratio_30b >= 0.95`

#### strongPressure

- `abs(pressure_index) >= rollingQuantile(abs(pressure_index), 0.60)`
- 且至少要 `>= 3`

#### supportedRawPressure

- `abs(raw_pressure) >= rollingQuantile(abs(raw_pressure), 0.55)`
- 且至少要 `>= 3`

#### trendBiasDirection

- `di_bias_14 > 8 => +1`
- `di_bias_14 < -8 => -1`
- 否則 `0`

#### flowDirection

- `cvd_5b_slope > flowThreshold => +1`
- `cvd_5b_slope < -flowThreshold => -1`
- 否則 `0`

#### trendReady

- `adx_14 >= 18`
- 且 `choppiness_14 <= 62`

---

## 6. Signal State 的過濾步驟

### Step 1. 先排除不該給訊號的情況

如果出現以下任一條件，直接：

- `Signal = 0`

條件：

- `active = false`
- `biasValue = 0`
- `rangeStateValue < 0`
- `chop_score > 30`

白話：

- 市場太冷
- Bias 根本沒方向
- 還在壓縮盤
- chop 太高，先直接當噪音

這些情況下，Signal 不應該強出方向。

### Step 2. 看有沒有明顯反向背離

如果：

- `opposingDivergence = true`

則直接：

- `Signal = 0`

白話：

- 就算 Bias 偏多，如果價格與 CVD 已經出現對應的空方背離
- 那就先不要放行多方 signal

### Step 3. 計算 support score

這是 `Signal State` 的核心。

目前加分方式如下：

#### `structure_state` 同向

如果：

- `structure_state === biasValue`

加：

- `+2`

這是唯一加 2 分的條件，因為目前它被視為最重要的結構確認。

#### `regime_state` 同向

如果：

- `regime_state === biasValue`

加：

- `+1`

#### `trendBiasDirection` 同向

如果：

- `trendBiasDirection === biasValue`

加：

- `+1`

#### `flowDirection` 同向

如果：

- `flowDirection === biasValue`

加：

- `+1`

#### `cvd_price_alignment` 同向

如果：

- `cvdAlignmentValue === biasValue`

加：

- `+1`

#### `pressureDirection` 同向

如果：

- `pressureDirection === biasValue`

加：

- `+1`

#### `trendReady`

如果：

- `trendReady = true`

加：

- `+1`

#### `strongPressure`

如果：

- `strongPressure = true`

加：

- `+1`

#### `supportedRawPressure`

如果：

- `supportedRawPressure = true`

加：

- `+1`

#### `rangeStateValue > 0`

如果：

- `rangeStateValue > 0`

加：

- `+1`

### Step 4. 根據分數輸出結果

如果：

- `supportScore >= 6`

則：

- `Signal = biasValue`

也就是：

- `bias = +1 => signal = +1`
- `bias = -1 => signal = -1`

否則：

- `Signal = 0`

---

## 7. 白話總結

可以把它理解成：

- `Bias Signal`
  - 先回答：現在大方向偏多還偏空？

- `Signal State`
  - 再回答：這個 bias 有沒有足夠多的其他證據支持？

所以 `Signal` 不是另一套完全獨立的方向判斷。
它比較像：

- `Bias` 的加強版過濾器

---

## 8. 為什麼 Signal 會比 Bias 少

這是設計上故意的。

因為 `Signal` 比 `Bias` 多做了這些事情：

- 要求 `Range` 不能還在壓縮
- 會檢查 `CVD divergence`
- 會累積 support score
- 要求至少 `6` 分才放行

所以很自然會出現：

- `Bias = long`
- 但 `Signal = neutral`

這不代表程式錯。
它代表：

- 市場有方向傾向
- 但 supporting evidence 還不夠完整

---

## 9. 目前版本的限制

這份文件描述的是「當前實作」，不是最終正確答案。

目前有幾個你要特別記得的限制：

- `Bias` 很依賴 `structure_state`
- `structure_state` 目前可能偏嚴，常常卡在 `0`
- `Signal` 的 `supportScore >= 6` 仍然是人工規則，不是回測校正出的最佳值
- `Range` 目前只做簡化三態，還沒細分 `expanding` 和 `expanded`
- `Flow` 與 `Trend` 的門檻，也都還在研究中

所以這份文件比較適合拿來：

- 檢查目前邏輯到底在做什麼
- 討論哪一層規則該放寬或改寫

而不是把它當成交易真理。
