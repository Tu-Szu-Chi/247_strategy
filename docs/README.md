# Docs Guide

這個資料夾目前分成兩類文件：

## Current

這些文件應該優先當成目前 codebase 的工作基準：

- `ARCHITECTURE.md`
- `OPERATIONS.md`
- `DATA_PIPELINE.md`
- `SCHEMA.md`

## Research / Historical

這些文件保留研究脈絡、設計歷程或候選方向，但內容可能引用已搬移或已刪除的 code path，不應直接當成實作真相：

- `POLARS_INDICATOR_BACKEND_PLAN.md`
- `MTX_PROBABILITY_SPEC.md`
- `KRONOS_PROBABILITY_INTEGRATION.md`
- `MTX_REGIME_CANDIDATE_INDICATORS.md`
- `MTX_REGIME_FEATURES.md`
- `MTX_REGIME_SCHEMA.md`

若文件內容與 code 衝突，請以 `src/qt_platform/*`、測試、以及上面 `Current` 區的文件為準。
