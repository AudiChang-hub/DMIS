# 00 — Charter：財務結算模組（dms_finance）

## 宗旨

減少 Excel 彙整與人工計算，統一在 Odoo 系統中記錄每筆銷售的收入、支出與淨利，提供財務結算介面，並作為後續 BI 報表（Phase 4）的資料基礎。

## 範圍

- 新增 `dms_finance` 模組於 `addons/dms_finance/`。
- 與 `dms_sale` 整合：以 Smart Button 從銷售訂單直達財務結算頁。
- 建立收入（15 種）與支出（11 種）明細，由系統自動帶入部分預設值。
- 不修改現有模組核心邏輯，僅以 `_inherit` 擴充。

## 目標用戶

- 財務人員：記錄各筆銷售的收支細節、計算淨利。
- 管理者：查看跨訂單的財務彙總，作為績效與利潤分析依據。

## 成功指標

1. `docker compose up` 後安裝模組無 ERROR。
2. 從銷售訂單點擊 Smart Button 能自動建立並開啟財務結算。
3. 收入/支出明細可手動編輯，淨利即時計算正確。
4. `make smoke` 180 秒內完成且 HTTP 200。

## 限制

- Odoo 16 Community Edition。
- 不使用 Enterprise 功能（如 account 模組的 analytic lines）。
- 貨幣僅支援新台幣（TWD），不實作多幣別。
