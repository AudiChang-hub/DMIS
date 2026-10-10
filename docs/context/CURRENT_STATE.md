# 目前狀態

核對日期：2026-10-06。

- 版本：**1.70.1**（`config/release_notes.py`，各版內容以此為準）；正式站 1.70.1（migration 至 0177）。發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式資料已於 2026-10-05 依使用者要求清空，正在重建主檔；目前 10 個 SUZUKI 機種啟用並上架。清除前備份：`/srv/dmis-data/dmis-next/backups/pre-reset-20261005/`。重建順序見[使用者手冊](../USER_MANUAL.md)第十四章。
- 待辦：車行帳號 `audi` 已停用，車行重建後重新綁定再啟用；admin 預設店別待重選。待使用者決定：車行掛帳是否改用「車行結算」金額、本店單指定車行時是否套用該車行傭金、淨利鎖定時是否隱藏收支合計、車行結算是否開放給非財務交車人員。含簽名 PDF 列印未在正式站實機驗收；未設定 Email 通道。
- 帳號權限（2026-10-10 使用者要求，只有店內人員使用）：morris、nina、Sylvia 三人一致、業務全開；帳號管理、完整性報告、淨利限 admin。異動紀錄在各人的權限修訂歷程。
- 暫停的流程（2026-10-10，現階段訂單都由本店處理）：建立人直接接單 `order_intake.AUTO_ACCEPT_ON_CREATE=True`、代開公司確認 `intake_forms.ASSISTED_COMPANY_CONFIRMATION=False`；恢復時改回開關。
- 主機：T470P 核心 7.0.0-34，2026-10-06 曾對外斷網約 1 小時、原因未確認；再發生先查路由器與網路線。SSH 見 [HANDOFF](HANDOFF.md)。
- CI 約 21 分鐘（完整測試已平行，上限 45）；本機 SQLite 測不出 PostgreSQL 鎖定，CI 另跑 PostgreSQL 驗證。
- 規則：[商業規則](BUSINESS_RULES.md)、[UI](../reference/UI_GUIDELINES.md)；工具：[AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。1.23–1.34 見[發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
- 技術棧：Python 3.12、Django 5.2、HTMX、Channels、RQ、PostgreSQL 16、Redis 7。
