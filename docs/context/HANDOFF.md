# Handoff

更新日期：2026-09-19

## 本次完成

使用者批准 B：建立全域／repo 規則、Hot／Warm／Cold 分層、精簡 README、歷史原文封存與相容入口、工具分級與限制。
本次沒有改應用邏輯、正式資料或執行部署。

## 修改檔案

AGENTS、.codex/config.toml、docs/context、docs/architecture、docs/reference、docs/archive；
README、CONSTITUTION、Gemini／Copilot／prompts、歷史 PR 導向、.gitignore、specs/055-least-context、tests/context、tools/context_lookup.py 及 CI 的 Context 檢查步驟。
本機全域兩檔先備份於 %USERPROFILE%/.codex/backups/least-context-20260919/，不納入 repo。

## 驗證結果

- 八項 unittest 全通過：Hot 大小、路由、bounded lookup、連結、設定、ignore、封存 SHA-256、交接格式。
- 15 份封存與原提交 9b83d43 原文一致（統一換行與檔尾空白）；沒有刪除備份或歷史。
- config/read 確認專案層有效，skills/list 列 12 份且零錯誤；exec --strict-config 實際載入通過。
- 最終新工作階段：一次 shell 操作讀現況／Git 狀態並執行兩個定位器，正確找到 catalog() 與 _sales_transaction_key() 後停止；未開 Browser、DB 或改檔。
- check_release 通過，應用維持 1.11.0；未執行 Django 全套測試、正式部署與正式資料驗證，因本次沒有相關異動。
- 變更在 codex/least-context-architecture 獨立分支保存，不合併 main、不發布應用。驗證細節見 [CONTEXT_VALIDATION](../reference/CONTEXT_VALIDATION.md)。

## 尚未完成

先前使用者指定的五組訂單合併尚未執行；本次 AI 環境工作不包含資料清理。恢復時依使用者已確認範圍重新檢查來源／主單、財務衝突、附件及備份，不依聊天摘要直接寫庫。

## 已知風險

全域 CLI 原模型 gpt-5.3-codex-spark 已被帳號拒絕，永久設定未變；最終唯讀驗收暫用帳號 model/list 回報可用的 gpt-5.6-sol，未替使用者永久選新模型。
本輪已有提示無法移除；新工作階段才是驗證設定的基準。Desktop 平台工具不一定能由 repo 設定移除。
舊文件封存保留原文及相對路徑語境，不能照歷史指令操作正式服務。

## 下一步

新工作階段重新載入工具設定；新任務從 CURRENT_STATE 及 AGENTS 路由進入，不自動續跑正式資料合併。
如要直接用 CLI，先由使用者選擇支援的模型或明確指定臨時 -m；不要悄悄覆寫全域模型偏好。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)；只有工具維護讀 [AI_TOOL_POLICY](../reference/AI_TOOL_POLICY.md)。
