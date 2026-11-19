# Spec 025 — 銷售渠道與品牌規則重構

## 背景

`ds.sales.report` SQL view 目前以 dealer name 的 hardcoded regex 判斷下列 4 個欄位：

- `energy_type`（能源型式）有 product 主檔但又寫了一份 regex 兜底
- `sales_source`（銷售來源）以 dname regex 區分「馭盛/網路平台/店內員工/車行」
- `sales_type`（銷售類型）以 dname regex 區分「本店/網路平台/車行」
- `brand_type`（品牌分類）以 dname 列舉約 80 家車行對應 8 種品牌

每新增車行就要改 Python 原始碼 → 維運成本高。

## 目標

延續 spec 024 的設計理念，將判斷邏輯改為 UI 可維護的資料表 + 既有 dealer 主檔欄位。

## 變更內容

### 1. `energy_type`

- 移除 dname/pname 兜底 regex；完全以 `dms_product.energy_type` 為準。
- 若 product 未設定，預設 `油車`。

### 2. `sales_source` / `sales_type`

- 新增 `LEFT JOIN dms_dealer d ON d.id = so.dealer_id`
- 新增 `LEFT JOIN dms_store_type st ON st.id = d.store_type_id`
- 取 `st.name` 直接作為「網路平台」判斷依據。
- 「馭盛/本店」維持以 `display_dealer_name = ''` 判斷。
- 「店內員工」（特定員工兼營）暫保留 `dname ~ '員工甲'` 判斷。
- `display_dealer_name = '中古車'` 視為 `馭盛` 體系資料列：`dealer` / `dealer_not_null` 應正規化為 `馭盛`，`sales_source` 應為 `馭盛`，`sales_type` 應為 `本店`，且車行縣市/區域應 fallback 使用 `馭盛` 主檔地址。
- `display_dealer_name IN ('朋友推薦', '代申請補助')` 視為店內引薦/代辦單，`sales_source` 歸入 `店內員工`、`sales_type` 歸入 `本店`，不得落入 `車行`。
- `display_dealer_name IN ('朋友推薦', '代申請補助')` 的顯示欄位需同步正規化為 `dealer='馭盛'`、`dealer_not_null='馭盛'`，並以 `dms_dealer.name='馭盛'` 的主檔地址解析車行縣市/區域，避免報表在車行維度與區域維度出現不一致。

### 3. `brand_type`

新增模型 `dms.dealer.brand.rule`，欄位與 `dms.motor.type.rule` 同構：

| 欄位 | 型別 | 說明 |
|------|------|------|
| name | Char (required) | 規則名稱 |
| sequence | Integer (default 10) | 比對順序 |
| pattern | Char (required) | 套用於 dealer 名稱的 POSIX 正則（不分大小寫）|
| result | Char (required) | 品牌名稱（光陽/三陽/山葉/台鈴/睿能/一般車行/...）|
| active | Boolean (default True) | 啟用 |
| note | Text | 備註 |

`ds.sales.report.init()` 動態組合 `brand_type` CASE：

1. `dname = ''` → `馭盛網推`
2. `store_type.name = '網路平台'` → `網路平台`
3. `dname ~ '中古車'` → `中古車`
4. 套用啟用中的規則（依 sequence）→ `result`
5. 否則 → `dname`（fallback 顯示原車行名稱）

### 預設規則（8 條）

| seq | name | pattern | result |
|-----|------|---------|--------|
| 10 | 光陽車行 | `車行01\|車行02\|車行03\|車行04\|車行05\|車行06\|車行07\|車行08` | 光陽 |
| 20 | 三陽車行 | `永湛\|車行09\|車行10\|車行11\|車行12\|車行13\|車行14\|車行15\|車行16\|車行17\|車行18\|車行19\|車行20` | 三陽 |
| 30 | 山葉車行 | `車行21\|車行22\|車行23\|車行24\|車行25\|車行26\|車行27\|車行28\|車行29\|車行30\|車行31\|車行32\|車行33\|車行34\|車行35\|車行36\|車行37\|車行38\|車行39\|車行40\|車行41\|車行42\|車行43\|車行44\|車行45\|車行46\|車行47` | 山葉 |
| 40 | 一般車行 A | `車行48\|車行49\|車行50\|車行51\|車行52\|車行53\|車行54\|車行55\|車行56\|車行57\|車行58` | 一般車行 |
| 41 | 一般車行 B | `車行59` | 一般車行 |
| 50 | 台鈴車行 | `車行60\|車行61\|車行62\|車行63\|車行64\|車行65` | 台鈴 |
| 60 | 睿能車行 | `車行66\|車行67\|車行67` | 睿能 |
| 70 | 網路平台-關鍵字 | `平台D\|平台C\|平台A\|平台F\|平台G\|平台B\|平台E\|平台H` | 網路平台 |

## UI

- 選單：報表分析 → **車行品牌規則**
- list editable + form + 「重新套用規則」按鈕

## 權限

- `base.group_user`：唯讀
- `base.group_system`：完整 CRUD

## 驗證

1. `ds_sales_report` 4 個欄位（energy_type / sales_source / sales_type / brand_type）的分佈
   與重構前一致（容許 ±1% 誤差，主要來自 store_type JOIN 取代 regex）。
2. UI 新增規則 → 自動重建 view → 對應車行立即改變 brand_type。
3. 既有 metabase dashboards 不受影響。
4. `display_dealer_name IN ('朋友推薦', '代申請補助')` 的資料在 `ds_sales_report` 中應顯示 `sales_source='店內員工'`、`sales_type='本店'`。
5. `display_dealer_name IN ('朋友推薦', '代申請補助')` 的資料在 `ds_sales_report` 中不應再顯示原始 dealer 字樣。
6. `display_dealer_name IN ('朋友推薦', '代申請補助')` 的資料在 `ds_sales_report` 中應顯示 `dealer='馭盛'`，且 `dealer_region_city` / `dealer_region_district` 應取 `馭盛` 主檔地址。
7. `display_dealer_name = '中古車'` 的資料在 `ds_sales_report` 中應顯示 `dealer='馭盛'`、`sales_source='馭盛'`、`sales_type='本店'`，且 `dealer_region_city` / `dealer_region_district` 應取 `馭盛` 主檔地址。

