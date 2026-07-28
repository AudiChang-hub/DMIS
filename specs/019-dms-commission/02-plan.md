# 019-dms-commission 實作計畫（02-plan）

## 實作順序

依賴關係由底層往上，共分 **6 個里程碑**。

---

## Milestone 1：模組骨架

1. 建立 `addons/dms_commission/` 目錄結構
2. 建立 `__manifest__.py`（依賴 dms_core, dms_product, dms_sale）
3. 建立 `__init__.py`（空）
4. 建立 `models/__init__.py`、`views/`、`security/` 目錄
5. 建立 `security/ir.model.access.csv`（含全部 model ACL）
6. 安裝模組，確認可正常載入

---

## Milestone 2：傭金規則模型

1. 建立 `models/commission_rule.py`（`dms.commission.rule`）
2. 建立 `models/commission_dealer_rule.py`（`dms.commission.dealer.rule`）
3. 建立 `models/commission_volume_rule.py`（`dms.commission.volume.rule`）
4. 建立對應 XML views（tree/form/action/menu）
5. 升級模組，確認 CRUD 正常

---

## Milestone 3：激勵設定模型

1. 建立 `models/incentive_type.py`（`dms.incentive.type`）
2. 建立 `models/incentive_rule.py`（`dms.incentive.rule`）
3. 建立對應 XML views
4. 升級模組，確認 CRUD 正常

---

## Milestone 4：結案機制（核心）

1. 建立 `models/commission_record.py`（`dms.commission.record`）
2. 建立 `models/incentive_delivery.py`（`dms.incentive.delivery`）
3. 建立 `models/sale_order_ext.py`（`_inherit = 'sale.order'`）
   - 加入 `is_closed`, `closed_date`, `commission_record_id`
   - 實作 `action_close_order()` / `action_reopen_order()`
   - 實作台數重算邏輯 `_recompute_volume_bonus(dealer_id, closed_month)`
4. 建立 `views/sale_order_ext_views.xml`（加入結案/撤銷按鈕）
5. 建立 `views/commission_record_views.xml`
6. 建立 `views/incentive_delivery_views.xml`
7. 升級模組，驗證結案 → 計算 → 撤銷 → 重算流程

---

## Milestone 5：報表

1. 建立 `models/report_monthly.py`（`dms.commission.monthly.report` TransientModel）
2. 建立 `models/report_summary.py`（`dms.commission.summary.report` TransientModel）
3. 建立 wizard views（月份/日期區間輸入）
4. 實作 Excel 匯出（`xlsxwriter` 或 `report_xlsx`）
5. 加入報表選單

---

## Milestone 6：權限整合與 demo 資料

1. 建立 `security/dms_commission_security.xml`（群組定義）
2. 在 `user_management` 加入群組勾選（`_inherit`）
3. 建立 `data/demo_commission_rules.xml`（示範資料）
4. git commit + push，更新 CHANGELOG.md

---

## 技術注意事項

- **台數重算**：`_recompute_volume_bonus` 核心是 `search([('dealer_id','=',dealer_id), ('closed_month','=',month), ('state','=','active')])` 後批次 write，需注意效能（目前資料量小，可接受）
- **formula_type 擴充**：使用 `Selection` + 獨立 `compute_amount(base)` 方法，新增公式只需加 selection 項目與對應 if/elif
- **撤銷結案限制**：已 `delivered` 的 `incentive.delivery` 不強制作廢（只把 `pending` 設為 voided），保留已核銷記錄
- **Excel 匯出**：優先使用 `xlsxwriter` + binary attachment，避免額外依賴 `report_xlsx` 外部模組
