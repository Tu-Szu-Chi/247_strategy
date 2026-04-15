## Background
現在我們可以從盤中即時資料抓到最近結算的兩檔選擇權且ATM+-20的option
我平常都是自己手動從XQ看盤軟體匯出資料到Excel自己建制表格來看最近結算的那檔選擇權各履約價的“力道”
而我現在希望有一個web UI介面讓我從盤中live record抓到的資料即時算出各履約價的力道, 統稱option-power

## Requirement
UI上可選擇要看哪一個週期的選擇權, 以我們目前架構而言只會有兩個選項, 預設選最近的
透過websocket每五秒發送一次統計過後的option-power給前端
UI應該長得像T-Shape Bar Chart, Y軸label是各履約價, X軸是“力道"
紅色代表多方力道較強, 綠色則是空方力道, 數值範圍就是整數(會有負數); 當某一履約價的紅柱遠大於綠柱，代表該價位多頭氣勢強；反之則空頭強

## Math
有鑒於目前live record拿到的tick除了price/vol之外, 還有up/down tick來告訴我們方向, 間接讓我們推算出內外盤比
但我們沒有現成的未平倉量, 跟以往透過XQ看盤軟體有些許不同, 請想替代方案, 或是看Finmind/Shiaoji能否拿到該期選擇權前一天夜盤的未平倉數據; 日盤就看昨日夜盤的未平倉, 夜盤就看當日日盤的未平倉
如果沒有未平倉數據, 就要找出替代方案試著把option-power的可信度提高

## Comment
## Discussion Conclusion

### Confirmed Product Decisions
- option-power 以「單合約」為單位計算，不做同履約價 call/put 合併
- call 與 put 各自擁有自己的 power
- UI 主視角以「當前盤別累積力道」為主
- UI 另外提供「最近一分鐘變化」作為輔助觀察，但不是主排序依據
- v1 可先不上未平倉量，先做 raw power；後續再加權提升可信度
- 相同 strike-price 的 call / put 在 UI 上應該是同一行顯示

### Engineering Direction
- power 計算必須以目前 live tick 可直接推得的買賣方向為基礎
- websocket 每 5 秒推送一次完整 snapshot 給前端
- 前端週期 selector 目前只需支援最近兩個到期日，預設最近到期
- 後端資料模型必須同時保留:
  - session cumulative power
  - latest 1m delta power
- 累積力道是 session-aware，不可跨日盤/夜盤直接延續

### v1 Math Baseline
- 先以 tick direction 將成交量拆成 buy volume / sell volume
- `cumulative_power = cumulative_buy_volume - cumulative_sell_volume`
- `power_1m_delta = last_1m_buy_volume - last_1m_sell_volume`
- 若某些 tick 無法判定方向，需單獨統計 unknown volume，不能默默併入任一側

### Deferred After v1
- 補前一盤或可取得的 open interest 作為 confidence weighting
- 研究 FinMind / Shioaji 是否能穩定取得選擇權未平倉量
- 加入 replay / run_id 回放能力

### Risks To Remember
- 不可直接使用跨盤別累積總量去乘上重置後的內外盤比
- 若資料源在盤別切換時重置比例或累積欄位，session reset 必須明確處理
- 若 UI 只顯示累積值，後段大成交履約價可能長時間佔據視覺焦點，因此 1m delta 必須保留作輔助訊號

### Product Clarification About "Nearest Two"
- 「最近兩檔選擇權」不能簡化成固定 `TXO` root 下最近兩個 delivery date
- 實際需求比較接近:
  - 根據台指選擇權週別 / 月別 root 判斷目前可交易的最近兩檔
  - 週三結算日的夜盤，應排除當天已結算的那一檔
- 例如在 `2026-04-15` 夜盤，應關注的是 `TXX` 與 `TX4`
- 因此 live universe resolver 應從多個 option root 中選出「當前最近兩檔」，而不是只從 `TXO` 選

## Implementation Plan

### v1 Goal
- 提供一個可在盤中使用的 web UI
- UI 可切換最近兩個到期日
- 後端每 5 秒推送一次 option-power snapshot
- 每個 option contract 都有自己的 cumulative power 與 1m delta power
- 第一版不依賴 OI 即可運作

