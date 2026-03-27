# 03 — Plan：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## 1. 實作策略

採用「新增 wizard，不改主模型語意」方式：

1. 在 `dms_visit/wizard/` 新增 `visit_bulk_create_wizard.py`
2. 以主選單提供批次建立入口
3. 單筆拜訪表單維持原有欄位順序與版面
4. 由 wizard 一次建立多筆 `dms.visit`

## 2. 修改範圍

### 新增

- `addons/dms_visit/wizard/visit_bulk_create_wizard.py`
- `addons/dms_visit/wizard/visit_bulk_create_wizard_views.xml`

### 修改

- `addons/dms_visit/__manifest__.py`
- `addons/dms_visit/__init__.py`
- `addons/dms_visit/wizard/__init__.py`
- `addons/dms_visit/models/visit.py`
- `addons/dms_visit/views/visit_views.xml`
- `addons/dms_visit/security/ir.model.access.csv`
- `addons/dms_visit/tests/test_visit.py`
- `docs/USER_MANUAL.md`

## 3. 視圖策略

- 單筆表單保留 `dealer_id`
- 增加一個可從 action/menu 開啟的 `批次建立拜訪` modal
- 行事曆雙擊開啟的表單不嵌入批次建立按鈕

## 4. 權限策略

- wizard 對 `group_dms_visit_user` 與 `group_dms_visit_admin` 開放建立
- wizard 最終仍走 `dms.visit.create()`，不做 sudo 繞過

## 5. 測試策略

至少新增：

- wizard 可一次為多個車行建立多筆 `dms.visit`
- 每筆建立的 `visitor_id`、`purpose_id`、`visit_date` 一致
- 不影響既有單筆建立測試

## 6. 回歸驗證

- `dms_visit` 模組升級
- `dms_visit` 單元測試
- `bash scripts/smoke_odoo.sh`
- 拜訪清單 / 拜訪行事曆仍可正常開啟
