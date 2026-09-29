# Handoff

更新日期：2026-09-29

## 本次完成

開發工具由 Codex 交接到 Claude Code：建立精簡 `CLAUDE.md`（匯入 AGENTS）、共享 `.claude/settings.json`、本機檔忽略規則，並更新 CURRENT_STATE。
未改業務程式、正式資料、權限、部署流程；在分支 `claude/code-setup` 分兩個提交（未 push、未合併 main）、未發布、未刪除 Codex 設定或 archive。

## 修改檔案

新增 `CLAUDE.md`、`.claude/settings.json`；修改 `.gitignore`、`docs/context/CURRENT_STATE.md`、本檔、`docs/reference/AI_TOOL_POLICY.md`（Claude 小節）。
使用者的 `AGENTS.md`、`docs/RELEASE_POLICY.md`、`docs/reference/DEVELOPMENT.md` 原樣獨立提交，未修改內容。

## 驗證結果

- Claude Code 2.1.284 位於 Desktop 內建路徑，shell PATH 無 `claude`。
- 遠端 main 為 `985a071`；遠端標籤最新 v1.17.2 = `615b1ae`。
- 公開健康檢查 200；SSH `t470p` 以 BatchMode 被拒（publickey），正式部署 SHA 未重新核對。
- `tests/context` 8 項通過；settings.json 可解析，local 檔確認被忽略；重開後的工作階段已由 CLAUDE.md 載入；是否重複載入 AGENTS 仍以 `/context`「Memory files」確認。

## 尚未完成

- 1.17.3 已在 main、正式站仍 1.17.2，是否發布待使用者指定。
- 舊交接的五組訂單合併：狀態待核對，未執行也不得自動執行。
- `claude/code-setup` 是否 push／合併 main，待使用者指定。

## 已知風險

- `rg` 只存在 Codex 安裝目錄，不在 PATH；Claude 內建 Grep 可用，獨立 rg 未安裝。
- Docker CLI 存在但 daemon 未執行。SSH `t470p` 在 Windows 端未指定金鑰、`~/.ssh` 無對應預設金鑰、ssh-agent 停用；需使用者補齊，未改登入設定。
- CI 尚未依風險分流，屬另項待核准工作。

## 下一步

新任務從 CURRENT_STATE 及 AGENTS 路由進入；不自動續跑舊聊天任務或正式資料合併。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)；只有工具維護讀 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