### Proposed Architecture
- 保留現有 `record-live` 作為 tick ingestion 與落庫入口
- 新增 `option power service` 作為盤中即時計算與推播層
- `option power service` 直接接 live tick stream，在記憶體維護聚合狀態
- DB 仍持續保留 `raw_ticks` 作為 audit / replay / 日後回放基礎
- websocket publisher 每 5 秒對前端發送一次完整 snapshot

### Why This Cut
- 若改成「先落 DB 再查 DB 聚合再推播」，資料路徑較長，延遲與故障面都會增加
- option-power 是盤中即時觀察工具，主計算應在 live stream 當下完成
- `raw_ticks` 落庫仍有價值，但不應作為 UI 的即時主來源

### Backend Modules

#### 1. Option Power Domain
- 新增 option-power 專用 dataclass / payload model
- 需包含:
  - contract identity
  - expiry
  - strike price
  - call_put
  - cumulative buy volume
  - cumulative sell volume
  - cumulative power
  - rolling 1m buy volume
  - rolling 1m sell volume
  - 1m delta power
  - unknown volume
  - last tick ts

#### 2. In-Memory Aggregator
- 輸入為 `CanonicalTick`
- 只處理 option contract tick
- 依 `instrument_key` 維護單合約狀態
- 需同時維護:
  - session cumulative counters
  - 最近 1 分鐘 rolling window counters
- session 切換時必須 reset cumulative state
- rolling 1m 可用 time-bucket queue 或 per-second bucket 實作

#### 3. Snapshot Builder
- 每 5 秒從 aggregator 產出一次 immutable snapshot
- 依 `contract_month` 分組
- 每個 expiry 底下依 `strike_price` 與 `call_put` 排序
- 需附上 snapshot metadata:
  - generated_at
  - session
  - run_id
  - option_root
  - expiry list
  - contract_count
  - underlying reference price if available

#### 4. Web Service
- v1 建議新增輕量 ASGI service
- 建議技術選型:
  - `FastAPI` 提供 HTTP + websocket
  - `uvicorn` 作為 runtime server
- 提供兩類 endpoint:
  - `GET /api/option-power/snapshot`
  - `GET /ws/option-power`
- websocket 連線建立後先送一次當前 snapshot，再每 5 秒持續推送

#### 5. Runtime Wiring
- 新增 CLI 入口，例如:
  - `serve-option-power`
- 啟動流程:
  - resolve option universe
  - connect live provider
  - 啟動 aggregator
  - 啟動 websocket / HTTP service
  - 背景持續 ingest 與 snapshot broadcast
- v1 可接受此服務自己再接一次 live stream
- 若後續要與 `record-live` 合併，再收斂成單一 runtime process

### Power Calculation Rules

#### Tick Side Mapping
- `tick_direction == up` 視為 buy-initiated
- `tick_direction == down` 視為 sell-initiated
- 無法判定方向者記入 `unknown_volume`
- unknown volume 不併入 buy / sell 任一側

#### Formula
- `cumulative_power = cumulative_buy_volume - cumulative_sell_volume`
- `power_1m_delta = rolling_1m_buy_volume - rolling_1m_sell_volume`

#### Session Boundary
- 日盤與夜盤各自獨立累積
- 一旦 session 切換:
  - cumulative counters reset
  - 1m rolling window reset
  - snapshot metadata 更新 session

### Websocket Payload Draft

```json
{
  "type": "option_power_snapshot",
  "generated_at": "2026-04-15T09:15:10+08:00",
  "run_id": "uuid",
  "session": "day",
  "option_root": "TXO",
  "underlying_reference_price": 19876.0,
  "expiries": [
    {
      "contract_month": "202604W3",
      "label": "2026-04 W3",
      "contracts": [
        {
          "instrument_key": "TXO202604W319800C",
          "strike_price": 19800,
          "call_put": "call",
          "cumulative_buy_volume": 120,
          "cumulative_sell_volume": 80,
          "cumulative_power": 40,
          "rolling_1m_buy_volume": 12,
          "rolling_1m_sell_volume": 5,
          "power_1m_delta": 7,
          "unknown_volume": 3,
          "last_tick_ts": "2026-04-15T09:15:08+08:00"
        }
      ]
    }
  ]
}
```

