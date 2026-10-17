# 目前狀態

核對日期：2026-10-17。

- 版本：**1.86.5**（`config/release_notes.py`，各版內容以此為準）；正式站 1.86.5（migration 至 0192）。只有選號方式「指定號碼」收選號費，訂金頁目前金額會列出。訂購單配件多時自動續頁，收款資料、確認事項與簽名固定在每聯最後一頁。付款方式可多筆（現金／刷卡／匯款／分期，車價＝合計，見 BUSINESS_RULES）。系統只給本店人員使用：無車行帳號、無代開單、無待接單（開單者即接單人），訂購單一律用本店公司（見 BUSINESS_RULES「訂單與接待」）。建立訂單七步（車款與車價→車主→汰舊→選號→配件（可略過）→訂金（列目前金額、填備註）→確認），選車卡片直接接單。訂單頁全面自動儲存、資料維護區草稿＋套用。發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式資料已於 2026-10-05 依使用者要求清空，正在重建主檔；目前 10 個 SUZUKI 機種啟用並上架。清除前備份：`/srv/dmis-data/dmis-next/backups/pre-reset-20261005/`。重建順序見[使用者手冊](../USER_MANUAL.md)第十四章。
- 待辦：`audi`（原車行帳號）已轉為店內帳號並維持停用。2026-10-17 使用者確認：車行單掛帳維持記客戶應收尾款、不扣傭金；本店單指定車行不算該車行基礎傭金（維持現行）；車行結算全員可看（店內帳號都有收支權限，不另分財務）；全員皆本店人員，不需設定預設店別；含簽名 PDF 列印不另做正式站實測；不使用 Email 通知（通道維持未設定）。
- 帳號權限（2026-10-10 使用者要求，只有店內人員使用）：morris、nina、Sylvia 三人一致、業務全開；帳號管理、完整性報告、淨利限 admin。2026-10-15 起取消淨利解鎖與敏感資料的密碼驗證／身分證遮罩（見 BUSINESS_RULES）。異動紀錄在各人的權限修訂歷程。
- 主機：T470P 核心 7.0.0-34，2026-10-06 曾對外斷網約 1 小時、原因未確認；再發生先查路由器與網路線。SSH 見 [HANDOFF](HANDOFF.md)。
- CI 約 21 分鐘（完整測試已平行，上限 45）；本機 SQLite 測不出 PostgreSQL 鎖定，CI 另跑 PostgreSQL 驗證。
- 規則：[商業規則](BUSINESS_RULES.md)、[UI](../reference/UI_GUIDELINES.md)；工具：[AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。1.23–1.34 見[發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
- 技術棧：Python 3.12、Django 5.2、HTMX、Channels、RQ、PostgreSQL 16、Redis 7。
