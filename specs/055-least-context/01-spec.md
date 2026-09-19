# Least Context Architecture

批准：使用者 2026-09-19 選擇 B 並要求完整實作。

## 範圍與接受條件

- 全域／專案 AGENTS 分層；Hot 入口總計不超過 10 KiB（UTF-8 實測，不冒稱 token）。
- CURRENT_STATE 只描述現在；BUSINESS_RULES、DECISIONS、HANDOFF 各自單一來源。
- README 簡化，開發與維運移至 reference；過時文件原文封存，舊連結保留導向頁。
- 本專案限制無關插件、MCP 工具白名單與輸出、子代理並行數；保留 Office、瀏覽器與安全 lifecycle 能力。
- 不改供應商 Skill cache、不改模型／密碼／hooks、不宣稱能卸載目前對話已有內容。
- 靜態測試：文件連結、入口大小、封存完整性、TOML、ignore、設定來源。
- 新工作階段：驗證 SUI 車色及 importer 定位，無寫入／部署；失敗與平台限制如實交接。

## 不在範圍

不改應用邏輯、版號、migration、正式資料或服務；不執行先前的五組訂單合併。不刪除備份、輸出或歷史記錄。

## 回復

全域檔案用已驗證備份回復；專案以本次 commit 的 Git revert 回復。原文在 archive，不須找舊聊天。回復設定後需新開工作階段驗證。
