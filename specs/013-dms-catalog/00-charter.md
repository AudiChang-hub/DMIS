# 013-dms-catalog — Charter

## 模組宗旨

整併既有 `dms_product`（產品管理）與 `dms_pricelist`（價目管理）為統一的 **`dms_catalog`** 模組。

本模組負責：
- 產品目錄分層管理（品牌 → 型式 → SKU）
- 版本化定價（依生效日期管理，多版本共存，系統自動推算有效期）
- 彈性分期規則範本（可複用於多款 SKU）
- 可擴充費用類型（開辦費、設定費等）
- 精品、電車牌險、傭金規則（保留現有功能，不刪除）

## 整併聲明

| 舊模組 | 狀態 | 說明 |
|---|---|---|
| `dms_product` | **取代** | 由 `dms_catalog` 完整承接，保留向下相容資料遷移 |
| `dms_pricelist` | **取代** | 由 `dms_catalog` 完整承接，保留向下相容資料遷移 |

**凍結模組保護**：本次整併**不得修改** `addons/dms_core/`（凍結模組）的任何原始檔案。如需參照 `dms.brand`、`dms.dealer`，以 `Many2one` 引用方式進行。

## 核心設計原則

1. **分層清晰**：品牌（`dms.brand` in dms_core） → 產品型式（`dms.product.template`） → SKU（`dms.product.sku`）
2. **版本化定價**：`dms.price.version` 只記錄生效日，End date 由系統自動從下一版本的生效日推算
3. **規則範本可複用**：`dms.installment.rule` 為獨立範本，透過關聯表綁定至特定 SKU × 價格版本
4. **費用類型可擴充**：`dms.fee.type` 主檔維護費用分類

## 依賴關係

```
dms_core  ←  dms_catalog
```

`dms_catalog` 取代後，所有依賴 `dms_product` 或 `dms_pricelist` 的模組（`dms_sale`、`dms_finance`、`dms_visit` 等）若有欄位參照，須依 migration/compatibility 計劃更新。

## 版本資訊

| 項目 | 值 |
|---|---|
| 模組名稱 | `dms_catalog` |
| Odoo 版本 | 16.0 |
| 初始版本 | 16.0.1.0.0 |
| 需求發起日 | 2025-05 |
| 狀態 | Draft |
