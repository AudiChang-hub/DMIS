# 00 — Charter：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## 背景

現行 `dms.visit` 採單筆拜訪對應單一車行的資料模型，適合追蹤單次拜訪紀錄，但在實務排程上，業務人員經常需要在同一天安排多間車行，且共用同一位拜訪人員與相同拜訪目的。若仍透過單筆表單逐一選車行，建立成本過高，容易造成排程輸入阻力。

## 目標

在不改變 `dms.visit` 單筆單車行資料語意的前提下，新增一個可由拜訪行事曆/拜訪表單呼叫的批次建立流程，讓使用者可以：

- 一次多選多間車行
- 套用相同的拜訪日期
- 套用相同的拜訪人員
- 套用相同的拜訪目的
- 一次建立多筆 `dms.visit`

## 原則

1. 不將 `dms.visit.dealer_id` 改為多選欄位。
2. 不破壞既有拜訪清單、拜訪行事曆、權限與 record rule。
3. 批次建立後的結果仍是標準 `dms.visit` 紀錄，每筆僅對應一個車行。
4. UI 以最小侵入方式新增，不重寫現有拜訪表單主流程。

## 範圍

### In Scope

- `dms.visit` 新增開啟批次建立精靈的方法
- `dms.visit.bulk.create.wizard` transient model
- 批次選擇車行並統一帶入 `visit_date`、`visitor_id`、`purpose_id`
- 拜訪行事曆/拜訪表單的批次建立入口
- 對應測試、文件與驗收更新

### Out of Scope

- 改寫 `dms.visit` 主模型為多車行單筆紀錄
- 調整自動拜訪排程 `dms.visit.schedule` 的建立邏輯
- 改變既有 `dms.visit` record rule
- 批次建立送出物品明細
