# 演化計畫（分階段）

本計畫分為三個階段，從最小可用核心（MVP Core）到逐步擴張：

階段 1：MVP Core（穩定交易真相）
- 目標：建立最小且可信的 Core Transaction Layer（Odoo 為單一交易真相），確保資料一致性與可追溯性。
- 內容：
  - 定義 Master、Sales、Incentive、Import、Analytics 等 bounded contexts（interface 與依賴）。
  - 實作 Staging 層的匯入流程（idempotent、保留原始欄位）。
  - 建立 basic outbox pattern（將事件放入 outbox table 以供 worker_consumer 使用）。

階段 2：擴充工作流程與運算（Workers）
- 目標：移除同步計算對交易寫入的耦合，將大量計算交給獨立 worker。 
- 內容：
  - 建置 `worker-import`、`worker-compute` 服務，處理批次匯入、長時間計算與版本化重算。
  - 實作版本化規則庫（rules service / table），並支援回算。 

階段 3：分析與外部整合
- 目標：提供 Reporting Layer 與 API gateway，供 BI 與外部系統查詢與整合。
- 內容：
  - 建立 SQL View / Materialized Views 並規劃 refresh 策略。
  - 建置 API gateway（或公開 events）與外部系統整合範例。

驗收原則
- 每階段完成前需通過對應的驗收測試（smoke、資料一致性檢查、回算測試）。
- 所有變更需有 specs 更新與 PR 記錄。 
