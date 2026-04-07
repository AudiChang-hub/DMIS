# 017 dms_parts — 零件管理（簡易版）

> 最後更新：2026-04-07

## 目標

建立最小化的零件清單模型，供傭金系統（dealer rule 實物折換）使用。
後續可擴充至目錄圖、VIN 搜尋、採購、庫存等功能。

## 模組資訊

| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_parts` |
| 顯示名稱 | DMS 零件管理 |
| 依賴 | `dms_core` |
| 頂層選單 | 「零件管理」，置於傭金管理選單下方 |

## 模型

### `dms.part.category`（零件分類）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `name` | Char | 分類名稱（油品、濾材、電瓶⋯），必填 |
| `active` | Boolean | 啟用，預設 True |

### `dms.part`（零件）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `name` | Char | 零件名稱，必填 |
| `part_number` | Char | 原廠料號（選填） |
| `category_id` | Many2one → `dms.part.category` | 分類 |
| `uom` | Char | 單位（瓶、個、組） |
| `cost_price` | Float | 進貨成本（每單位） |
| `active` | Boolean | 啟用，預設 True |
| `note` | Text | 備註 |

## 視圖規格

- **零件清單**：tree view，所有欄位加 `optional`（`name`/`part_number`/`category_id`/`uom`/`cost_price`/`active` = show；`note` = hide）
- **零件表單**：form view，兩欄 group + 備註區
- **零件分類清單**：tree view，`name`/`active` = optional show
- **Search view（零件）**：搜尋欄（name、part_number、category_id）+ 啟用中 / 已歸檔 filter + 分類 group by
- **Search view（零件分類）**：搜尋欄（name）+ 啟用中 / 已歸檔 filter

## 權限（ACL）

```
dms_parts.access_dms_part_all          → dms.part         base.group_user rw
dms_parts.access_dms_part_category_all → dms.part.category base.group_user rw
```

## 與 dms_commission 的整合

- `dms.commission.dealer.rule.incentive.line.part_id`：必填 Many2one → `dms.part`
- `dms.incentive.delivery.part_id`：選填 Many2one → `dms.part`，從 dealer rule line 帶入
- `dms.incentive.delivery.incentive_type_id`：由原必填改為選填，與 `part_id` 擇一填寫

## 未來擴充（本次不做）

- `dms.part.catalog`（目錄圖）：一台車型對應多張爆炸圖
- VIN 搜尋（跨維修模組）
- 庫存欄位 `stock_qty`、安全庫存警示
- 與採購模組整合
