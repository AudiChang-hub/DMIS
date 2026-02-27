# 03 - Plan

實作步驟（依序執行）：
1. 更新 specs（已建立）
2. 補齊 `dms.dealer` 模型欄位/行為（create/write/onchange/constraints）
3. 新增 `dms.brand`, `dms.store_type` models 與 views + ACL
4. 更新 `dealer_views.xml`（tree/form/search/action）
5. 新增 seed 資料
6. 新增 SCSS assets（可選）
7. 新增 tests 並執行

每個邏輯變更獨立 commit，commit 後執行 `make smoke`。
# 計畫（Plan）

1. 建立模組骨架與基本 model/view。
2. 提供 docker-compose 與 smoke 測試腳本。
3. 撰寫 CI 檢查 specs 同步。
4. 提交並驗證一鍵啟動流程。