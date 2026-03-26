# 013-dms-catalog — 功能規格（01-spec）

## 1. 模型設計

### 1.1 `dms.product.template`（產品型式）

> 描述一款機種的基本特性（不含顏色、年份）。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `brand_id` | Many2one(`dms.brand`) | 品牌，必填 |
| `name` | Char | 型式名稱，必填（例：FORCE 2.0）|
| `model_code` | Char | 原廠型號代碼 |
| `energy_type` | Selection(`oil`/`electric`) | 能源型式，必填 |
| `brake_type` | Char | 煞車型式 |
| `engine_displacement` | Float | 排氣量（cc）|
| `fuel_tank` | Float | 油箱容量（L）|
| `engine_type` | Char | 引擎型式 |
| `consumption_grade` | Char | 油耗等級 |
| `efficiency` | Float | 燃油效率（km/L）|
| `max_hp` | Float | 最大馬力 |
| `max_torque` | Float | 最大扭力 |
| `power_system` | Char | 電力系統 |
| `max_output` | Float | 最大輸出（kW）|
| `ev_max_hp` | Float | 電車最大馬力 |
| `ev_max_torque` | Float | 電車最大扭力 |
| `ev_efficiency` | Float | 電車效率（km/kWh）|
| `transmission` | Char | 變速方式 |
| `battery_capacity` | Float | 電池容量（kWh）|
| `battery_type` | Char | 電池型式 |
| `charge_time` | Float | 充電時間（小時）|
| `dimensions` | Char | 車身尺寸（長×寬×高 mm）|
| `seat_height` | Float | 坐高（mm）|
| `wheel_base` | Float | 軸距（mm）|
| `vehicle_weight` | Float | 整備重量（kg）|
| `tire_front` | Char | 前輪規格 |
| `tire_rear` | Char | 後輪規格 |
| `image_1920` | Binary | 產品主圖（image.mixin）|
| `active` | Boolean | 啟用，預設 True |
| `sku_ids` | One2many(`dms.product.sku`) | SKU 清單 |

---

### 1.2 `dms.product.sku`（SKU）

> 描述同一型式的特定顏色 × 年份組合，對應實際販售商品。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `template_id` | Many2one(`dms.product.template`) | 所屬型式，必填 |
| `color` | Char | 顏色名稱 |
| `color_code` | Char | 色碼（例：Pearl White / #FFFFFF）|
| `manufacture_year` | Char | 出廠年份（例：2026）|
| `sku_code` | Char | 唯一 SKU 代碼，系統自動生成或手動輸入 |
| `image_1920` | Binary | SKU 專屬圖（image.mixin）|
| `active` | Boolean | 啟用，預設 True |

**限制**：`(template_id, color_code, manufacture_year)` 三者組合不得重複（`_sql_constraints`）。

---

### 1.3 `dms.price.version`（定價版本）

> 管理定價的版本歷程。同一 SKU 可存在多個版本；系統以 `effective_date` 排序，下一版本的生效日即為本版本的結束日。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `name` | Char | 版本名稱（例：2026-06 標準版）|
| `effective_date` | Date | 生效日期，必填 |
| `state` | Selection(`draft`/`active`/`archived`) | 狀態 |
| `note` | Text | 備註 |
| `line_ids` | One2many(`dms.price.line`) | 定價明細 |

---

### 1.4 `dms.price.line`（定價明細）

> 記錄特定 SKU 在特定版本下的售價。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `version_id` | Many2one(`dms.price.version`) | 所屬版本，必填 |
| `sku_id` | Many2one(`dms.product.sku`) | SKU，必填 |
| `cash_price` | Float | 現金售價 |
| `list_price` | Float | 牌價（建議售價）|
| `is_promotion` | Boolean | 當期活動價 |
| `note` | Text | 備註 |
| `installment_rule_ids` | Many2many(`dms.installment.rule`) | 適用分期規則 |

**限制**：`(version_id, sku_id)` 不得重複。

---

### 1.5 `dms.installment.rule`（分期規則範本）

> 可複用的分期規則，與 SKU/版本無耦合，可跨多個定價明細共用。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `name` | Char | 規則名稱，必填 |
| `finance_company` | Char | 分期公司 |
| `active` | Boolean | 啟用，預設 True |
| `note` | Text | 備註 |
| `line_ids` | One2many(`dms.installment.rule.line`) | 分期明細 |

---

### 1.6 `dms.installment.rule.line`（分期規則明細）

