# 01 — Spec：財務結算模組欄位規格

## 模型：dms.sale.finance

| 欄位名稱 | 類型 | 說明 |
|---|---|---|
| `sale_order_id` | Many2one → dms.sale.order | 對應銷售訂單（必填，唯一） |
| `income_ids` | One2many → dms.sale.finance.income | 收入明細 |
| `expense_ids` | One2many → dms.sale.finance.expense | 支出明細 |
| `total_income` | Float (計算/存儲) | 收入合計 = sum(income_ids.amount) |
| `total_expense` | Float (計算/存儲) | 支出合計 = sum(expense_ids.amount) |
| `net_profit` | Float (計算/存儲) | 淨利 = total_income − total_expense |
| `note` | Text | 備註 |

## 模型：dms.sale.finance.income（收入明細）

| 欄位名稱 | 類型 | 說明 |
|---|---|---|
| `finance_id` | Many2one → dms.sale.finance | 歸屬結算（必填，cascade） |
| `type` | Selection | 收入類型（見下表） |
| `amount` | Float(12,0) | 金額（必填） |
| `note` | Char | 備註 |

### 收入類型（15 種）

| 代碼 | 名稱 |
|---|---|
| `plate_fee_income` | 牌險費收入 |
| `handling_income` | 代辦費收入 |
| `scrap_handling_income` | 報廢代辦收入 |
| `plate_selection_income` | 選號收入 |
| `used_vehicle_income` | 中古車收入 |
| `scrap_vehicle_income` | 報廢車收入 |
| `service_fee_income` | 手續費收入 |
| `yamaha_bonus_income` | 山葉獎金收入 |
| `friendly_dealer_income` | 友善車行獎金收入 |
| `other_income` | 其他收入 |
| `actual_sales_incentive` | 實銷獎勵金 |
| `promo_subsidy` | 促銷補助金 |
| `installment_subsidy` | 分期補貼息 |
| `insurance_commission` | 強制險傭金收入 |
| `credit_card_commission` | 信用卡傭金收入 |

## 模型：dms.sale.finance.expense（支出明細）

| 欄位名稱 | 類型 | 說明 |
|---|---|---|
| `finance_id` | Many2one → dms.sale.finance | 歸屬結算（必填，cascade） |
| `type` | Selection | 支出類型（見下表） |
| `amount` | Float(12,0) | 金額（必填） |
| `note` | Char | 備註 |

### 支出類型（11 種）

| 代碼 | 名稱 |
|---|---|
| `credit_card_fee` | 信用卡手續費支出 |
| `installment_fee` | 分期手續費支出 |
| `plate_fee_expense` | 牌險費支出 |
| `plate_selection` | 選號支出 |
| `used_vehicle` | 中古車支出 |
| `gift_shipping` | 贈品及運費支出 |
| `dealer_commission` | 車行傭金支出 |
| `friendly_dealer_bonus` | 友善車行獎金支出 |
| `first_sale_bonus` | 首賣獎金支出 |
| `unit_bonus` | 台數獎金支出 |
| `other_expense` | 其他支出 |

## 自動帶入預設值規則

建立 `dms.sale.finance` 時，系統從銷售訂單自動產生以下明細：

| 明細類型 | 來源欄位 | 帶入條件 |
|---|---|---|
| 支出：牌險費支出 | `fee_vehicle_registration + fee_insurance` | 合計 > 0 |
| 支出：選號支出 | `fee_plate_selection` | > 0 |
| 支出：車行傭金支出 | `commission` | > 0 |
| 收入：牌險費收入 | `fee_vehicle_registration + fee_insurance` | 合計 > 0 |

其餘項目由使用者手動新增。

## Smart Button

在 `dms.sale.order` 表單頂部加入統計按鈕，顯示財務結算筆數，點擊後：
- 若尚未建立：自動建立並帶入預設值後開啟。
- 若已建立：直接開啟現有結算記錄。

## 選單配置

- 頂部導覽：`財務結算`（主選單）
- 子選單：`財務結算` → 所有結算記錄
