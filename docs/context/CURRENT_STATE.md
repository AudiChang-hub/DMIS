# 目前狀態

核對日期：2026-09-29（正式站以 SSH 與公開頁面核對）。

- 應用版本：**1.17.3**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 正式站：**1.17.3** 已於 2026-09-29 發布，提交 `985a071`（附註標籤 v1.17.3，CI 通過）；工作樹 HEAD、deployed-sha、執行版號一致，DB／Redis 未重啟。發布前備份為 `backups/postgres/daily/dmis_20260929_112251.sql.gz`。
- 1.17.3 登入後畫面與依權限顯示的版本歷程尚未實機驗收（無可用登入）。
- 交接分支 `claude/code-setup` 已推送遠端備存，尚未合併 main；是否與遠端同步以當次 Git 查詢為準，正式站版本需獨立核對。
- 正式主機 SSH 連線方式見 [HANDOFF](HANDOFF.md)「已知風險」；僅授權維運時使用。
- 技術棧：Python 3.12、Django 5.2、Templates／HTMX、Channels／Daphne、RQ、PostgreSQL 16、Redis 7；本機可用 SQLite。
- 開發工具：Codex 與 Claude Code 並存；Claude 入口 `CLAUDE.md` 匯入 AGENTS，工具狀態見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 待核對：舊交接提到的五組訂單合併，**狀態待核對**；不可視為未完成或已完成，不可自動執行，等使用者另行指定。
- 已知限制：舊 Odoo 規格只供追溯；「姓名＋車身／引擎號」合併需求不是 importer 全域唯一鍵。UI 自動測試不能替代實機驗收。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位；接手未完工作才讀 [HANDOFF](HANDOFF.md)。
