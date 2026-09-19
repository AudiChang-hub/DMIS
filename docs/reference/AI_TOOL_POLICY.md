# AI 工具與 Context 政策

只在工具設定／環境維護任務讀。本次已批准 B；[盤點](AI_TOOL_INVENTORY.md) 是快照，不放入 Hot。

## 已實作設定

- 全域 AGENTS 僅跨專案原則；專案 AGENTS 導向 CURRENT_STATE 和精確模組。
- 全域／本專案單次工具輸出預設 4096 tokens；這不是整個任務 token 配額。必要完整指令仍須分段讀完。
- 本專案子代理並行最多 2；不預設啟動。每位提供不同範圍與驗收，不複製整份對話。
- 本專案停用 Sites（插件＋connector）、visualize、template-creator；不是卸載，其他專案不受影響。
- Office、PDF、Chrome／IAB、既有 GitHub 保留，僅需求吻合才使用。
- node_repl 白名單在其全域 transport 同層；cua_repl 白名單與 js 6000 輸出上限在專案插件 override。都保留 turn_ended 清理能力。
- 未更動模型、推理程度、登入、hooks、sandbox、pipe／環境資訊、插件 cache。既有 CLI 預設模型可用性另見交接。

## 任務路由

| 任務 | 優先工具 | 不先開 |
| --- | --- | --- |
| Python／Django 修正 | 檔案、shell、Git、受影響測試 | Browser、DB MCP、Office、GitHub |
| SUI／UI 真實驗收 | 先定位程式，再用已配置 Browser | 第二個 browser、多組重複頁面 |
| importer bug | importer＋測試；必要時去識別化 fixture | 整本正式 Excel、全表 dump |
| Excel／PPT／Word 成品 | 對應 Skill，依指令讀所需參考 | 所有 Office Skills |
| PR／Issue | 只搜尋本次需要的 GitHub 方法 | 全量 repository／issue dump |
| 外部技術文件 | 官方文件工具／搜尋 | 無關連線或臨時安裝 |

shell 搜尋先給目錄與符號，常態輸出 100–200 行或 1000–4000 tokens；DB 診斷先 LIMIT／COUNT、只取必要欄位，避免敏感資料。
Browser snapshot 僅取一個相關頁面；網路最多 3 並行、間隔至少 1 秒。大結果只保存必要摘錄：問題／原因／解法／影響／驗證。

## Skills 與設定的限制

`allow_implicit_invocation: false` 是 Skill 的 `agents/openai.yaml` policy，不是 config.toml 的任意鍵。
不改供應商 cache，避免更新覆蓋；本次選用 plugin-level 停用，未寫失效的 versioned skill 路徑。
使用者明確要用已停用能力時，先說明範圍，重新啟用該專案插件並重開工作階段；不承諾在同一輪自動熱載入。
MCP 白名單只使用實際存在的工具名，不將 connector 假裝成可設定的本機 server。
On Demand 不代表已從平台永久卸載；本輪已注入的歷史、工具與 Skill 描述無法靠改檔回收。

## 維護與回復

1. 修改全域前備份 AGENTS.md 與 config.toml；本次備份為 `%USERPROFILE%/.codex/backups/least-context-20260919/`，備份時已比對 SHA-256。
2. 專案設定在 [config.toml](../../.codex/config.toml)；不要複製機器特定 command／pipe 到共享 repo。
3. 用 `codex exec --strict-config --ephemeral -s read-only ...` 檢查實際載入；光是 TOML parse 或 config/read 成功不保證 strict layer 合法。
4. 更動後新開工作階段，驗證所需技能／工具與代表任務；當前工作階段不當作完整重新載入。
5. 要回復全域：先保存回復當下檔案，再將上述備份兩檔 Copy-Item 回原位置；只回復這兩個已確認路徑，不遞迴覆寫整個 .codex。
6. 專案用本次 commit 的 `git revert`（先確認工作樹），不用 reset --hard。封存原文保留；沒有刪除 backups、log 或輸出。

## 官方依據

- [AGENTS 載入與專案規則](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [設定範例：工具輸出、子代理、Skills 與 MCP](https://learn.chatgpt.com/es-419/docs/config-file/config-sample)
- [Codex 設定欄位](https://learn.chatgpt.com/docs/config-file/config-reference)

不要估算或保證省下固定百分比 token；可量測 Hot bytes、實際技能清單與工具輸出，平台固定提示另計。
