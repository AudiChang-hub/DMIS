@AGENTS.md

## Claude Code 補充

- 一律使用繁體中文回覆；commit 訊息簡潔繁中。
- AGENTS.md 是規則主來源；本檔只放 Claude 專用限制，衝突時指出差異，不自行覆蓋。
- 不用 `@` 自動載入 docs；依 AGENTS 路由按需讀取。Codex 專屬設定（`.codex/`）保留，不當成 Claude 設定。
- 未經使用者明確要求，不 commit、push、打標籤、部署或寫正式資料；保留他人未提交修改，不夾帶提交。
- 子代理預設不啟動，最多 2 個並行；Browser 最多 1 個、3 頁，用完關閉；網路最多 3 並行。
- Windows：主要用 PowerShell；`rg` 不在 PATH 時改用內建 Grep／Glob。
