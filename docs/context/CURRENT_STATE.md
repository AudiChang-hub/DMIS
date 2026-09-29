# 目前狀態

核對日期：2026-09-29（唯讀核對；未部署、未改正式資料）。

- 應用版本：**1.17.3**，來源 `config/release_notes.py`；發布規範見 [RELEASE_POLICY](../RELEASE_POLICY.md)。
- 版本位置：
  - main：**1.17.3**，遠端 main `985a071`（含 `d3082a1` 頁首日期時間及受眾規則補充）。
  - 正式站：**1.17.2** `615b1ae`（= 標籤 v1.17.2）；2026-09-29 以 SSH 唯讀核對工作樹 main 乾淨、HEAD 與 deployed-sha 一致；健康檢查 200。
  - 遠端無 `v1.17.3` 標籤。1.17.3 已進 main、**未發布**；不得自行補標籤、部署或回退，待使用者指定。
- 分支 `claude/code-setup`（未 push、未合併 main）：風險分級政策、Claude Code 設定、交接現況共三個提交。
- 正式主機 SSH 連線方式見 [HANDOFF](HANDOFF.md)「已知風險」；僅授權維運時使用。
- 技術棧：Python 3.12、Django 5.2、Templates／HTMX、Channels／Daphne、RQ、PostgreSQL 16、Redis 7；本機可用 SQLite。
- 開發工具：Codex 與 Claude Code 並存；Claude 入口 `CLAUDE.md` 匯入 AGENTS，工具狀態見 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
- 待核對：舊交接提到的五組訂單合併，**狀態待核對**；不可視為未完成或已完成，不可自動執行，等使用者另行指定。
- 已知限制：舊 Odoo 規格只供追溯；「姓名＋車身／引擎號」合併需求不是 importer 全域唯一鍵。UI 自動測試不能替代實機驗收。
- 下一步：依新需求從 [AGENTS](../../AGENTS.md) 路由定位；接手未完工作才讀 [HANDOFF](HANDOFF.md)。
