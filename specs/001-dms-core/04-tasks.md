# 任務清單 (04-tasks)

## 正式機網路邊界（2026-09-04 安全稽核）

- [x] 舊 Odoo Web、PostgreSQL 與 Metabase 的 host published port 僅綁定 `127.0.0.1`
- [x] Cloudflare Tunnel 與服務間連線維持走 Docker network，不依賴區網公開 port
- [x] 正式機既有 PostgreSQL 角色須另行輪替預設密碼，不能只修改 `.env`
- [x] 套用後從其他區網主機驗證 5433 無法連線，並確認 Metabase 與備份仍正常

## 品牌授權子表（feat: dealer-brand-auth）

### 規格說明
- 新增 `dms.dealer.brand.auth` 模型，取代原 `brand_ids` Many2many
- 欄位：`dealer_id`（車行）、`brand_id`（品牌）、`auth_type`（廠商認定類型：dealer/exclusive/none）
- 車行表單新增「品牌授權」分頁，呈現子表格
- 原 `brand_ids` 欄位保留於 DB（backward compat），但從視圖移除

### 實作項目
- [x] 新增 `addons/dms_core/models/dealer_brand_auth.py`
- [x] `dealer.py` 新增 `brand_auth_ids` One2many
- [x] `dealer_views.xml` 品牌授權分頁（子表格）
- [x] `ir.model.access.csv` 新增 `dms.dealer.brand.auth` 存取權
- [x] `models/__init__.py` import dealer_brand_auth

---



### 規格說明
- 車行代碼改為系統自動產生，使用者無法手動輸入
- 格式：`{前綴}{YY}{MM}{DD}{seq:02d}`，共 9 碼
  - 前綴依車行類型 `category` 欄位決定：`dealer`（經銷）→ `D`、`exclusive`（專賣）→ `S`、其他/未設定 → `N`
  - `YY`：年份後兩碼；`MM`：月；`DD`：日；`seq`：當日同前綴流水碼（01 起跳）
  - 範例：`D260317**01**`（2026-03-17 第一筆經銷車行）
- 產生時機：按下儲存（`create()` 觸發）
- 唯一性：`_sql_constraints` + 建立時迴圈檢查確保不重複

### 實作項目
- [x] `dms.store_type` 新增 `category` 欄位（Selection: dealer/exclusive/other）
- [x] `store_type_views.xml` 加入 `category` 欄位
- [x] `dealer.py`：`code` 改為 `readonly=True`；`create()` 依新格式自動產生
- [x] `dealer_views.xml`：`code` 欄位加 `readonly="1"`

---

## 完整車行需求實作清單

### Step 1 — Specs
- [ ] 01-spec.md — 完整欄位定義與視圖規格
- [ ] 02-clarify.md — 假設與决策
- [ ] 03-plan.md — 實作步驟
- [ ] 04-tasks.md — 任務清單
- [ ] 05-acceptance.md — 驗收條件

### Step 2 — Models
- [ ] `dealer.py`: 更新 `name` label/`store_manager`/`note`/`email`/`address`/`brand_ids`/`store_type_id`/Boolean price fields/`name_search`
- [ ] `dealer.py`: 新增 `copy(default=None)` override，自動產生不重複 `code`（`{code}-C`, `{code}-C2`...`{code}-C19`）
- [ ] `brand.py`: 建立 `dms.brand` model
- [ ] `store_type.py`: 建立 `dms.store_type` model
- [ ] `__init__.py`: import brand, store_type, dealer

### Step 3 — Views
- [ ] `dealer_views.xml`: 4分頁表單 + 新清單 + 搜尋 + action
- [ ] `dealer_views.xml`：tree view 欄位選擇器全面化（所有業務欄位加 `optional` 屬性；預設顯示 ≤15；其餘欄位預設隱藏但可選）
- [ ] `dealer_views.xml`：tree view 補齊缺漏欄位 `address`（地址）、`note`（備註）為 `optional="hide"`
- [ ] `dealer_views.xml`：新增 `ir.actions.server`（`action_dealer_duplicate`）複製動作，綁定 list view
- [ ] `brand_views.xml`: 新增 tree/form/action/menu
- [ ] `store_type_views.xml`: 新增 tree/form/action/menu
- [ ] `static/src/js/dms_dealer_column_limit.js`：新增前端 JS patch，hardcode 最多顯示 15 欄（超過時阻止 + warning notification + 強制 OWL rerender 回復 checkbox 狀態），僅對 `dms.dealer` list view 生效
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

## 產品管理任務（dms.product）

### Step P1 — Specs
- [ ] `01-spec.md`：新增「產品管理」章節（欄位定義、分頁規格）
- [ ] `02-clarify.md`：新增 energy_type 分頁控制假設
- [ ] `04-tasks.md`：本清單
- [ ] `05-acceptance.md`：新增產品管理驗收條件

### Step P2 — Model
- [ ] `models/product.py`：新增 `dms.product` 模型（基本資料、油車動力、電車動力、車身規格欄位）
- [ ] `models/__init__.py`：加入 `from . import product`

### Step P3 — Views / ACL / Manifest
- [ ] `views/product_views.xml`：tree view（6 欄）、form view（4 分頁含條件分頁）、search view、action、menu
- [ ] `security/ir.model.access.csv`：新增 `access_dms_product` 行（全 1）
- [ ] `__manifest__.py`：在 `data` 清單加入 `views/product_views.xml`

### Step P4 — Upgrade & Smoke
- [ ] `docker compose restart odoo`
- [ ] CLI upgrade `dms_core` (`--stop-after-init`)
- [ ] HTTP /web/login 回應 200
- [ ] 手動測試：DMS → 產品管理 → 新增產品，切換能源型式，驗證分頁顯示切換
