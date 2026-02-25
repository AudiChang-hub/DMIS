# Acceptance Criteria（驗收）

- `docker compose up` 可啟動 Odoo 與 Postgres
- `make smoke` 能在 180 秒內得到 200/302/303 回應
- PR 若修改 `addons/**` 或 `docker-compose.yml`，且未同步更新 `specs/**`，CI 失敗
-- 可在 Odoo Apps 中看到並安裝「車行」模組（dealer）

新增車行（Dealer）MVP 驗收條件：

- 在 Odoo 後台能看到 `DMS -> 車行` 選單，點入後可看到清單（tree）與明細（form）。
- 能夠建立新的車行並填寫 `code`、`name`（必填）。
- `code` 欄位為唯一（重複代碼建立時會失敗並提示）。
- 搜尋功能應能以 `code`、`name`、`phone` 查詢到正確記錄。
- 基本 ACL 生效：一般使用者具有讀寫建立刪除的基本權限（以 `security/ir.model.access.csv` 為準）。