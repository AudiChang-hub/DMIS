# 目前狀態

核對日期：2026-09-29（正式站以 SSH 與公開頁面核對）。

- 應用版本：**1.18.0**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.18.0**（全站畫面風格與操作流程統一）已於 2026-09-29 發布，main 提交 `6da5a4c`（附註標籤 v1.18.0，CI 通過）；工作樹 HEAD、標籤、執行版號一致，DB／Redis 未重啟。部署前備份為 `/srv/dmis-data/dmis-next/backups/postgres/daily/dmis_20260929_134216.sql.gz`。
- 1.18.0 已核對公開頁面、health、單一 `app.css` 與容器內模板；**登入後頁面尚未在正式站實機驗收**（本機已以測試資料跨三種主題與手機寬度比對）。
- UI 規則來源為 [UI_GUIDELINES](../reference/UI_GUIDELINES.md)，由 `sales/tests/test_ui_consistency.py` 把關。
- 交接分支 `claude/code-setup` 已推送；1.18.0 以 cherry-pick 方式從 origin/main 發布，分支上其餘 AI 工具與政策文件提交仍未合併 main。
- 正式主機 SSH 連線方式見 [HANDOFF](HANDOFF.md)「已知風險」；僅授權維運時使用。
- 技術棧：Python 3.12、Django 5.2、Templates／HTMX、Channels／Daphne、RQ、PostgreSQL 16、Redis 7；本機可用 SQLite。
- 開發工具：Codex 與 Claude Code 並存；Claude 入口 `CLAUDE.md` 匯入 AGENTS，工具狀態見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 待核對：舊交接提到的五組訂單合併，**狀態待核對**；不可視為未完成或已完成，不可自動執行，等使用者另行指定。
- 已知限制：舊 Odoo 規格只供追溯；「姓名＋車身／引擎號」合併需求不是 importer 全域唯一鍵。UI 自動測試不能替代實機驗收。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位；接手未完工作才讀 [HANDOFF](HANDOFF.md)。
