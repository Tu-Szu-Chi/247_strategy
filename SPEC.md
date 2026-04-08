
# 📊 系統設計文件

## 0. Note
NOTE.md有些提示可以參考

## 1. 系統核心目標 (Project Goals)

* **全流程支持**
  涵蓋數據獲取、清洗、存儲、策略開發、回測驗證、盤中監測及自動下單。

* **高度解耦化**
  採用適配器模式，確保更換券商 API 或資料源時，核心策略與交易邏輯不需重寫。

* **資料自主性**
  建立完善的本地化時序資料庫，確保回測數據的一致性與完整性。

---

## 2. 技術棧 (Tech Stack)

* **語言**：Python 3.10+

* **資料庫**：TimescaleDB（基於 PostgreSQL，優化時序資料儲存與查詢）

* **即時行情**：KGI SuperPY（WebSocket）
> python -m pip install kgisuperpy

* **歷史資料**：FinMind API（Sponsor 專案）
> ./finmind_doc.txt

* **回測引擎**

  * VectorBT（快速驗證）
  * 自定義 Event-loop（精確模擬）

* **數據視覺化**

  * Streamlit：盤中即時監控面板
  * QuantStats：策略績效回測分析報告

---

## 3. 系統模組架構 (System Architecture)

### 3.1 數據適配層 (Data Adapters)

* 定義抽象介面 `BaseProvider`

  * `fetch_history()`
  * `subscribe_live()`

* 具體實作：

  * `FinMindAdapter`（REST API）
  * `KgiAdapter`（WebSocket）

---

### 3.2 策略引擎層 (Strategy Engine)

* **動態標的管理**
  內建邏輯自動根據台指期點位計算 ATM ±5 檔之週/月選擇權合約代碼。

* **事件驅動**

  * `on_tick()`
  * `on_bar()`

---

### 3.3 執行與風控層 (Execution & Risk)

* 定義 `BaseExecutor`

  * 區分：

    * 實戰下單（KGI）
    * 回測下單（Mock）

* 預留風控模組

  * 下單前檢查：

    * 保證金
    * 口數限制

---

## 4. 資料儲存設計 (Storage Layer)

### 4.1 Schema 定義

以 **1 分鐘 K 線 (1-Min Bar)** 為基礎，預留 Tick 資料表。

**核心欄位：**

* `timestamp`
* `symbol`
* `open`
* `high`
* `low`
* `close`
* `volume`
* `in_volume`（內盤量）
* `out_volume`（外盤量）
* `open_interest`（OI）

---

### 4.2 性能優化

* 使用 TimescaleDB 的 **Hypertable**

  * 自動時間分區

* 使用 `ON CONFLICT`

  * 實作 Upsert
  * 確保資料：

    * 不重複
    * 可修正

---

## 5. 資料維護與同步機制 (Maintenance Module)

### 5.1 完整性檢查 (Inventory Scan)

* 系統啟動時：

  * 檢查資料庫內各標的的起始與結束時間
  * 掃描交易日曆
  * 自動識別缺漏區間（Gaps）

---

### 5.2 自動補齊功能

* **Catch-up Sync**

  * 從資料庫最新一筆補齊至當前開盤日

* **Historical Backfill**

  * 支援手動輸入 `start_date`
  * 可拉取 3–5 年歷史資料

---

## 6. 流量與頻率控制 (Throttling)

### 6.1 頻率控制 (RPS Control)

* 支援可配置 RPS（Requests Per Second）
* 防止 API 帳號被封鎖

**計算公式：**

```
Interval = 1 / RPS
```

---

### 6.2 容錯與續傳

* **指數退避（Exponential Backoff）**

  * 遇到 429 / 5xx 自動延時重試

* **中斷續傳**

  * 記錄最後成功游標（Cursor）
  * 支援崩潰後續傳

---

## 7. 設定檔範例 (config.yaml)

```yaml
ingestion:
  finmind:
    rps_limit: 0.5        # 每兩秒發送一次請求
    retry_limit: 5        # 最大重試次數
    backoff_factor: 2     # 等待時間乘數

  kgi:
    max_connections: 2    # 符合新星級別連線數
    symbols_per_connection: 20

maintenance:
  auto_check_on_startup: true
  fill_gaps_automatically: true

secrets:
  env_path: ".env"        # 存放 API_KEY, DB_URL
```

---

### Reference
以下三個專案都是github上開源的, 跟量化交易/回測有關
./Kronos 
./backtrader
./phandasㄜ
