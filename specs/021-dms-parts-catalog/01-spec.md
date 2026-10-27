# 021 dms_parts 零件目錄擴充規格

> 狀態：草稿
> 建立日期：2026-04-13
> 模組：`dms_parts`（擴充，非新建）

---

## 目標

將機車廠商 PDF 零件目錄反推進入系統，提供：
1. 車型/引擎號碼搜尋 → 進入爆炸圖目錄
2. 零件清單含即時庫存查詢
3. CSV 批次匯入 + PDF 自動轉圖工具
4. 連結 Odoo `stock`，支援手動入庫與庫存調整

---

## 架構說明

### 資料來源方向

```
廠商 PDF → 人工整理 CSV + 截圖 PNG → 匯入精靈 → Odoo
```

不依賴原廠資料庫推送，全部由經銷商手動/半自動建立。

---

## 模型規格

### 1. `dms.part`（既有，補強欄位）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `name` | Char | 零件名稱，必填 |
| `part_number` | Char | 料號（原廠/內部） |
| `category_id` | Many2one → `dms.part.category` | 分類 |
| `part_type` | Selection | **新增**：`vehicle_part`（車輛結構零件）/ `consumable`（耗材）/ `accessory`（精品/副廠） |
| `uom` | Char | 單位（個、組、瓶） |
| `cost_price` | Float | 進貨成本 |
| `list_price` | Float | **新增**：公告售價（建議零售價） |
| `product_id` | Many2one → `product.product` | **新增**：連結 Odoo 庫存商品 |
| `superseded_by_id` | Many2one → `dms.part`（自身） | **新增**：料號繼承（停產替代） |
| `active` | Boolean | 啟用，預設 True |
| `note` | Text | 備註 |

**`product_id` 的處理邏輯：**
- 建立 `dms.part` 時，若 `product_id` 為空，系統自動建立對應的 `product.product`
- `product.product` 設定：
  - `name` = `dms.part.name`
  - `default_code` = `dms.part.part_number`
  - `type` = `product`（可儲存產品，啟用庫存追蹤）
  - `uom_id` / `uom_po_id` = 個（`product.product_uom_unit`）

---

### 2. `dms.part.catalog`（新建）

一份零件目錄對應一個車型的一個版本（年式/設變）。

| 欄位 | 類型 | 說明 |
|---|---|---|
| `name` | Char | 目錄名稱，必填（如「UQ125DA 2025版」） |
| `template_id` | Many2one → `dms.product.template` | 對應車型，必填 |
| `engine_prefix` | Char | 引擎號碼前綴（如 `DD`），用於搜尋比對 |
| `frame_prefix` | Char | 車架號碼前綴（選填） |
| `setup_date` | Date | 設變日期（PDF 上的設計變更日期） |
| `active` | Boolean | 啟用，預設 True |
| `note` | Text | 備註 |
| `section_ids` | One2many → `dms.part.catalog.section` | 分區清單 |

---

### 3. `dms.part.catalog.section`（新建）

目錄中的一個分區（E01 蓋蓋、E02 節流組...）。

| 欄位 | 類型 | 說明 |
|---|---|---|
| `catalog_id` | Many2one → `dms.part.catalog` | 所屬目錄，必填 |
| `code` | Char | 分區代號（E01、E02、F01...），必填 |
| `name` | Char | 分區名稱（蓋蓋、節流組...），必填 |
| `category` | Selection | `engine`（引擎）/ `frame`（車架） |
| `diagram_image` | Binary | 爆炸圖（PNG/JPEG），從 PDF 截圖 |
| `diagram_filename` | Char | 圖檔名稱（供下載用） |
| `sequence` | Integer | 排序，預設 10 |
| `line_ids` | One2many → `dms.part.catalog.line` | 零件明細 |

---

### 4. `dms.part.catalog.line`（新建）

爆炸圖上每個零件的明細。

