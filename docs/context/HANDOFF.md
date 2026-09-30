# Handoff

更新日期：2026-09-30

## 本次完成

訂單、金流、庫存與交付流程補強 Phase 1–4，已發布 1.19.0（Phase 1）與 1.20.0（Phase 2–4）。
2026-09-30：1.21.0 依使用者要求移除發票紀錄；1.22.0 訂單頁改為步驟式工作台（A 方案兩階段同版發布，`specs/060`）。
使用者定調規則與授權範圍見 `specs/056-payment-ledger`、`057-business-gates`、`058-state-integrity`、`059-invoices-notifications`，有效規則已併入 BUSINESS_RULES。

## 驗證結果

- 本機：各期新增測試（帳本 14、閘門 6、狀態 7、發票通知 8）與受影響套件約 916 項通過；前端 order-workspace 測試通過；CI 1.19.0、1.20.0 皆通過。
- 本機以合成資料在瀏覽器實際操作：沒收／退款結算、沖銷、溢收、分期閘門、例外結案面板、發票面板、我的通知。
- 正式站：部署前唯讀核對（無負數收款、無取消待退款、分期狀態全空白、無調車狀態資料）；部署後核對 migration 0152–0155、版號、deployed-sha、worker 佇列、health 200，訂單與車輛數量不變。

## 尚未完成

- 正式站登入後畫面未實機驗收（無登入帳密，不代為輸入）；1.22.0 步驟式訂單頁請使用者實際走一張訂單確認順序與摘要。
- Email 通道未設定：需要時在正式站設定 SMTP 與 `DMIS_NOTIFICATION_EMAIL_ENABLED=true`，再用 `send_pending_notifications` 補發。
- 客戶端簡訊／LINE 通知需使用者提供服務商帳號；L5（外部串接冪等）使用者指示之後再議。
- 舊交接的五組訂單合併：狀態待核對，未執行也不得自動執行。
- `claude/code-setup` 上的 AI 工具／政策文件提交是否合併 main，待使用者指定。

## 已知風險

- 正式站唯一一張未交車的分期單，須先在交付頁登記「已核准」才能交車。
- 既有已配車訂單沒有配車時間，不列入保留逾期；取消前已存在的 1 張已取消單標記為舊制退款。
- `rg` 不在 PATH；Claude 內建 Grep 可用。Docker daemon 本機未執行。
- 正式主機 SSH：`ssh -i "C:/Users/user/.ssh/line_monitor_ubuntu_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes t470p "<指令>"`；僅限已授權維運。
- CI 尚未依風險分流，單次約 25 分鐘。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)、[BUSINESS_RULES](BUSINESS_RULES.md) 財務與訂單小節、對應 specs。
