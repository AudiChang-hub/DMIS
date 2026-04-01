# 00 — Charter：產品定價簡化（017-dms-product-pricing-simplify）

## 背景與動機

目前 DMIS 的定價架構繼承自「版本管控」設計（`dms.price.version` → `dms.price.line`），
並透過 `dms.installment.rule.binding` 中間表將分期規則掛接到（版本，產品）組合上。
這個設計在「需要提前準備下期價格、特定日期上線」的業務前提下有其合理性，
但實際業務情境是：

1. **原廠穩價機制**：車款售價由原廠決定並直接通知，幾乎不會有「提前排定未來價格」的需求。
2. **無版本切換流程**：價格變動時直接套用新價格，不需要草稿→生效→封存的版本生命周期。
3. **活動特殊價**：原廠偶爾推出限時活動，提供特殊折扣或補助，依舊由原廠給定金額，業務人員直接填入即可；活動結束後清除。
4. **維護流程繁瑣**：目前新增一台車需跳三個選單（產品 → 價目版本 → 規則掛接），容易漏設定。

## 目標

1. **一站式維護**：在 `dms.product`（SKU）表單的同一頁面完成「目前售價 + 活動特殊價 + 分期規則」的所有設定。
2. **廢棄版本架構**：移除 `dms.price.version`、`dms.price.line`、`dms.installment.rule.binding`，改為直接欄位。
3. **保留異動歷史**：價格變更時系統自動寫入稽核日誌（`dms.product.price.log`），供追溯查詢，但使用者不需主動管理。
4. **向下相容**：既有 `dms.sale.order` 查價邏輯改為直接讀 `dms.product.cash_price`，行為與現行相同或更簡單。

## 範圍

| 包含 | 不包含 |
|---|---|
| `dms.product` 新增 `cash_price`, `list_price`, `promo_price`, `promo_note`, `installment_rule_ids` | 修改 `dms.installment.rule` 規則內容 |
| 新模型 `dms.product.price.log`（自動稽核） | 報表或 BI 邏輯 |
| Migration：舊 `price.version/line` 資料轉移至新欄位 | 修改 `dms_core` 凍結模組 |
| Migration：舊 binding 轉為 M2M | 費用類型（`dms.fee.type`）相關調整 |
| `dms_sale` 查價 onchange 改為讀 `product.cash_price` | `dms.ev.fee.schedule` 電車牌險費邏輯 |
| 廢棄舊三個 model + 對應選單 | 分期規則模板（`dms.installment.rule`）本身的內部結構 |

## 成功指標

- 設定一台新車的完整定價：**從跳 3 個畫面減少為 1 個畫面**
- 活動特殊價：在產品頁直接填寫，訂單查價時若 `promo_price > 0` 則優先使用
- 所有既有測試通過，`make smoke` OK
- 舊資料（`dms.price.line`）完整轉移，資料不遺失

## 約束

- `dms_core` 凍結，不得直接修改
- 本次變動屬 **breaking change**，須附帶 migration script
- 廢棄的 model 先以 `_description = '已廢棄'` 保留空殼一個版本，下一 PR 再移除（確保 DB 欄位安全清除）
