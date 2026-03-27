# 02 — Clarify：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## 目前 repo 真實狀態

- `dms.visit` 目前是單一 `dealer_id` 的拜訪紀錄模型。
- 拜訪表單與拜訪行事曆都以單筆建立流程為主。
- `dealer_id` 使用 Many2one，因此現有搜尋視窗只能單選，無法直接支援多選車行。
- 拜訪權限已有既有 record rule：一般拜訪使用者只能看到 `visitor_id = 自己` 的紀錄。

## 問題定義

實務上同一天可能安排多間車行，而且拜訪人員與拜訪目的相同。若沿用目前單筆建立流程，需要反覆：

1. 建立拜訪
2. 選一間車行
3. 重複輸入相同的拜訪人員與目的

此流程成本過高。

## 關鍵決策

### D1：不把 `dealer_id` 改成多選

原因：

- `dms.visit` 本身代表一筆具體拜訪紀錄，單一拜訪對單一車行的語意清楚
- 既有 tree/calendar/search/record rule 都建立在此假設上
- 若直接改成多選，會破壞現有資料模型與下游使用方式

### D2：新增 transient wizard 進行批次建立

原因：

- 可在不改主模型的情況下支援一次選多間車行
- 每間車行仍落成一筆標準 `dms.visit`
- 可共用日期、拜訪人員、目的與備註

### D3：保留單筆建立流程

原因：

- 並非所有拜訪都需要批次建立
- 單筆建立仍是必要功能

## 影響分析

### 受影響

- `addons/dms_visit/models/visit.py`
- `addons/dms_visit/views/visit_views.xml`
- `addons/dms_visit/security/ir.model.access.csv`
- `addons/dms_visit/tests/test_visit.py`
- `addons/dms_visit/wizard/**`

### 不應受影響

- `dms_core` 車行管理
- `dms_visit` 自動拜訪排程 `dms.visit.schedule`
- `dms_sale` / `dms_product`
- 既有拜訪清單與拜訪行事曆的單筆編修流程

## migration / 相容策略

- 無需資料 migration
- 不修改既有 `dms.visit` 資料表結構
- 新增 wizard 與入口即可

## Open Questions

- 批次建立後是否需要立即跳回行事曆當日檢視？
  - 本輪先以「刷新當前畫面」處理，不重寫日曆導航行為

## Assumptions

- 批次建立主要使用情境是「同一天、同一人員、同一目的，多間車行」
- 批次建立後，送出物品仍由各筆拜訪再個別補充
