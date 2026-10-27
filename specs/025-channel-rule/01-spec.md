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
- 「店內員工」（特定員工兼營）暫保留 `dname ~ '文傑'` 判斷。
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
| 10 | 光陽車行 | `鑫輝\|特色\|捷盛\|祥銘\|達能\|立野\|名豐\|弘安` | 光陽 |
| 20 | 三陽車行 | `永湛\|宏堂\|見元\|萬全\|百福\|昌億\|風火輪\|皇韋\|成峰\|百呈\|明達\|東永\|嘉順` | 三陽 |
| 30 | 山葉車行 | `馳機\|天佑\|旭昇\|宏偉\|尚勁\|德新\|凱弘\|鋐亞\|群陽\|德旺\|駿翔\|輪友\|極昇\|奕鈞\|良澄\|岩谷\|昌勝\|松祥\|金利富\|泳辰\|源泰\|旗成\|嘉仁\|金泰發\|日信\|名傑\|鈞鴻` | 山葉 |
| 40 | 一般車行 A | `明毅\|鑨來\|阿松\|佳峰\|信益\|鼎勝\|上慶\|合聰\|宏昌\|湖州\|鉉豐` | 一般車行 |
| 41 | 一般車行 B | `彗星` | 一般車行 |
| 50 | 台鈴車行 | `明輝\|新隆\|旭昶\|欣益\|富順\|運豐` | 台鈴 |
| 60 | 睿能車行 | `士辰\|北野電能\|北野` | 睿能 |
| 70 | 網路平台-關鍵字 | `pc\|momo\|yahoo\|燦坤\|小樹購\|百利市\|friday\|蝦皮` | 網路平台 |

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

