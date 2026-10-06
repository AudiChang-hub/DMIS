# 目前狀態

核對日期：2026-10-06（正式站以 SSH 與頁面實測核對）。

- 應用版本：**1.38.0**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.38.0**（機種轉為啟用自動上架選車展示；官網建立車型時未修改的預填車色也會建立）2026-10-06 發布，main `a52b891`（標籤 v1.38.0），無 migration。同日依使用者同意，替官網建立的 9 個 SUZUKI 機種補回官網車色 31 筆（VehicleColor pk 227–257）；Gixxer 250「消光藍」原為停用未變更。1.37.1（使用說明停在頁首、沒收訂金訂單一律不可刪除、完整性報告按鈕依權限）同日稍早發布。1.37.0（使用說明全面更新、`reset_business_data`）2026-10-05 發布。
- 2026-10-06 T470P 於 09:43 自動重開機進入核心 7.0.0-34，約 10:48–11:46 主機對外網路中斷（網站 530／1033）；11:46 網路線連線恢復後正常，原因未確認，再發生先查路由器與網路線，再考慮回到 7.0.0-29。
- **正式資料已清空（2026-10-05 21:50，使用者要求）**：以 `reset_business_data` 清除 47,803 筆業務與主檔資料（含 1,787 筆舊系統匯入訂單、1,499 台庫存、品牌／車型／車色／售價／通路／分期等主檔），並刪除全部 995 個媒體附件。保留帳號與權限、門市 3 筆、馭盛開單公司、通路類別、工作日與假日、報表定義與版本歷程。車行帳號 `audi` 已自動停用，待重建車行後重新綁定再啟用；admin 的預設店別已清空。清除前備份：`/srv/dmis-data/dmis-next/backups/pre-reset-20261005/`（`dmis_20261005_214853.sql.gz`＋`media_20261005_pre_reset.tar.gz`）。重建順序見[使用者手冊](../USER_MANUAL.md)「十四、首次建立基本資料」。清除後 105 個頁面與報表以 admin 實測無 500。1.35–1.36（優先配車、車輛來源）功能內容以 release notes 為準。
- 本機測試用 SQLite，不會檢出 PostgreSQL 鎖定錯誤；CI「Verify order sorting with PostgreSQL」已加跑 `test_allocation_priority`、`test_document_signing`。
- 部署前備份只新增不清理；過期清理只由 root 的 `dmis-next-backup.timer` 執行（1.35.0 部署已套用）。
- 1.23–1.34 的版本、備份與部署細節見[發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
- 官網檢查排程 `dmis-next-official-catalog-check.timer` 已啟用；清空後官網檢查紀錄已歸零，可用「原廠車型比對」從官網建立車型。
- 登入後畫面與含簽名 PDF 列印未在正式站實機驗收；未設定 Email 通道，系統內通知正常。
- 規則：[UI](../reference/UI_GUIDELINES.md)、[商業規則](BUSINESS_RULES.md)；SSH 見 [HANDOFF](HANDOFF.md)。
- AI 工具與政策文件只在交接分支，是否合併 main 待使用者指定；工具見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 技術棧：Python 3.12、Django 5.2、HTMX、Channels、RQ、PostgreSQL 16、Redis 7。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位。
