# Charter / 宗旨 — 014-module-removal

> 2026-03-27 收尾註記：本規格已完成文件同步、資料庫 `dms_catalog` 殘留 metadata 清理，以及整併後的升級/測試驗證。維運腳本位於 [`scripts/cleanup_dms_catalog_metadata.py`](/home/audi/project/DMIS/scripts/cleanup_dms_catalog_metadata.py)。

## 目的

移除三個獨立模組：

| 模組技術名稱 | 顯示名稱 |
|---|---|
| `dms_product` | DMS 產品管理 |
| `dms_pricelist` | DMS 價目管理 |
| `dms_catalog` | DMS 產品目錄 |

## 動機

1. **功能重疊**：`dms_catalog` 是 `dms_product` + `dms_pricelist` 的整合替代版，三者並存造成維護負擔加重。
2. **簡化架構**：移除多餘的獨立應用程式選單，降低模組間依賴鏈複雜度。
3. **功能整合**：原本分散於 `dms_product` / `dms_pricelist` 中、仍被 `dms_sale` 及 `dms_visit` 使用的共用模型，統一遷移至 `dms_sale`，維持銷售流程完整性。

## 範圍

### 移除（直接刪除資料夾）
- `addons/dms_catalog/`：無其他模組依賴，可整體刪除。

### 解耦後移除
- `addons/dms_product/`：`dms_sale` 與 `dms_visit` 依賴其模型 → 先遷移模型至 `dms_sale`，再移除。
- `addons/dms_pricelist/`：`dms_sale` 依賴其多個模型 → 先遷移模型至 `dms_sale`，再移除。

## 不在範圍內

- `dms_core`（凍結模組，不可修改）
- `dms_customer`, `dms_finance`, `dms_report`, `dms_report_rule`, `dms_report_virtual`, `dms_visit`, `user_management` — 功能不變，僅更新依賴宣告

## 核心原則

- 規格優先：所有程式碼異動於本 Spec 完成後方可實作。
- 不破壞現有使用者操作：`dms_core`（車行管理）與 `user_management`（使用者管理）兩大主力模組維持 100% 功能正常。
- 向下相容：已存在的資料紀錄（dms.product, dms.accessory 等）須能平滑遷移。
- 完整驗收：所有 `make smoke` 及既有測試必須通過。
