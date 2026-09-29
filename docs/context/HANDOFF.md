# Handoff

更新日期：2026-09-29

## 本次完成

開發工具由 Codex 交接到 Claude Code：建立精簡 `CLAUDE.md`（匯入 AGENTS）、共享 `.claude/settings.json`、本機檔忽略規則，並更新 CURRENT_STATE。
未改業務程式、正式資料、權限、部署流程；變更在交接分支 `claude/code-setup`（已推送遠端備存、未合併 main）、未發布、未刪除 Codex 設定或 archive。

## 修改檔案

新增 `CLAUDE.md`、`.claude/settings.json`；修改 `.gitignore`、`docs/context/CURRENT_STATE.md`、本檔、`docs/reference/AI_TOOL_POLICY.md`（Claude 小節）。
使用者的 `AGENTS.md`、`docs/RELEASE_POLICY.md`、`docs/reference/DEVELOPMENT.md` 原樣獨立提交，未修改內容。

## 驗證結果

- Claude Code 2.1.284 位於 Desktop 內建路徑，shell PATH 無 `claude`。
- 2026-09-29 核對：main 為 1.17.3（遠端 `985a071`，無 v1.17.3 標籤）；正式站為 1.17.2。
- 正式站以 SSH 唯讀核對：工作樹 main 乾淨，HEAD＝deployed-sha＝`615b1ae`（v1.17.2）；公開健康檢查 200。
- `tests/context` 8 項通過；settings.json 可解析，local 檔確認被忽略；新工作階段 `/context` 驗收**尚未完成**，由使用者另開工作階段確認 CLAUDE.md 與 AGENTS.md 各載入一次。
- 權限規則僅靜態檢查（鍵與格式符合官方文件）；實際阻擋**尚未驗證**。規則為前綴比對，例如 `git push origin main --force` 不符 `git push --force *`，不保證攔截所有寫法。實測只能用不連正式遠端的隔離測試 Repository，不得在本專案試 `git push --force`。

## 尚未完成

- 1.17.3 已在 main、正式站仍 1.17.2，是否發布待使用者指定。
- 舊交接的五組訂單合併：狀態待核對，未執行也不得自動執行。
- `claude/code-setup` 是否合併 main，待使用者指定；同步狀態以當次 Git 查詢為準。

## 已知風險

- `rg` 只存在 Codex 安裝目錄，不在 PATH；Claude 內建 Grep 可用，獨立 rg 未安裝。
- Docker CLI 存在但 daemon 未執行。
- 正式主機 SSH：`~/.ssh/config` 的 `t470p` 未指定金鑰、ssh-agent 停用，須明確指定既有金鑰：
  `ssh -i "C:/Users/user/.ssh/line_monitor_ubuntu_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes t470p "<唯讀指令>"`。
  僅限已授權維運；不讀出私鑰、不改 SSH 設定／指紋／金鑰權限。
- CI 尚未依風險分流，屬另項待核准工作。

## 下一步

新任務從 CURRENT_STATE 及 AGENTS 路由進入；不自動續跑舊聊天任務或正式資料合併。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)；只有工具維護讀 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
