# 目前狀態

核對日期：2026-10-06（正式站以 SSH 與頁面實測核對）。

- 應用版本：**1.41.1**，來源 `config/release_notes.py`（各版內容以此為準）；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.41.0**（機種工作區分頁），標籤 v1.41.0、main `da72056`，無 migration；10 機種 80 個分頁實測 200。1.41.1（分頁標示已設定／未設定）待部署。
- **正式資料已於 2026-10-05 依使用者要求清空**（`reset_business_data`）：保留帳號權限、門市、馭盛開單公司、通路類別、假日、報表。清除前備份在 `/srv/dmis-data/dmis-next/backups/pre-reset-20261005/`。車行帳號 `audi` 已停用，待重建車行後重新綁定再啟用；admin 預設店別已清空。重建順序見[使用者手冊](../USER_MANUAL.md)「十四、首次建立基本資料」。
- 清空後已依使用者同意替官網建立的 9 個 SUZUKI 機種補官網車色 31 筆（VehicleColor pk 227–257）；目前 10 個機種啟用且上架，售價與規則由使用者陸續建立。
- 規則摘要：選車上架完全跟著機種啟用；促銷補助金只對網路平台訂單自動帶入、皆可人工更正；沒收訂金訂單一律不可刪除；通路名冊匯入只讀「車行」工作表並略過店名刪除線。細節見 [商業規則](BUSINESS_RULES.md)。
- 2026-10-06 T470P 自動重開機進入核心 7.0.0-34，約 10:48–11:46 對外網路中斷（網站 530／1033），11:46 起正常、原因未確認；再發生先查路由器與網路線，再考慮回到 7.0.0-29。
- CI 品質檢查約需 28 分鐘，逾時上限 45 分鐘。本機 SQLite 測不出 PostgreSQL 鎖定錯誤，CI 另跑 PostgreSQL 驗證。
- 部署前備份只新增不清理；過期清理由 root 的 `dmis-next-backup.timer` 執行。官網檢查排程 `dmis-next-official-catalog-check.timer` 已啟用。
- 1.23–1.34 細節見[發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
- 含簽名 PDF 列印未在正式站實機驗收；未設定 Email 通道，系統內通知正常。
- 規則：[UI](../reference/UI_GUIDELINES.md)、[商業規則](BUSINESS_RULES.md)；SSH 見 [HANDOFF](HANDOFF.md)。
- AI 工具與政策文件只在交接分支，是否合併 main 待使用者指定；工具見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 技術棧：Python 3.12、Django 5.2、HTMX、Channels、RQ、PostgreSQL 16、Redis 7。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位。
