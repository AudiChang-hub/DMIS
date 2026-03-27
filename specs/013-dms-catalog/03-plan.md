# 013-dms-catalog — 實作計畫（03-plan）

## 目標

建立 `addons/dms_catalog/` 作為統一產品目錄與定價管理模組，完整取代 `dms_product` 與 `dms_pricelist`。

## 執行語境

- Odoo 16.0 Community
- Docker Compose 環境（`dmis-odoo-1`，DB: `dmis_dev`）
- 採用 SDD spec-first 流程，所有程式碼變更須依本計畫執行

## 目錄結構

```
addons/dms_catalog/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── product_series.py            # dms.product.series 【本輪新增】
│   ├── product_template.py          # dms.product.template
│   ├── product_sku.py               # dms.product.sku
│   ├── price_version.py             # dms.price.version
│   ├── price_line.py                # dms.price.line
│   ├── installment_rule.py          # dms.installment.rule
│   ├── installment_rule_line.py     # dms.installment.rule.line
│   ├── fee_type.py                  # dms.fee.type
│   ├── installment_rule_fee.py      # dms.installment.rule.fee
│   ├── accessory.py                 # dms.accessory（搬移）
│   ├── ev_fee_schedule.py           # dms.ev.fee.schedule（搬移）
│   ├── commission_rule.py           # dms.commission.rule（搬移）
│   └── kanban_config.py             # dms.kanban.product.config（搬移）
├── security/
│   └── ir.model.access.csv
├── data/
│   └── fee_type_data.xml            # 預載費用類型
├── views/
│   ├── product_series_views.xml     # 【本輪新增】
│   ├── product_template_views.xml
│   ├── product_sku_views.xml
│   ├── price_version_views.xml
│   ├── installment_rule_views.xml
│   ├── fee_type_views.xml
│   ├── accessory_views.xml
│   ├── ev_fee_schedule_views.xml
│   ├── commission_rule_views.xml
│   ├── kanban_config_views.xml
│   └── menu.xml
└── static/
    └── src/
        ├── css/
        │   └── product_kanban.css
        └── js/
            ├── dms_catalog_column_limit.js
            └── product_image_lightbox.js
```

## 實作順序

### Phase 1：骨架與核心模型

1. `__manifest__.py`（depends: `dms_core`，包含所有 data/views/security）
2. 車系模型：`product_series.py` 【本輪新增】
3. 核心模型：`product_template.py`、`product_sku.py`（加入 series_id）
4. 定價模型：`price_version.py`、`price_line.py`
5. 分期模型：`installment_rule.py`、`installment_rule_line.py`、`fee_type.py`、`installment_rule_fee.py`
6. 搬移模型：`accessory.py`、`ev_fee_schedule.py`、`commission_rule.py`、`kanban_config.py`

### Phase 2：安全設定

6. `security/ir.model.access.csv`：設定 catalog_manager / catalog_user 群組

### Phase 3：資料

7. `data/fee_type_data.xml`：預載開辦費、設定費

### Phase 4：視圖

8. 各模型的 List / Form 視圖
9. Kanban 視圖（`dms.product.template`）
10. 主選單 `menu.xml`

### Phase 5：靜態資產

11. 搬移 CSS/JS（從 `dms_product/static/` 複製並調整）

### Phase 6：安裝驗證

12. `make up` 重啟環境
13. `make smoke` 基本煙測

### Phase 7：標記 deprecated（OQ-7）

14. 在 `addons/dms_product/__manifest__.py` 的 `description` 欄位加入警告說明
15. 在 `addons/dms_pricelist/__manifest__.py` 的 `description` 欄位加入警告說明

> 標記格式：`⚠️ DEPRECATED：功能已整併至 dms_catalog，本模組待相依模組完成遷移後移除。`

## 風險與緩解

| 風險 | 緩解 |
|---|---|
| `dms_sale` 等舊依賴因 `dms.product` 不存在而報錯 | `dms_catalog` 與 `dms_product`/`dms_pricelist` 同時存在；遷移另排 |
| Kanban config JS 搬移後路徑錯誤 | 搬移時調整 `__manifest__.py` asset 路徑 |
| ACL 設定不完整導致 access denied | 對所有新模型補充 CSV 記錄 |
| 資料遷移腳本損壞既有資料 | 腳本以冪等方式設計，先在測試 DB 驗證 || `series_id` 為必填但現有 template 資料未有對應車系 | 陛遷移至 dms_catalog 前，`series_id` 設為 `required=False` 先容譐空就；正式 migrate 後再改為必填 |