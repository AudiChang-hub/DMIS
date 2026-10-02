# Handoff

更新日期：2026-10-02

## 本次完成

1.30.0（全站操作中提示，一併升 pypdf 6.19.0）已發布：main `247cc92`、附註標籤 v1.30.0、正式站 deployed-sha 一致。
CURRENT_STATE 精簡回熱脈絡預算內，1.23–1.30 的版本、備份與部署細節移至 [發布歷史](../archive/2026-10-02/CURRENT_STATE-release-history.md)。
訂單流程補強（1.19–1.20）、電子簽署（1.25）、訂單精靈（1.26）等有效規則見 [BUSINESS_RULES](BUSINESS_RULES.md) 與對應 specs。

## 修改檔案

docs/context/CURRENT_STATE.md、docs/context/HANDOFF.md、docs/archive/2026-10-02/CURRENT_STATE-release-history.md；未改應用程式碼、正式資料或部署。

## 驗證結果

- `python -m unittest discover -s tests/context`：8 項通過（含熱脈絡預算與本檔格式）。
- 正式站以 SSH 唯讀核對：HEAD、deployed-sha、v1.30.0 標籤均為 `247cc92`，web healthy，`/health/` 回 ok；DB／Redis 未重啟。
- 文件提交在 main 之後，正式站 HEAD 落後 main 純文件提交屬正常，不需部署。

## 尚未完成

- 正式站登入後畫面未實機驗收：1.30.0 操作中提示、含簽名 PDF 列印（pypdf 升版）、1.25 電子簽署、1.26 訂單精靈。
- 官網檢查排程首次執行 2026-10-05 05:47；正式站尚未執行官網檢查、對應或補圖。
- Email 通道未設定：需要時設定 SMTP 與 `DMIS_NOTIFICATION_EMAIL_ENABLED=true`，再用 `send_pending_notifications` 補發。
- 客戶端簡訊／LINE 通知需使用者提供服務商帳號。
- 舊交接的五組訂單合併：狀態待核對，未執行也不得自動執行。
- 交接分支上的 AI 工具／政策文件是否合併 main，待使用者指定。

## 已知風險

- 唯一一張未交車的分期單須先在交付頁登記「已核准」才能交車。
- 多個工作階段可能同時發布；發布前先查 `gh run list` 與正式站 deployed-sha，避免重複打標籤或部署。
- CURRENT_STATE 不得超過 5000 位元組（與 AGENTS 合計 8000），新增發布紀錄時舊版移至 archive。
- `rg` 不在 PATH；Claude 內建 Grep 可用。CI 尚未依風險分流，單次約 25 分鐘。
- 正式主機 SSH：`ssh -i "C:/Users/user/.ssh/line_monitor_ubuntu_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes t470p "<指令>"`；僅限已授權維運。

## 下一步

等使用者實機驗收回饋；新需求從 [AGENTS](../../AGENTS.md) 路由定位，不自動執行訂單合併或寫入正式資料。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)、[BUSINESS_RULES](BUSINESS_RULES.md) 財務與訂單小節、對應 specs。
