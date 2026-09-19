---
name: dms-specify
description: "需求變更入口（Spec-first 流程）：影響分析 → 先改 specs → 最小實作 → make smoke → 建 PR（繁體中文）"
argument-hint: "請貼上需求變更摘要（一句話或數段描述）"
agent: copilot
---

請以繁體中文執行以下 Spec-first 流程（不要做程式修改、先產出規格）：

1. 讀取並遵守 `docs/CONSTITUTION.md`、`.github/copilot-instructions.md` 與 `specs/` 目錄內最新相關 spec。
2. 進行「影響分析」：列出此變更會影響的檔案/模組（例如 `addons/...`、`docker-compose.yml`、`specs/...`、`scripts/...`、`Makefile`）。
3. 依影響分析結果，產出需要新增或修改的 `specs/` 文件清單（至少更新以下檔案或新增序號檔：`01-spec.md`、`02-clarify.md`、`03-plan.md`、`04-tasks.md`、`05-acceptance.md`），並直接產出繁體中文內容草稿。
4. 明確列出「只改哪些檔案」的範圍（要求開發者在實作時只修改影響分析列出的檔案，避免亂改）。
5. 建議最小可行實作步驟（包含 make smoke 的驗證步驟），並產出 PR 樣板文字（繁中）供複製貼上。

輸出格式要求（皆繁體中文）：
- 影響分析：列清單（路徑）
- 要更新/新增的 specs 檔案與內容（逐檔案列出要點）
- 最小實作步驟（逐步指令，包含 `make up` / `make smoke`）
- PR 範本（標題、描述、驗證步驟、spec 路徑）

注意：本 prompt 只產出規格與流程，不執行實作或 commit。實作階段請使用 /dms-feature 或手動建立分支。所有產出請使用繁體中文（charter 可有英文補充）。
