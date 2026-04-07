# 017 dms_parts — 零件管理（簡易版）

## 目標

建立最小化的零件清單模型，供傭金系統（dealer rule 實物折換）使用。
後續可擴充至目錄圖、VIN 搜尋、採購、庫存等功能。

## 模型

### dms.part.category（零件分類）
| 欄位 | 類型 | 說明 |
|---|---|---|
| name | Char | 分類名稱（油品、濾材、電瓶⋯） |
| active | Boolean | 啟用 |

### dms.part（零件）
| 欄位 | 類型 | 說明 |
|---|---|---|
| name | Char | 零件名稱 |
| part_number | Char | 料號（選填） |
| category_id | Many2one dms.part.category | 分類 |
| uom | Char | 單位（瓶、個、組） |
| cost_price | Float | 進貨成本（每單位） |
| active | Boolean | 啟用 |
| note | Text | 備註 |

## 與 dms_commission 的整合

- `dms.commission.dealer.rule.incentive.line` 的 `incentive_type_id` 替換為 `part_id (Many2one dms.part)`
- `dms.incentive.delivery` 加入選填 `part_id`，`incentive_type_id` 改為非必填（兩者擇一）
- `sale_order_ext._generate_incentive_deliveries` 從 dealer rule 明細產生 delivery 時帶入 `part_id`

## 未來擴充（本次不做）
- `dms.part.catalog`（目錄圖）：一台車型對應多張爆炸圖
- VIN 搜尋（跨維修模組）
- 庫存欄位 `stock_qty`、安全庫存警示
- 與採購模組整合