> 每條代表一個期數設定。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `rule_id` | Many2one(`dms.installment.rule`) | 所屬規則，必填 |
| `periods` | Integer | 期數，必填（例：6、12、24、36）|
| `monthly_payment` | Float | 月付金 |
| `fee_ids` | One2many(`dms.installment.rule.fee`) | 費用明細 |

---

### 1.7 `dms.fee.type`（費用類型主檔）

> 可擴充的費用分類（例：開辦費、設定費等）。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `name` | Char | 費用名稱，必填 |
| `code` | Char | 費用代碼（簡寫，例：SETUP、OPEN）|
| `active` | Boolean | 啟用，預設 True |

---

### 1.8 `dms.installment.rule.fee`（分期費用明細）

> 掛載於 `dms.installment.rule.line` 下，記錄各費用金額。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `rule_line_id` | Many2one(`dms.installment.rule.line`) | 所屬明細行，必填 |
| `fee_type_id` | Many2one(`dms.fee.type`) | 費用類型，必填 |
| `amount` | Float | 金額 |
| `charge_method` | Selection(`flat`/`rate`) | 計費方式：固定金額 / 比例 |

---

### 1.9 保留既有模型（不做 migration，原模型繼續存在）

以下模型從 `dms_pricelist` 搬移至 `dms_catalog`，邏輯不變：

| 模型 | 說明 |
|---|---|
| `dms.accessory` | 精品售價 |
| `dms.accessory.price`（若存在）| 精品歷史定價 |
| `dms.ev.fee.schedule` | 電車牌險費率 |
| `dms.commission.rule` | 傭金規則 |

---

## 2. 向下相容橋接（Backward Compatibility）

為確保 `dms_sale`、`dms_finance`、`dms_visit` 等依賴模組繼續運作，新模組需透過下列橋接策略處理：

### 2.1 `dms.product` 相容層

保留 `dms.product` 模型名稱作為**唯讀捷徑視圖**（`_auto = False` + `_sql_constraints` 可選），或透過 computed 欄位橋接到 `dms.product.sku`，讓現有 Many2one('dms.product') 的欄位在遷移前不報錯。

> 實作決策：在切換 `dms_sale` 等模組時再評估是否需要此層。目前 alpha 版先保留兩個模型共存。

### 2.2 `dms.vehicle.price` 相容層

保留 `dms.vehicle.price` 模型定義（設為 deprecated），讓已安裝的 `dms_sale` 在升級前不報 missing table 錯誤。

---

## 3. 業務流程

```
品牌（dms.brand / dms_core）
  └── 型式（dms.product.template）
        └── SKU（dms.product.sku）
              └── 定價明細（dms.price.line）
                    ├── 版本（dms.price.version）
                    └── 分期規則（dms.installment.rule）
                          └── 規則明細（dms.installment.rule.line）
                                └── 費用（dms.installment.rule.fee → dms.fee.type）
```

---

## 4. 視圖需求

| 視圖 | 類型 | 說明 |
|---|---|---|
| `dms.product.template` | List / Form / Kanban | 型式管理，Kanban 卡片顯示可配置欄位 |
| `dms.product.sku` | List / Form | SKU 管理，含型式展開 |
| `dms.price.version` | List / Form | 版本管理，含明細 One2many |
| `dms.price.line` | 嵌入 version Form | 定價明細表 |
| `dms.installment.rule` | List / Form | 分期規則管理 |
| `dms.fee.type` | List / Form | 費用類型主檔 |
| `dms.accessory` | List / Form | 精品管理（保留原有視圖樣式）|
| `dms.ev.fee.schedule` | List / Form | 電車牌險費率（保留）|
| `dms.commission.rule` | List / Form | 傭金規則（保留）|

---

## 5. Kanban 設定

延續 `dms_product` 的 `dms.kanban.product.config` 概念，搬移至 `dms_catalog`，作用於 `dms.product.template` Kanban 視圖。欄位映射維持不變。

---

## 6. 安全權限

| 群組 | 模型 | CRUD |
|---|---|---|
| `dms_catalog.group_catalog_manager` | 全部模型 | ✓✓✓✓ |
| `dms_catalog.group_catalog_user` | template / sku / price | R___（唯讀）|
| `base.group_user` | 無 | — |

---

## 7. 資料遷移策略

遷移腳本放置於 `dms_catalog/data/migration/` 目錄：

1. `migrate_product.py`：`dms.product` → 映射到 `dms.product.template` + `dms.product.sku`
2. `migrate_price.py`：`dms.vehicle.price` → `dms.price.version` + `dms.price.line`；`dms.installment.plan` → `dms.installment.rule` + `dms.installment.rule.line`

遷移腳本須確保冪等性（可重複執行不會產生重複資料）。
