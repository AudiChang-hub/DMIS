# 04 — Tasks：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## Phase 1：Spec 與設計

- [x] 建立 016 charter/spec/clarify/plan/tasks/acceptance

## Phase 2：Wizard 實作

- [x] 建立 `dms.visit.bulk.create.wizard`
- [x] 建立 wizard form view
- [x] 新增 wizard access control
- [x] 將 wizard 載入 `__manifest__.py`

## Phase 3：入口與流程

- [x] 在 `dms.visit` 新增開啟 wizard 方法
- [x] 在拜訪表單新增 `批次選擇車行` 入口
- [x] 在拜訪清單/行事曆提供批次建立入口
- [x] 批次建立後刷新當前畫面

## Phase 4：測試與文件

- [x] 新增 wizard 批次建立測試
- [x] 回歸既有拜訪測試
- [x] 更新 `docs/USER_MANUAL.md`
- [x] 執行模組升級、smoke 驗證
