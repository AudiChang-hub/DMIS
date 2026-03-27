# Clarify（澄清）— 014-module-removal

## 假設與决策

### D1：模型遷移採「原地整合」策略

**決策**：將 `dms.product`、`dms.product.color`、`dms.accessory` 等仍被其他模組使用的模型，遷移至 `dms_sale`，而非建立新模組。

**原因**：
- 避免新增不必要的中介模組
- `dms_sale` 是這些模型唯一有意義的業務宿主
- 技術名稱（`_name`）完全不變，資料庫 Table 不需搬移，**零資料遷移風險**

---

### D2：`dms_visit` 改依賴 `dms_sale`

**決策**：`dms_visit` 的 `depends` 從 `dms_product` 改為 `dms_sale`。

**原因**：`visit_item.product_id` 引用 `dms.product`，此模型移至 `dms_sale` 後，`dms_visit` 需更新依賴宣告。在業務邏輯上，拜訪送出物品（产品）與銷售產品清單一致，依賴 `dms_sale` 合理。

**風險**：`dms_visit` 安裝時必須同時安裝 `dms_sale`；評估為可接受。

---

### D3：dms_catalog 直接刪除，不遷移任何模型

**決策**：`dms_catalog` 的所有模型（`dms.catalog.*`）均無其他模組引用，直接刪除資料夾，不作任何遷移。

**注意**：若生產環境已安裝 `dms_catalog` 且資料庫中有 `dms.catalog.*` 資料表，需在移除前先在 Odoo 中卸載此模組（UI → Settings → Apps → Uninstall），讓 Odoo 自動清除相關資料表與 IR 記錄。

---

### D4：不移除 dms_accessory.price 模型

**決策**：`dms.accessory.price`（精品價格歷史紀錄）隨 `dms.accessory` 一並遷移至 `dms_sale`，即使目前 dms_sale 未使用此模型，亦保留以維持資料完整性。

---

### D5：視圖保留、選單整合

**決策**：從 `dms_product` 與 `dms_pricelist` 搬入的視圖保留原有功能，整合至 `dms_sale` 的子選單「產品資料」與「價目資料」，不做 UI 設計變更。

---

### D6：ACL 合併，群組不變

**決策**：`dms_product/security/ir.model.access.csv` 與 `dms_pricelist/security/ir.model.access.csv` 的記錄合併至 `dms_sale/security/ir.model.access.csv`，不新增或刪除任何 res.groups 記錄。

---

### D7：static assets 改路徑，不改功能

**決策**：JS/CSS 檔案搬至 `dms_sale/static/`，並更新 `__manifest__.py` 中的 `assets` 路徑宣告，檔案內容不改。

---

### D8：dms_core 完全不動

**決策**：嚴格遵守 `dms_core` 凍結規範。模型遷移的宿主為 `dms_sale`，不借用 `dms_core`。

---

### D9：清理已移除模組的殘留 registry metadata 與舊 UI

**決策**：若資料庫中 `dms_catalog` / `dms_product` / `dms_pricelist` 已為 `uninstalled`，但仍保留 catalog-only 模型的 `ir.model` / `ir.model.data` / `ir.model.fields` 註冊資料、舊選單 / 舊 action / 舊 view / 舊 ACL，或仍留有 `ir_module_module` 模組登記，需以維運腳本清理。

**原因**：
- 可消除 Odoo 升級時的 registry warning
- 避免後續開發者誤判 `dms_catalog` 仍存在
- 避免畫面繼續出現「產品管理 / 價目管理 / 產品目錄」等舊頂層入口
- 將「模組已刪除」與「資料庫 metadata 已收尾」兩件事真正對齊

**限制**：
- 只清理 `dms.product.template`、`dms.product.sku`、`dms.price.version`、`dms.price.line`、`dms.installment.rule`、`dms.installment.rule.line`、`dms.fee.type`、`dms.installment.rule.fee`
- `dms_product` / `dms_pricelist` 的共享模型只可移除舊 xmlid，不得刪到已由 `dms_sale` 接手的 `ir.model` / `ir.model.fields`

---

### D10：文件視 `014-module-removal` 為最新真相來源

**決策**：`README`、`SETUP`、`USER_MANUAL`、`ERD`、roadmap 及受影響 spec 必須改寫為「產品/價目已整併進 `dms_sale`」的描述；`013-dms-catalog` 整個目錄則自 repo 移除，不再保留獨立規格入口。

**原因**：目前最大的風險不是程式碼不能跑，而是文件仍指向舊架構，會直接誤導後續開發與操作。

---

## 未決問題

1. **生產環境卸載順序**：若生產環境已安裝三個被移除的模組，需確認卸載順序（catalog → pricelist → product）與資料備份策略，此須由專案負責人確認後才能在生產環境執行。
2. **dms_report / dms_report_virtual 是否有直接 SQL 或程式碼引用這些模型**：需在執行前確認，spec 完成後執行時會補查。
