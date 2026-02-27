# 任務清單（Tasks）

- 建立 `addons/dms_core` 模組
- 建立 views 與 menu
- 撰寫 specs 文件
- 準備 CI 與 smoke 檢查

新增任務（MVP#1 - Dealer）：

- 在 `addons/dms_core/models/dealer.py` 新增欄位：`code,name,level,active,contact_name,phone,email,address`，並加入 `code` 唯一性約束。
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