# 04 — Tasks：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## Phase 1：Spec 與設計

- [x] 建立 016 charter/spec/clarify/plan/tasks/acceptance

## Phase 2：Wizard 實作

- [x] 建立 `dms.visit.bulk.create.wizard`
- [x] 建立 wizard form view
- [x] 新增 wizard access control
- [x] 將 wizard 載入 `__manifest__.py`

## Phase 3：入口與流程

- [x] 批次建立入口保留於主選單
- [x] 單筆拜訪表單維持原有欄位流程，不嵌入批次按鈕
- [x] 批次建立後刷新當前畫面

## Phase 4：測試與文件

- [x] 新增 wizard 批次建立測試
- [x] 回歸既有拜訪測試
- [x] 更新 `docs/USER_MANUAL.md`
- [x] 執行模組升級、smoke 驗證
