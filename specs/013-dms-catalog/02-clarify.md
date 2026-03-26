# 013-dms-catalog — 澄清紀錄（02-clarify）

## 整併範圍

**Q: `dms_product` 與 `dms_pricelist` 是否立即停用？**
A: **不立即停用**。新模組 `dms_catalog` 提供新的分層模型，舊模型（`dms.product`、`dms.vehicle.price`、`dms.installment.plan`）暫時保留以維持向下相容，等到 `dms_sale`、`dms_finance`、`dms_visit` 等依賴模組遷移完成後再廢棄。

**Q: `dms_catalog` 的 dependency 設定？**
A: 只依賴 `dms_core`（提供 `dms.brand`、`dms.dealer`）。`dms_product` 和 `dms_pricelist` 設定為 `dms_catalog` **不依賴**（避免 circular dependency），而是透過資料遷移腳本搬移資料。

**Q: Kanban 設定視圖是否需要重寫？**
A: 搬移至 `dms_catalog`，對應模型改為 `dms.product.template`，欄位名稱與原 `dms.kanban.product.config` 保持一致（`show_model`、`show_year` 等），最小化改動。

## 遷移策略細節

**Q: `dms.product` 中的 color/color_code/year 如何拆分？**
A: 一筆 `dms.product` 對應一筆 `dms.product.sku`（因原設計已是顏色粒度），`template` 層以 `brand_id + name + model + energy_type` 為 key 合併同型號的多筆紀錄（若有）。

**Q: `dms.vehicle.price.installment_ids` 如何遷移？**
A: 每個 `dms.vehicle.price` 建立一個 `dms.price.version`（`name = valid_year_month`，`effective_date = <parsed date>`），再建立對應的 `dms.price.line`。`dms.installment.plan` 紀錄合併成一個 `dms.installment.rule`（以 `finance_company` 分組），再建立對應的 `dms.installment.rule.line`。

**Q: 費用類型初始資料？**
A: 在 `data/fee_type_data.xml` 中預載：
- 開辦費（OPEN）
- 設定費（SETUP）

可由管理員自行新增。

## 保護原則

- **嚴禁**修改 `addons/dms_core/` 任何檔案
- `dms.brand` 以 `Many2one` 引用，不繼承、不重寫
- `dms.dealer` 同上
- `dms_catalog` 不得修改 `dms_core` security/ACL 設定

## SKU 代碼生成規則

`sku_code` 格式建議：`{brand_code}-{model_code}-{color_code_abbr}-{year}`，例：`YAM-F2E-WHT-2026`。
第一版可由使用者手動填寫，後續版本再實作自動生成。

## 版本狀態流轉

```
draft → active → archived
```

- `draft`：草稿，不對外顯示
- `active`：當前有效版本（系統允許多個 active，由 effective_date 決定優先順序）
- `archived`：已封存

## 不在範圍內（Out of Scope）

- 不實作庫存整合（庫存由 `dms_core` 的 `dms.vehicle` 管理）
- 不實作自動報價單（屬 `dms_sale` 功能模組）
- 不修改 `dms_sale`、`dms_finance`、`dms_visit`（遷移另行排程）
