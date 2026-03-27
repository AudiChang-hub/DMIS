# 013-dms-catalog — 澄清紀錄（02-clarify）
## 已確認問題與决策（OQ-1 ~ OQ-7）

> 以下為本輪定稿前由專案負責人明確決策的全部 Open Questions，不得膪自變更。

**OQ-1：機種層級設計（已確認）**
> Q: `dms.product.template` 的「機種」要用自由文字還是主檔？
> A: **做成主檔 Many2one**。新增 `dms.product.series`（車系）主檔；型式透過 `series_id` Many2one 關聯。車系是具有可查尋識別意義的車系名稱（例：FORCE、SMAX、EC-05），不是速克達/越野車那種粗分類。

**OQ-2：舊依賴模組遷移時間表（已確認）**
> Q: 本輪是否同步遷移 `dms_sale` / `dms_visit` / `dms_finance`？
> A: **本輪不遷移。**只完成 `dms_catalog` 整併。`dms_sale`、`dms_visit`、`dms_finance` 檙結對舊模型的引用不變，遷移另排下一輪。

**OQ-3：車色相容策略（已確認）**
> Q: `dms.product.color` 本輪是否替換為 Many2one？
> A: **保留 `dms.product.color` 主檔概念，本輪相容為主。**`dms.product.sku` 的 `color` 欄位不強制替換成 Many2one，對現有容不強推替換［下一輪再統一接入定義。

**OQ-4：圖片願敏度（已確認）**
> Q: `image_1920` 欄位是否於本輪移除？
> A: **保留資料庫欄位，不顯示於主要畫面。**`image_1920` 僅保留欄位定義，Form / List / Kanban 主要視圖均不顯示圖片 avatar。未來募需再加入圖片頁籤。

**OQ-5：Kanban 首要視圖（已確認）**
> Q: `dms.product.template` 是否以 Kanban 為預設？
> A: **List 為主視圖，Kanban 降為次要。**預設 CRUD 入口導向 List；Kanban 可切換但瀏覽依賴，不包含圖片 avatar。

**OQ-6：`dms_sale` 分期欄位整合（已確認）**
> Q: 本輪是否連查 `dms_sale` 分期欄位取得 `dms.installment.rule`？
> A: **本輪不動 `dms_sale`。**分期規則整合是下一輪內容。

**OQ-7：`dms_product` / `dms_pricelist` 退場策略（已確認）**
> Q: 舊模組是否立即移除？
> A: **現在標記 deprecated，不立即移除。**在 manifest `description` 加入 `⚠️ DEPRECATED` 說明。等 `dms_sale` / `dms_visit` / `dms_finance` 泽移完成後，再正式移除底層程式碼。

---
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