| 欄位 | 類型 | 說明 |
|---|---|---|
| `section_id` | Many2one → `dms.part.catalog.section` | 所屬分區，必填 |
| `seq_no` | Integer | 圖上的序號（1、2、3...） |
| `part_id` | Many2one → `dms.part` | 對應零件主檔，必填 |
| `part_number` | Char | 料號（從 `part_id` 自動帶入，可覆寫） |
| `name` | Char | 零件名稱（從 `part_id` 自動帶入，可覆寫） |
| `qty` | Float | 標準用量，預設 1 |
| `list_price` | Float | 公告售價（從 `part_id.list_price` 帶入，可覆寫） |
| `note` | Char | 備註（如「適用引擎號 DD000001~DD050000」） |

---

## 視圖規格

### 搜尋入口（Wizard）

- Model：`dms.part.catalog.search.wizard`（暫存模型）
- 欄位：
  - `engine_number`：Char（輸入引擎號碼，系統做前綴比對）
  - `template_id`：Many2one → `dms.product.template`（下拉選車型）
  - `section_category`：Selection（全部 / 引擎 / 車架）
- 按「查詢」→ 依條件開啟對應 catalog 的 Section Kanban view

### Catalog Section Kanban（圖二）

- 每張卡片顯示：分區代號（E01）+ 名稱 + 爆炸圖縮圖
- 依 `category` filter（引擎/車架/全部）
- 點卡片 → 進入 Section Form view

### Section Form view（爆炸圖 + 清單）

- 左半：`diagram_image` 大圖（widget="image"，寬 100%）
- 右半：`line_ids` tree view（seq_no / part_number / name / qty / list_price / 庫存量）
- 庫存量欄位：`part_id.product_id` 的 `qty_available`（compute，不存庫）

### 車型圖片頁（圖三）

- 使用 `dms.product.template` 的現有 Form view 擴充（視圖繼承）
- 加入 `catalog_ids` One2many tab 頁籤

---

## 選單結構

```
零件管理（頂層）
  ├── 零件查詢（搜尋 Wizard）
  ├── 零件目錄（catalog tree/form）
  ├── 零件清單（dms.part tree/form，已有）
  └── 零件分類（dms.part.category，已有）
```

---

## 權限（ACL）

| 名稱 | 模型 | 群組 | CRUD |
|---|---|---|---|
| `access_dms_part_catalog_all` | `dms.part.catalog` | `base.group_user` | CRUD |
| `access_dms_part_catalog_section_all` | `dms.part.catalog.section` | `base.group_user` | CRUD |
| `access_dms_part_catalog_line_all` | `dms.part.catalog.line` | `base.group_user` | CRUD |
| `access_dms_part_catalog_search_wizard` | `dms.part.catalog.search.wizard` | `base.group_user` | CR |

---

## M6：匯入工具

### M6-A CSV 批次匯入精靈

CSV 格式（UTF-8）：

```
catalog_name,section_code,section_name,section_category,seq_no,part_number,part_name,uom,qty,list_price
UQ125DA 2025版,E01,蓋蓋,engine,1,17510-AAA-000,汽缸頭蓋,個,1,850
UQ125DA 2025版,E01,蓋蓋,engine,2,93892-05012-08,螺栓,個,4,25
```

精靈邏輯：
1. 對應 `catalog_name` 找（或建立）`dms.part.catalog`
2. 對應 `section_code` 找（或建立）`dms.part.catalog.section`
3. 對應 `part_number` 找既有 `dms.part`，找不到則建立（同步建 `product.product`）
4. 建立 `dms.part.catalog.line`

### M6-B PDF 轉圖腳本

- 路徑：`scripts/pdf_to_diagrams.py`
- 依賴：`PyMuPDF`（`pip install pymupdf`）
- 輸入：PDF 路徑、輸出目錄
- 輸出：每頁一個 PNG，命名為 `E01.png`、`E02.png`...（依頁序）
- 解析度：150 DPI（足夠清晰且檔案不過大）

---

## 未來擴充（本期不做）

- M3-E 設變引擎號碼區間（`engine_from`/`engine_to`）
- M4-A 目錄版本比對
- M5-C 價格生效日期
- M8-B 含爆炸圖的 QWeb 報表
- Kit 零件
- 維修工單整合接口（`catalog_line_id` 預留欄位）
