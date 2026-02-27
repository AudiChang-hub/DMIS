# 規格（01-spec）

此檔為 DMS Core 的規格文件（繁體中文）。

功能概述：
- 提供 `dms.dealer`（車行）模型，含負責人/店長/同負責人同步、車行類型與多品牌選擇、四個品牌價格表開關、排車容量限制。

## 主要模型

### `dms.dealer`（車行）

#### 基本識別
- `code`（車行代碼）：Char，必填、唯一；未填則自動產生（type_prefix + YYMMDD）。
- `name`（店名）：Char，必填，string 顯示為「店名」。
- `active`（啟用）：Boolean，預設 True。

#### 人員
- `owner_name`（負責人）：Char，必填。
- `store_manager`（店長）：Char，**可空**（非 required）。
- `manager_same_as_owner`（同負責人）：Boolean，預設 False。
  - 勾選時：`@api.onchange` 即時將 `owner_name` 帶入 `store_manager`；UI 上 `store_manager` 顯示為 readonly。
  - 取消勾選時：不自動清空 `store_manager`，保留現有值。
  - `create()/write()` 防呆：若勾選且未提供 `store_manager`，自動補入 `owner_name`。

#### 分類
- `store_type_id`（車行類型）：Many2one → `dms.store_type`，可選，可在 `DMS → 車行類型管理` 維護。
- `brand_ids`（品牌）：Many2many → `dms.brand`，關聯表 `dms_dealer_brand_rel`（column1=dealer_id, column2=brand_id），使用 `many2many_tags` widget。

#### 聯絡資訊
- `phone_1`（電話1）、`phone_2`（電話2）：Char，可空。
- `mobile`（手機）、`mobile_fax`（手機/傳真）：Char，可空。
- `email`（電子信箱）：Char，可空，string 顯示為「電子信箱」。
- `address`（地址）：Text，可空。

#### 品牌價格表（Boolean，default False）
- `sym_gas_price_list`：三陽油車價格表
- `sym_ev_price_list`：三陽電車價格表
- `suzuki_gas_price_list`：台鈴油車價格表
- `suzuki_ev_price_list`：台鈴電車價格表

#### 排車容量
- `sym_dispatch_capacity`（三陽排車容量）：Integer，不可為負（`@api.constrains` + ValidationError）。
- `suzuki_dispatch_capacity`（台鈴排車容量）：Integer，不可為負。

#### 群組/活動（Boolean，default False）
- `line_group`（LINE群組）
- `holiday_gift`（年節送禮）

#### 備註
- `note`（備註）：Text，可空。

#### name_get
- 有 code：`[code] 店名`
- 無 code：`店名`

#### name_search（模糊搜尋欄位）
`code`、`name`、`phone_1`、`mobile`、`owner_name`、`store_manager`、`address`、`brand_ids.name`

---

### `dms.brand`（品牌主檔）
- `name`（品牌名稱）：Char，必填，唯一。
- `active`（啟用）：Boolean，預設 True。
- ACL：所有使用者讀寫（內部人員系統，全部開放）。

### `dms.store_type`（車行類型主檔）
- `name`（類型名稱）：Char，必填，唯一。
- `active`（啟用）：Boolean，預設 True。
- ACL：所有使用者讀寫（全部開放）。

---

## 介面規格

### tree view（`dms.dealer`）

#### 欄位選擇器規格
Odoo list view 右上角欄位選擇器需包含**所有**車行業務欄位，使用者可自由勾選顯示或隱藏任意欄位。實作方式：tree view 內所有欄位必須加上 `optional` 屬性（`optional="show"` 或 `optional="hide"`）。

- **預設顯示** (`optional="show"`，共 9 欄，≤ 15 軟性上限)：  
  `code`（車行代碼）、`name`（店名）、`owner_name`（負責人）、`store_manager`（店長）、`phone_1`（電話1）、`mobile`（手機）、`store_type_id`（車行類型）、`brand_ids`（品牌，widget=many2many_tags）、`active`（啟用）

- **預設隱藏** (`optional="hide"`，可在選擇器勾選後顯示)：  
  `phone_2`（電話2）、`mobile_fax`（手機/傳真）、`email`（電子信箱）、`sym_gas_price_list`（三陽油車價格表）、`sym_ev_price_list`（三陽電車價格表）、`suzuki_gas_price_list`（台鈴油車價格表）、`suzuki_ev_price_list`（台鈴電車價格表）、`sym_dispatch_capacity`（三陽排車容量）、`suzuki_dispatch_capacity`（台鈴排車容量）、`line_group`（LINE群組）、`holiday_gift`（年節送禮）

不顯示（不加入 tree view）：`short_name`、`city`、`district`、`phone`（舊）、`contact_name`（舊）等已廢棄欄位。

### form view（`dms.dealer`）
4 個 notebook 頁籤：
1. **基本資料**：店名、負責人、同負責人 checkbox + 店長（勾選時 readonly）、地址、品牌（tags）、車行類型、啟用、備註。
2. **聯絡資訊**：電話1、電話2、手機、手機/傳真、電子信箱。
3. **價格表／群組**：四個 Boolean 價格表 + LINE群組 + 年節送禮。
4. **排車容量**：三陽排車容量、台鈴排車容量（提示：不得為負）。

### search view（`dms.dealer`）
搜尋欄位：店名、負責人、店長、電話1、手機、地址、品牌。
Filters：啟用、年節送禮、LINE群組、三陽油車價格表、三陽電車價格表、台鈴油車價格表、台鈴電車價格表。

### 選單結構
- DMS（根選單）
  - 車行 → 列表 / 新增
  - 品牌管理
  - 車行類型管理

### Action 設定
- `action_dealer`：加入 `context={'form_view_initial_mode': 'edit'}`

---

## 安全規則
所有 DMS 模型（`dms.dealer`、`dms.brand`、`dms.store_type`）：perm_read/write/create/unlink 全 1（無群組限制，所有登入使用者皆可操作）。