# 013-dms-catalog — 任務分解（04-tasks）

## Task 清單

### T1：建立模組骨架
- [ ] 建立 `addons/dms_catalog/__init__.py`
- [ ] 建立 `addons/dms_catalog/__manifest__.py`
- [ ] 建立 `addons/dms_catalog/models/__init__.py`（匯入所有模型）

### T2：核心模型
- [ ] `models/product_template.py`（`dms.product.template`，含 image.mixin、_sql_constraints）
- [ ] `models/product_sku.py`（`dms.product.sku`，含 unique constraint）

### T3：定價模型
- [ ] `models/price_version.py`（`dms.price.version`）
- [ ] `models/price_line.py`（`dms.price.line`，含 M2M installment_rule_ids）

### T4：分期規則模型
- [ ] `models/installment_rule.py`（`dms.installment.rule`）
- [ ] `models/installment_rule_line.py`（`dms.installment.rule.line`）
- [ ] `models/fee_type.py`（`dms.fee.type`）
- [ ] `models/installment_rule_fee.py`（`dms.installment.rule.fee`）

### T5：搬移模型
- [ ] `models/accessory.py`（來自 `dms_pricelist`）
- [ ] `models/ev_fee_schedule.py`（來自 `dms_pricelist`）
- [ ] `models/commission_rule.py`（來自 `dms_pricelist`）
- [ ] `models/kanban_config.py`（來自 `dms_product`，調整 model reference）

### T6：安全設定
- [ ] `security/ir.model.access.csv`（所有新模型的 CRUD 設定）

### T7：預載資料
- [ ] `data/fee_type_data.xml`（開辦費 OPEN、設定費 SETUP）

### T8：視圖
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

### T9：靜態資產
- [ ] `static/src/css/product_kanban.css`（搬移並調整）
- [ ] `static/src/js/dms_catalog_column_limit.js`（搬移 dms_product 版本）
- [ ] `static/src/js/product_image_lightbox.js`（搬移）

### T10：安裝驗證
- [ ] `make up` / `docker compose ps` 確認容器正常
- [ ] 登入 Odoo，安裝 `dms_catalog` 模組
- [ ] 確認所有模型與視圖無 ParseError / AccessError
- [ ] `make smoke` 通過

## 依賴關係

T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10

（每個 phase 須前序完成後才執行）
