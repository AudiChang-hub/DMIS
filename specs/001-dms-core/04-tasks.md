# 任務清單 (04-tasks)

## 完整車行需求實作清單

### Step 1 — Specs
- [ ] 01-spec.md — 完整欄位定義與視圖規格
- [ ] 02-clarify.md — 假設與决策
- [ ] 03-plan.md — 實作步驟
- [ ] 04-tasks.md — 任務清單
- [ ] 05-acceptance.md — 驗收條件

### Step 2 — Models
- [ ] `dealer.py`: 更新 `name` label/`store_manager`/`note`/`email`/`address`/`brand_ids`/`store_type_id`/Boolean price fields/`name_search`
- [ ] `brand.py`: 建立 `dms.brand` model
- [ ] `store_type.py`: 建立 `dms.store_type` model
- [ ] `__init__.py`: import brand, store_type, dealer

### Step 3 — Views
- [ ] `dealer_views.xml`: 4分頁表單 + 新清單 + 搜尋 + action
- [ ] `dealer_views.xml`：tree view 欄位選擇器全面化（所有業務欄位加 `optional` 屬性；預設顯示 ≤15；其餘欄位預設隱藏但可選）
- [ ] `dealer_views.xml`：tree view 補齊缺漏欄位 `address`（地址）、`note`（備註）為 `optional="hide"`
- [ ] `brand_views.xml`: 新增 tree/form/action/menu
- [ ] `store_type_views.xml`: 新增 tree/form/action/menu
- [ ] `static/src/js/dms_dealer_column_limit.js`：新增前端 JS patch，hardcode 最多顯示 15 欄（超過時阻止 + warning notification），僅對 `dms.dealer` list view 生效
- [ ] `__manifest__.py`：在 `web.assets_backend` 補充 JS 資產宣告
- [ ] `store_type_views.xml`: 新增 tree/form/action/menu

### Step 4 — Security / Seed / Manifest
- [ ] `ir.model.access.csv`: 全部開放，新增 store_type
- [ ] `seed.xml`: 新欄位 引用
- [ ] `__manifest__.py`: 新增 brand/store_type views 檔案

### Step 5 — Tests
- [ ] `test_dealer.py`: 新增 Boolean 價格欄位測試，更新旧氋設現 store_manager 非必填

### Step 6 — Upgrade
- [ ] `docker compose restart odoo`
- [ ] CLI upgrade `dms_core` 在 `dmis_dev`
- [ ] `make smoke` 通過
- 更新 `views/dealer_views.xml`：tree/form/search 支援欄位顯示與搜尋（code/name/phone）。
- 更新 `security/ir.model.access.csv`（確認一般使用者可讀寫）。
- 更新 `specs`（01/04/05）與 `README` 的安裝說明。
- 在本地執行 `make up`、`make smoke` 驗證。

## UI/UX 改善任務（feat/dealer-uiux）

### 步驟 2：dealer 模型 + view 改善
- `addons/dms_core/models/dealer.py`：
  - 確認 `owner_name`、`store_manager`、`manager_same_as_owner` 已存在（已有）。
  - 補強 `@api.onchange` 與 create/write 防呆邏輯（已有，確認完整）。
- `addons/dms_core/views/dealer_views.xml`：
  - tree view 鎖定欄位清單（移除 optional 的 `short_name`、`city`）。
  - form view 分區顯示負責人/店長/同負責人，labels 清楚可見。

### 步驟 3：品牌主檔 + 車行類型
- `addons/dms_core/models/dealer.py`：確認 `brand_ids`（Many2many → `dms.brand`）存在。
- `addons/dms_core/security/ir.model.access.csv`：確認 `dms.brand` ACL。
- `addons/dms_core/__manifest__.py`：確認 data 清單含所有 view XML。

### 步驟 4：action context 預設 edit
- `addons/dms_core/views/dealer_views.xml`：`action_dealer` record 補上 context。

### 步驟 5：CSS labels 粗體
- `addons/dms_core/static/src/scss/dealer.scss`（新建）。
- `addons/dms_core/__manifest__.py`：新增 `assets` 區塊。

### 步驟 6：TransactionCase 測試
- `addons/dms_core/tests/__init__.py`（新建）。
- `addons/dms_core/tests/test_dealer.py`（新建）。