# 計畫（繁體中文）

1. 規格階段
- 撰寫並核准 `specs/002-store-management` 文件集（01~04）。

2. 實作階段
- 在 feature/002-車行管理完整化 分支中完成模型擴充、view 調整、權限設定與示範資料更新，分為至少兩個 commit（規格 + 實作）。

3. 驗證階段
- 啟動容器、安裝或更新 `dms_core` 模組，並依 04-tasks 列出的 DoD 逐條驗收。

4. 合併與交付
- PR 審查通過後以 Squash 合併，並把驗收步驟寫入 PR 描述，供 CI 或 reviewer 驗證。

Implementation details (high level)
- Model: add fields listed in 01-specify; ensure SQL and Python constraints; add `dms.dealer.tag` for tags.
- Views: update tree/form/search per UI guidance and group fields into notebook pages.
- Security: add two groups (read-only / manager) and update `ir.model.access.csv` accordingly.
- Data: update `data/seed.xml` with examples for new fields; avoid destructive migrations.

Testing
- Manual: follow PR validation steps (start compose, smoke, install/upgrade module, exercise DoD items).
- Automated: add lightweight server-side tests if possible to assert constraints and name_get behavior.

