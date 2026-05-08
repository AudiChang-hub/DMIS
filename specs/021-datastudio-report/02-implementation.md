# DataStudio 報表復刻 — 實作規格

> **對應需求**：`specs/021-datastudio-report/01-datastudio-extraction.md`
> **模組名稱**：`dms_report_ds`
> **實作時間**：2026-04-16

---

## 一、目標

將 DataStudio 報表（SUZUKI銷售統計，22 頁）復刻至 DMIS 環境，分兩階段：

1. **Odoo 側**：建立 SQL View 模型 `ds.sales.report`，包含所有 17 個計算欄位，提供 Odoo 原生 Pivot / Graph / Tree 視圖。
2. **Metabase 側**：在 Docker 環境加入 Metabase 服務，連接同一 PostgreSQL 資料庫讀取 `ds_sales_report` View，建立 22 頁 Dashboard。

---

## 二、技術設計

### 2.1 模組結構

```
addons/dms_report_ds/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── ds_sales_report.py      # SQL View model（_auto=False）
├── security/
│   └── ir.model.access.csv
└── views/
    └── ds_report_views.xml      # Pivot / Graph / Tree / Search / Menu
```

### 2.2 SQL View 設計

- 名稱：`ds_sales_report`
- 來源表：`dms_sale_order` LEFT JOIN `dms_product`、`dms_commission_record`
- 篩選條件：`active = True`（含 draft / confirmed，排除已封存）
- 所有 17 個 DataStudio fx 計算欄位均在 SQL 層完成（不使用 Odoo stored compute）
- 使用 CTE 統一別名，避免 COALESCE 重複

### 2.3 關鍵欄位對照（DataStudio → SQL View）

| DataStudio 欄位 | SQL 欄位 | 來源 |
|----------------|----------|------|
| age | `age` | `EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM birthday_ad)` |
| AgeGroup | `age_group` | CASE WHEN 區間 |
| BasicBonus | `basic_bonus` | `friendly_bonus_out + first_sale_bonus + dealer_comm_out` |
| BrandType | `brand_type` | Dealer regex 分類 |
| Dealer_NotNull | `dealer_not_null` | COALESCE + UPPER + TRIM |
| Energy Type | `energy_type` | `dms_product.energy_type` + Model 名稱 fallback |
| ModelColor | `model_color` | `model || '_' || car_color` |
| MotorType | `motor_type` | Model regex 分類 |
| NumberOfUnitsBonus | `volume_bonus` | `dms_commission_record.volume_bonus` |
| TotalBonus | `total_commission` | `dms_commission_record.total_commission` |
| Region | `region` | Address regex 擷取 |
| Region_District | `region_district` | Address regex 擷取（含縣市） |
| Dealer_Region_District | `dealer_region_district` | `dms_dealer.address` regex 擷取（含縣市，代表車行區域） |
| Sales Source | `sales_source` | Dealer regex 分類 |
| SalesType | `sales_type` | Dealer regex 分類 |
| sex | `sex` | `SUBSTRING(id_number, 2, 1)` |
| SortLicenseDate | `sort_license_date` | `COALESCE(registration_date, '9999-12-31')` |

### 2.4 Docker / Metabase

- 新增 `metabase` 服務至 `docker-compose.yml`
- Metabase 使用內建 H2 儲存自身 metadata（volume: `metabase_data`）
- 資料來源：連接同一 `db` 容器的 `dmis_dev` 資料庫
- 新增 `.env` 變數：`METABASE_PORT=3000`

---

## 三、依賴

- `dms_sale`（dms.sale.order、dms.product、dms.product.color）
- `dms_commission`（dms.commission.record）

---

## 四、安全

- `ds.sales.report` 為唯讀 SQL View
- 內部使用者（base.group_user）：讀取權限
- 管理者（dms_sale.group_sale_manager）：完整讀取權限

---

## 五、驗證步驟

```bash
# 1. 啟動服務
make up

# 2. 安裝模組
docker compose exec odoo odoo -d dmis_dev -i dms_report_ds --stop-after-init

# 3. 重啟 Odoo
docker compose restart odoo

# 4. 確認服務正常
docker compose ps
make smoke

# 5. 確認 SQL View 存在
docker compose exec db psql -U odoo dmis_dev -c "\dv ds_sales_report"

# 6. 確認有資料
docker compose exec db psql -U odoo dmis_dev -c "SELECT count(*) FROM ds_sales_report"

# 7. 啟動 Metabase
docker compose up -d metabase

# 8. 瀏覽 Metabase
# http://localhost:3000 → 設定資料來源 → host=db, port=5432, db=dmis_dev, user=odoo, password=odoo
```
