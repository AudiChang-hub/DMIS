# 規格（01-spec）

此檔為 DMS Core 的規格文件（繁體中文）。

功能概述：
- 提供 `dms.dealer`（車行）模型，含負責人/店長/同負責人同步、車行類型與多品牌選擇。

欄位定義（繁體中文）：

### 基本識別
- `code`（車行代碼）：Char，必填、唯一，用於識別與搜尋；若未填入則自動產生（type_code + YYMMDD）。
- `name`（車行名稱）：Char，必填，作為主要名稱顯示。
- `short_name`（簡稱）：Char，可選，不顯示於列表。
- `active`（啟用）：Boolean，預設 True。

### 人員
- `owner_name`（負責人）：Char，必填，顯示於基本資料區塊。
- `store_manager`（店長）：Char，必填；當 `manager_same_as_owner=True` 時，自動同步為負責人姓名。
- `manager_same_as_owner`（同負責人）：Boolean，預設 False；勾選後即時帶入 `owner_name` 至 `store_manager`（透過 `@api.onchange` 實作），`create/write` 時亦防呆同步。

### 分類
- `store_type_id`（車行類型）：Many2one → `dms.dealer.type`，可選擇型別（如加盟、直營、代理、合作）。
- `brand_ids`（品牌）：Many2many → `dms.brand`，多品牌車行支援，使用 `many2many_tags` widget；品牌主檔可在 `DMS → 品牌管理` 維護。

### 聯絡資訊
- `phone_1`、`phone_2`（電話1/2）：Char。
- `mobile`（手機）、`mobile_fax`（手機/傳真）：Char。
- `email`（電子郵件）：Char。
- `address`（地址）：Text。
- `city`（縣市）：Char，不顯示於列表。

### 價格表/排車
- `sym_price_list`、`suzuki_price_list`：Selection（無/油車/電車/全部）。
- `sym_dispatch_capacity`、`suzuki_dispatch_capacity`：Integer，不可為負數。

### 其他
- `line_group`（有 LINE 群組）：Boolean。
- `holiday_gift`（年節送禮）：Boolean。
- `tags`：Many2many → `dms.dealer.tag`。
- `note`（備註）：Html。

索引/唯一性：
- `code` 欄位需唯一，透過資料庫約束 (`_sql_constraints`) 強制。

搜尋需求：
- 支援以 `code`、`name`、`short_name`、`phone_1`、`phone_2`、`mobile`、`mobile_fax` 搜尋。

介面：
- tree、form、search view；選單位置：`DMS` → `車行`。
- tree view 顯示：`code`、`name`、`owner_name`、`store_manager`、`phone_1`、`mobile`、`store_type_id`、`brand_ids`（不含簡稱、縣市）。
- form view 分為頁籤：基本資料（含人員區塊）、聯絡資訊、價格表/群組、進階。
- 點進明細預設以編輯模式開啟（`form_view_initial_mode: edit`）。
- 品牌管理選單：`DMS → 品牌管理`。
- 車行類型管理選單：`DMS → 車行類型管理`。

### 輔助模型
- `dms.brand`：品牌主檔，Char `name`（必填）。ACL：manager 全讀寫，一般使用者唯讀。
- `dms.dealer.type`：車行類型，`name`（必填）、`code`（短碼）。