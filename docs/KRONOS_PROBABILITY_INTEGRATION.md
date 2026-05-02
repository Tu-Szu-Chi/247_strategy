# Kronos 整合機率指標方案 (Kronos Probability Integration Strategy)

## 1. 核心設計理念 (Core Concept)
針對台指期 (MTX) 當沖交易，核心需求是計算「統計機率」而非單純預測點位。
*   **目標指標範例**：`mtx_up_50_in_10_mins_probability` (10 分鐘內上漲 50 點的機率)。
*   **方法論**：利用 Kronos 的生成式 AI 特性進行 **蒙地卡羅模擬 (Monte Carlo Simulation)**。

## 2. 技術可行性分析
Kronos 是一個基於 Transformer 的自迴歸模型 (Autoregressive Model)，推論過程如下：
1.  輸入歷史 K 棒序列。
2.  模型生成下一根 K 棒的機率分佈。
3.  根據 `sample_count` 參數進行 N 次隨機採樣，產生 N 條可能的未來路徑。
4.  **機率計算**：若 100 條路徑中有 30 條符合「觸及當前價 + 50」的條件，則該指標值為 `0.3`。

## 3. 需解決的技術瓶頸
根據對 `vendor/Kronos/model/kronos.py` 的程式碼審查，目前存在以下限制：
*   **路徑平均化**：現有的 `KronosPredictor` 會在回傳前執行 `np.mean(preds, axis=1)`，這會抹除掉波動度的分佈資訊，僅保留平均預期值。
*   **效能開銷**：`sample_count` 設高（例如 100）會增加推論時間，需評估在當沖實時環境下的延遲。

## 4. 具體實作藍圖

### 階段一：Kronos 底層擴充 (Surgical Modification)
修改 `vendor/Kronos/model/kronos.py`，讓 `predict` 方法支援回傳原始路徑：
```python
# 預計修改方向
def predict(self, ..., return_raw_paths=False):
    # ... 推論邏輯 ...
    if return_raw_paths:
        return preds  # 回傳 (sample_count, pred_len, features) 矩陣
    return np.mean(preds, axis=1) # 原有邏輯
```

### 階段二：建立專案指標封裝 (Feature Wrapper)
在主專案 `src/` 中建立指標類別，負責：
1.  **資料預處理**：將主系統的即時 1 分 K 轉換為 Kronos 格式。
2.  **機率算子執行**：
    ```python
    def calculate_prob(paths, threshold_delta):
        # paths shape: (100, 10, 6) -> 100 條路徑, 10 分鐘, 6 個特徵(OHLCVA)
        # 檢查每條路徑在 10 分鐘內是否有任何一根 High 超過門檻
        success = (paths[:, :, 1] >= current_price + threshold_delta).any(axis=1)
        return success.mean()
    ```

### 階段三：效能與部署優化
*   **模型選擇**：優先使用 `Kronos-mini` 或 `Kronos-small` 以換取推論速度。
*   **硬體加速**：強制指派至 `cuda:0` 或 `mps` 執行。
*   **非同步計算**：指標計算不應阻塞主交易迴圈 (Main Event Loop)，建議採用 Worker Pattern。

## 5. 後續研究方向
*   **訊號過濾**：當機率大於 70% 時，再結合現有的「選擇權力道」與「權值股動向」進行多重確認。
*   **反向驗證**：觀察當機率很高但價格未如預期移動時，是否代表市場發生了模型未捕捉到的結構性改變。

## 5.1 其他參考因子
*   **前十大權值股動能**：五檔掛單/大單成交/短線撐壓
*   **盤勢預估**: 預估成交量
