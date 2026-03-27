# 013-dms-catalog — 任務分解（04-tasks）

## Task 清單

> **狀態說明**：✅ 已完成（已安裝並驗證）、⬜ 未完成（需本輪實作）

### T1：建立模組骨架（✅ 已完成）
- [ ] 建立 `addons/dms_catalog/__init__.py`
- [ ] 建立 `addons/dms_catalog/__manifest__.py`
- [ ] 建立 `addons/dms_catalog/models/__init__.py`（匯入所有模型）

### T2：核心模型（✅ 已完成）
- [ ] `models/product_template.py`（`dms.product.template`，含 image.mixin、_sql_constraints）
- [ ] `models/product_sku.py`（`dms.product.sku`，含 unique constraint）

### T2-補：車系模型（⬜ 未完成 — OQ-1 新增）
- [ ] `models/product_series.py`（`dms.product.series`，含 SQL unique on brand_id+name）
- [ ] `views/product_series_views.xml`（List / Form）
- [ ] `security/ir.model.access.csv` 補充 `dms.product.series` 的 ACL 記錄
- [ ] 更新 `models/__init__.py` 匯入 `product_series`

### T3：定價模型（✅ 已完成）
- [ ] `models/price_version.py`（`dms.price.version`）
- [ ] `models/price_line.py`（`dms.price.line`，含 M2M installment_rule_ids）

### T4：分期規則模型（✅ 已完成）
- [ ] `models/installment_rule.py`（`dms.installment.rule`）
- [ ] `models/installment_rule_line.py`（`dms.installment.rule.line`）
- [ ] `models/fee_type.py`（`dms.fee.type`）
- [ ] `models/installment_rule_fee.py`（`dms.installment.rule.fee`）

### T5：搬移模型（✅ 已完成）
- [ ] `models/accessory.py`（來自 `dms_pricelist`）
- [ ] `models/ev_fee_schedule.py`（來自 `dms_pricelist`）
- [ ] `models/commission_rule.py`（來自 `dms_pricelist`）
- [ ] `models/kanban_config.py`（來自 `dms_product`，調整 model reference）

### T6：安全設定（✅ 已完成）
- [ ] `security/ir.model.access.csv`（所有新模型的 CRUD 設定）

### T7：預載資料（✅ 已完成）
- [ ] `data/fee_type_data.xml`（開辦費 OPEN、設定費 SETUP）

### T8：視圖（✅ 已完成）
- [ ] `views/product_template_views.xml`（List / Form / Kanban）
- [ ] `views/product_sku_views.xml`（List / Form）
- [ ] `views/price_version_views.xml`（List / Form 含 price_line embedded）
- [ ] `views/installment_rule_views.xml`（List / Form 含 rule_line & fee embedded）
- [ ] `views/fee_type_views.xml`（List / Form）
- [ ] `views/accessory_views.xml`
- [ ] `views/ev_fee_schedule_views.xml`
- [ ] `views/commission_rule_views.xml`
- [ ] `views/kanban_config_views.xml`
- [ ] `views/menu.xml`（主選單結構）

### T9：靜態資產（✅ 已完成）
- [ ] `static/src/css/product_kanban.css`（搬移並調整）
- [ ] `static/src/js/dms_catalog_column_limit.js`（搬移 dms_product 版本）
- [ ] `static/src/js/product_image_lightbox.js`（搬移）

### T10：安裝驗證（✅ 已完成）
- [ ] `make up` / `docker compose ps` 確認容器正常
- [ ] 登入 Odoo，安裝 `dms_catalog` 模組
- [ ] 確認所有模型與視圖無 ParseError / AccessError
- [ ] `make smoke` 通過

## 依賴關係

T1 → T2 → T2-補 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10（基礎）
T11、T12、T13 可並行（均依 T2-補 完成後執行）

### T11：標記 deprecated（⬜ 未完成 — OQ-7 新增）
- [ ] `addons/dms_product/__manifest__.py`：在 `description` 加入 `⚠️ DEPRECATED` 說明
- [ ] `addons/dms_pricelist/__manifest__.py`：在 `description` 加入 `⚠️ DEPRECATED` 說明

### T12：更新 `dms.product.template` 加入 series_id（⬜ 未完成 — OQ-1 新增）
- [ ] `models/product_template.py`：新增 `series_id` Many2one（`dms.product.series`）
- [ ] `models/product_template.py`：`brand_id` 改為 `related='series_id.brand_id'`，store=True

### T13：視圖修正（⬜ 未完成 — OQ-4/5 新增）
- [ ] `views/product_template_views.xml`：Form 移除圖片 avatar；List 欄位加入 `series_id`；Kanban 移除 avatar
- [ ] `views/menu.xml`：確認車系（product_series）子選單入口存在
