# 目前狀態

核對日期：2026-09-30（正式站以 SSH 與公開頁面核對）。

- 應用版本：**1.22.3**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.22.3**（選車頁篩選原地更新結果、不重新整理整頁）已於 2026-09-30 發布，main `616c482`（附註標籤 v1.22.3，CI 通過）；deployed-sha 一致，DB／Redis 未重啟，無 migration。部署前備份 `dmis_20260930_131640.sql.gz`。已在使用者 Chrome 以 admin 登入實測：切換車型／能源別與清除篩選皆未重新載入頁面、捲動位置不變。
- 同日稍早：1.22.2（main `6ea6af5`，確認頁與多行文字框外觀，備份 `dmis_20260930_124623.sql.gz`）、1.22.1（main `9e5ad16`，下拉選單自動套用篩選，備份 `dmis_20260930_121606.sql.gz`）、1.22.0（main `1b57af3`，訂單步驟式工作台，備份 `dmis_20260930_113951.sql.gz`）、1.21.1（main `469d4da`，全站版面對齊，備份 `dmis_20260930_110911.sql.gz`）、1.21.0（main `df4022e`，移除發票紀錄、領牌發票照片改選填，migration 0156 刪除 0 筆空表，備份 `dmis_20260930_104055.sql.gz`）。
- 2026-09-29：1.20.0（main `3884202`，migration 0153–0155）、1.19.0（main `4a55a5a`，migration 0152）、1.18.2（main `453ad2f`）。
- 1.19.0–1.20.0 為訂單流程補強 Phase 1–4（收款帳本與沒收退款、交車閘門、車行掛帳、領牌後例外結案、狀態機清理與配車先進先出、內部通知），規格 `specs/056`–`059`；發票紀錄已於 1.21.0 依使用者要求移除。
- 1.22.0 訂單頁改為 7 步驟工作台（規格 `specs/060-order-step-workspace`）：只展開目前步驟、交車同表單收尾款、訂金步驟直接登記收款；收支進階欄位收合，補助追蹤與車控贈品移到對應步驟。規則見 [BUSINESS_RULES](BUSINESS_RULES.md)。
- 正式站只做 SSH 唯讀核對與公開頁面檢查；**登入後頁面尚未在正式站實機驗收**，新流程以本機合成資料驗證。正式站未設定 Email 通道，Email 通知記為「未設定通道」，系統內通知正常。
- 部署時正式站唯一一張未交車的分期單須先在交付頁登記「已核准」才能交車；既有已配車訂單沒有配車時間，不列入保留逾期提醒。
- UI 規則來源為 [UI_GUIDELINES](../reference/UI_GUIDELINES.md)，由 `sales/tests/test_ui_consistency.py` 把關。
- 交接分支 `claude/code-setup` 已推送；應用版本以 cherry-pick 方式發布到 main，分支上其餘 AI 工具與政策文件提交仍未合併 main。
- 正式主機 SSH 連線方式見 [HANDOFF](HANDOFF.md)「已知風險」；僅授權維運時使用。
- 技術棧：Python 3.12、Django 5.2、Templates／HTMX、Channels／Daphne、RQ、PostgreSQL 16、Redis 7；本機可用 SQLite。
- 開發工具：Codex 與 Claude Code 並存；Claude 入口 `CLAUDE.md` 匯入 AGENTS，工具狀態見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 待核對：舊交接提到的五組訂單合併，**狀態待核對**；不可視為未完成或已完成，不可自動執行，等使用者另行指定。
- 已知限制：舊 Odoo 規格只供追溯；「姓名＋車身／引擎號」合併需求不是 importer 全域唯一鍵。UI 自動測試不能替代實機驗收。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位；接手未完工作才讀 [HANDOFF](HANDOFF.md)。