### UI Plan

#### Layout
- 頁首顯示:
  - 當前 session
  - snapshot time
  - websocket connection status
  - underlying reference price
- 主區塊提供 expiry selector
- 預設選最近到期日
- 內容區為 T-shape / diverging bar chart

#### Row Semantics
- 一列代表一個 option contract，不做 call/put 合併
- `Y-axis label = strike + call_put`
  - 例如 `19800C`, `19800P`
- `X-axis = cumulative power`
- 紅色表示正 power
- 綠色表示負 power
- 每列右側額外顯示 `1m delta`
- 若 `unknown_volume > 0`，需有低調提示，不可完全隱藏

#### Sorting
- v1 預設以 `strike_price` 由小到大排列
- 不以 power 大小重排，避免視覺跳動太大
- 後續版本可再加入排序切換

### Suggested File/Module Layout
- `src/qt_platform/option_power/domain.py`
- `src/qt_platform/option_power/aggregator.py`
- `src/qt_platform/option_power/service.py`
- `src/qt_platform/web/app.py`
- `src/qt_platform/web/static/option_power.html`
- `src/qt_platform/web/static/option_power.js`
- `src/qt_platform/web/static/option_power.css`

### Delivery Phases

#### Phase 1: Backend Core
- 建立 option-power domain model
- 建立 in-memory aggregator
- 補 aggregator 單元測試
- 驗證 session reset 與 rolling 1m 計算

#### Phase 2: Web Service
- 建立 HTTP + websocket service
- 建立 snapshot endpoint
- 建立 background live ingestion loop
- 補 websocket payload smoke test

#### Phase 3: UI
- 完成單頁監控介面
- 接 websocket 並渲染 diverging bar chart
- 補空狀態 / 斷線狀態 / 無資料狀態

#### Phase 4: Hardening
- log 與錯誤處理
- 加入 reconnect / provider close handling
- 補 README / 操作文件

### Out Of Scope For v1
- OI weighting
- replay 歷史 run_id
- 多使用者權限
- 多頁面前端應用
- 從 DB 重建即時狀態

### Open Implementation Choices
- 若不想引入 `FastAPI`，可改用標準庫 + 極簡 websocket server，但開發成本較高且可維護性較差
- 若要最小化初期複雜度，v1 可先做單 process:
  - live provider
  - aggregator
  - websocket server
  - static file serving
- 等功能穩定後再考慮拆成 ingestion service 與 UI service

## Note
option-power的概念:

數據定義 (Data Fields)總量 (Total Volume): 該合約當前的累計成交口數。內外盤比 (Buy/Sell Ratio): 外盤成交量佔總成交量的百分比（範圍 0~100）。外盤 (Ask-Hit): 買方主動以市價成交，視為多方攻擊力。內盤 (Bid-Hit): 賣方主動以市價成交，視為空方攻擊力。2. Power 核心公式Power 代表該履約價的「淨攻擊力道」，計算公式如下：$$Power = 總量 \times (2 \times \frac{內外盤比}{100} - 1)$$邏輯說明：將 0~100% 的比例轉換為 -1 到 +1 的權重（50% 為 0）。當比例 > 50%，Power 為正（多方勝）；當比例 < 50%，Power 為負（空方勝）。該公式本質上等於：外盤成交量 - 內盤成交量。3. 數據源特性與問題 (Critical Constraints)數據來源: XQ 全球贏家。統計偏差問題:總量累加性: XQ 的「總量」在同一個交易日內（含日夜盤）通常是持續累加的。比例重算性: 每逢日盤（08:45）或夜盤（15:00）開盤時，XQ 的「內外盤比」會重新從 0% 開始計算（僅統計當前盤別的比例）。計算錯誤點: 若拿「全日累計總量」去乘上「剛開盤的夜盤比例」，會導致 Power 數值在換盤瞬間發生劇烈跳動（例如：日盤結束 Power 為 +200，夜盤第一筆為內盤成交，Power 會瞬間變成 -10,000）。
