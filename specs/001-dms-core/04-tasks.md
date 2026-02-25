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