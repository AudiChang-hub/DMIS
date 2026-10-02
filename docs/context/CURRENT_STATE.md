# 目前狀態

核對日期：2026-10-02（正式站以 SSH 與公開頁面核對）。

- 應用版本：**1.34.0**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.34.0**（全新介面設計第四階段，主題改名）2026-10-02 發布，main `1fbe82a`（標籤 v1.34.0），deployed-sha 一致，migration 0159 只改主題選項名稱，DB／Redis 未重啟，備份 `dmis_20261002_165749.sql.gz`。
- 1.23–1.34 的版本、備份與部署細節見[發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
- 官網檢查排程 `dmis-next-official-catalog-check.timer` 已啟用，首次執行 2026-10-05 05:47；正式站尚未執行官網檢查、對應或補圖。
- 登入後畫面與含簽名 PDF 列印未在正式站實機驗收；未設定 Email 通道，系統內通知正常。
- 唯一一張未交車的分期單須先在交付頁登記「已核准」才能交車。
- 規則：[UI](../reference/UI_GUIDELINES.md)、[商業規則](BUSINESS_RULES.md)；SSH 見 [HANDOFF](HANDOFF.md)。
- AI 工具與政策文件只在交接分支，是否合併 main 待使用者指定；工具見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 待核對：舊交接的五組訂單合併，不可視為已完成或自動執行。
- 技術棧：Python 3.12、Django 5.2、HTMX、Channels、RQ、PostgreSQL 16、Redis 7。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位。
