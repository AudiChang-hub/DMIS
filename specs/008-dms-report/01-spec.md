# 01 — Spec：報表分析模組規格

## 資料來源

| 報表 | 模型 | 說明 |
|------|------|------|
| 銷售報表 | `dms.sale.order` | 依月份/車款統計成交金額、成本 |
| 利潤報表 | `dms.sale.finance` | 依月份統計總收入、總支出、淨利 |
| 傭金報表 | `dms.sale.order` | 依車行/月份統計傭金與成交金額 |

## 銷售報表（Pivot + Graph）

- **Pivot 預設**：列 = 訂單月份（`order_date:month`），欄 = 車款（`product_id`），量測 = `amount_total`、`cost`
- **Graph 類型**：Bar，X 軸 = 月份，Y 軸 = `amount_total`
- **Domain**：`state = confirmed`
- **可選 group_by**：`sale_type`、`dealer_id`、`product_id`、`order_date`
- **可選 measure**：`amount_total`、`cost`、`deposit_amount`

## 利潤報表（Pivot + Graph）

- **Pivot 預設**：列 = 月份（`order_date:month`），量測 = `total_income`、`total_expense`、`net_profit`
- **Graph 類型**：Bar，X 軸 = 月份，Y 軸 = `net_profit`
- **可選 group_by**：`order_date`

## 傭金報表（Pivot）

- **Pivot 預設**：列 = 車行（`dealer_id`），欄 = 月份（`order_date:month`），量測 = `commission`、`amount_total`
- **Domain**：`sale_type = dealer` AND `state = confirmed`

## 選單結構

```
報表分析 (sequence=40)
├── 銷售報表 (sequence=10)
├── 利潤報表 (sequence=20)
└── 傭金報表 (sequence=30)
```

## 依賴

- `dms_sale`：`dms.sale.order`、`dms.sale.order.line`
- `dms_finance`：`dms.sale.finance`
