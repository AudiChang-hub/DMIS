---
name: dms-merge
description: "合併前檢查清單產生器：輸入 PR 連結或編號，輸出繁中合併檢查清單與建議（不做實作）"
argument-hint: "請輸入 PR 編號或完整 URL（例如：#23 或 https://github.com/owner/repo/pull/23）"
agent: copilot
---

請以繁體中文輸出下列內容（不執行合併）：

1. 檢查清單：
   - 是否已更新對應 `specs/**`（若 PR 變更包含 `addons/**`、`docker-compose.yml`、`scripts/**` 或 `Makefile`，則 `specs/**` 必須同步更新）
   - 是否包含驗證步驟（`make up` / `make smoke` / `docker compose ps`）並且可重現
   - 是否有清楚的決策紀錄（如需在 `02-clarify.md` 補記）
   - 風險評估與回滾步驟
2. 建議的 squash commit message（繁中）範例
3. 若發現缺項，列出建議補充的項目與優先順序

只輸出檢查清單與建議，勿執行任何變更或合併指令。
