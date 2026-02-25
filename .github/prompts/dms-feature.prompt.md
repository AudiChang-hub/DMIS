---
name: dms-feature
description: "新功能入口：建立新的 specs 骨架（00~05），列出未決問題與假設，產出最小可行實作步驟（繁中）"
argument-hint: "請以一句話描述新功能目標（例如：新增商品庫存預警）"
agent: copilot
---

請以繁體中文完成下列工作：

1. 建立新的 specs 序號資料夾（於 `specs/` 內使用下一個可用序號，例如 `002-xxx` 或 `003-xxx`），產出 `00-charter.md、01-spec.md、02-clarify.md、03-plan.md、04-tasks.md、05-acceptance.md` 的初始內容骨架。
2. 在 `02-clarify.md` 中列出 Open Questions 與 Assumptions（繁中），並標註需要討論的項目。
3. 產出最小可行實作步驟（含要改動的檔案清單、測試/驗證指令，如 `make up`/`make smoke`）。
4. 產出 PR 樣板（繁中），包含 PR 標題建議、變更摘要、對應 specs 路徑、驗證步驟。

注意：此 prompt 只用於產出 specs 與實作計畫，不直接修改程式碼。所有文字請以繁體中文（charter 可中英）。
