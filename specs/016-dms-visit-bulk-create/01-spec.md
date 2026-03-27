# 01 — Spec：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## 1. 模型定義

### 1.1 `dms.visit.bulk.create.wizard`

用途：由拜訪行事曆或拜訪表單開啟，用於一次建立多筆拜訪紀錄。

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `visit_date` | Datetime | ✓ | 統一拜訪日期 |
| `visitor_id` | Many2one → `res.users` | ✓ | 統一拜訪人員 |
| `purpose_id` | Many2one → `dms.visit.purpose` |  | 統一拜訪目的 |
| `dealer_ids` | Many2many → `dms.dealer` | ✓ | 批次拜訪車行 |
| `note` | Text |  | 統一備註 |

規則：

- `dealer_ids` 至少需選擇一筆
- 每個選定車行各建立一筆 `dms.visit`
- 建立後每筆 `dms.visit` 都套用相同 `visit_date`、`visitor_id`、`purpose_id`、`note`
- 批次建立本身不建立 `item_ids`
- wizard 僅負責建立資料，不改動既有拜訪紀錄

### 1.2 `dms.visit`

維持既有單筆資料模型不變：

| 欄位 | 類型 | 說明 |
|---|---|---|
| `dealer_id` | Many2one → `dms.dealer` | 單一拜訪車行 |
| `visitor_id` | Many2one → `res.users` | 拜訪人員 |
| `purpose_id` | Many2one → `dms.visit.purpose` | 拜訪目的 |

新增方法：

- `action_open_bulk_create_wizard()`：開啟批次建立精靈，預帶目前表單中的日期/人員/目的

## 2. UI 規格

### 2.1 拜訪表單

- 保留原本 `dealer_id` 單選欄位，供建立單筆拜訪使用
- 在拜訪資訊區新增 `批次選擇車行` 入口
- 點擊後開啟 `dms.visit.bulk.create.wizard`
- wizard 預設帶入目前表單上的：
  - `visit_date`
  - `visitor_id`
  - `purpose_id`
  - `note`

### 2.2 拜訪行事曆 / 拜訪清單

- 提供可直接開啟批次建立精靈的入口
- 從行事曆建立時，若 context 已帶入日期，wizard 應沿用該日期

### 2.3 批次建立精靈

- 以 modal 形式顯示
- 可多選車行
- 可統一輸入拜訪日期、拜訪人員、拜訪目的、備註
- 送出後一次建立多筆 `dms.visit`
- 建立成功後關閉/刷新當前畫面，使新增紀錄可被立即看見

## 3. 安全與權限

- wizard 存取權限沿用 `dms_visit` 使用者/管理者可建立拜訪的能力
- 批次建立實際仍呼叫 `dms.visit.create()`
- 若使用者對建立後的 `visitor_id` 不符合既有 record rule，應沿用系統既有權限限制，不新增繞過機制

## 4. 相容策略

- 不修改 `dms.visit.dealer_id` 欄位型態
- 不改變拜訪清單、行事曆、搜尋、group by 的資料基礎
- 既有自動排程 `dms.visit.schedule` 不受本次影響

## 5. 驗收重點

- 可一次多選多間車行建立拜訪
- 可統一輸入拜訪人員與拜訪目的
- 建立後產生多筆標準 `dms.visit`
- 不影響既有單筆建立流程
