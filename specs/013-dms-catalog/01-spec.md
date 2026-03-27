# 013-dms-catalog — 功能規格（01-spec）
> **版本**：v2（2026-03-26）— 依 OQ-1~7 決策全面更新
> **狀態**：已終止，實作方向已由 `014-module-removal` 取代

> **說明**
> - 本規格代表 2026-03-26 時點的 `dms_catalog` 整併方案。
> - 自 2026-03-27 起，專案改採 `014-module-removal` 路線：移除 `dms_catalog`，並將仍需保留的產品/價目模型整併回 `dms_sale`。
> - 本檔保留作歷史決策紀錄，**不得再作為新的實作依據**。

---

## 0. 本輪範圍聲明

### ✅ 本輪（013-dms-catalog）包含
- 新增 `dms.product.series`（車系/機種主檔）
- 更新 `dms.product.template`：加入 `series_id`；`brand_id` 改為 related；圖片降級
- `dms.product.sku`（已實作，維持不變）
- `dms.price.version` / `dms.price.line`（已實作，維持不變）
- `dms.installment.rule` / `.line` / `.fee` / `dms.fee.type`（已實作，維持不變）
- 精品、電車牌險、傭金規則（搬移自 `dms_pricelist`，已實作）
- 將 `dms_product`、`dms_pricelist` 標記為 deprecated（不移除）
- UI：List 為主視圖，Kanban 降為次要

### ❌ 本輪不包含（非本輪範圍）
- `dms_sale` / `dms_visit` / `dms_finance` 的任何程式碼修改
- `dms.product.color` 的替換（保留相容，不動）
- `dms_sale` 分期欄位改為吃 `dms.installment.rule`（下一輪）
- 移除 `dms_product` / `dms_pricelist` 模組底層（只標記 deprecated）
- 移除圖片資料庫欄位（只降級視圖顯示）
- 資料遷移腳本執行（定義結構，下一輪執行）

---

## 1. 模型設計

### 1.0 `dms.product.series`（車系 / 機種主檔）【本輪新增】

> 產品識別的穩定層，介於「品牌」與「型式」之間。
> **不是** 速克達/越野車 那種粗分類，而是具有可查找識別意義的車系，例如：FORCE 系列、SMAX 系列、EC-05 系列。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `brand_id` | Many2one(`dms.brand`) | 所屬品牌，必填 |
| `name` | Char | 車系名稱，必填（例：FORCE、SMAX、EC-05）|
| `code` | Char | 識別代碼（英數，可作查找 key，例：FORCE）|
| `active` | Boolean | 啟用，預設 True |

**SQL 限制**：`(brand_id, name)` 不得重複。

---

### 1.1 `dms.product.template`（產品型式）【更新：加入 series_id，圖片降級】

> 描述一款機種的基本特性（不含顏色、年份）。

| 欄位 | 型態 | 說明 |
|---|---|---|
| `series_id` | Many2one(`dms.product.series`) | 車系，必填【本輪新增】|
| `brand_id` | Many2one(`dms.brand`) | 品牌（`related='series_id.brand_id'`，store=True）【改為 related】|
| `name` | Char | 型式名稱，必填（例：FORCE 2.0 ABS）|
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
| `image_1920` | Binary | 產品圖（image.mixin，**保留欄位；Form/List/Kanban 主要畫面均不顯示**）|
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

## 2. 向下相容策略（Backward Compatibility）

> OQ-2 決策：本輪**不遷移** `dms_sale` / `dms_visit` / `dms_finance`，保持現狀不動。

### 2.1 既有業務模組：本輪不動

- `dms_sale`、`dms_visit`、`dms_finance` 程式碼**本輪零修改**。
- 這三個模組內對 `dms.product` / `dms.vehicle.price` 的引用繼續有效（對應模型仍存在於 `dms_product` / `dms_pricelist`）。
- 遷移計劃另排下一輪 sprint。

### 2.2 `dms.product.color`（OQ-3）

保留 `dms.product.color` 主檔定義（位於 `dms_product`），本輪不強制替換。`dms.product.sku` 的 `color` 欄位維持 Char，等下一輪統一接 Many2one。

### 2.3 `dms_product` / `dms_pricelist` 退場策略（OQ-7）

| 動作 | 時機 |
|---|---|
| 在 `__manifest__.py` 加入 `# DEPRECATED` 標記與說明 | **本輪執行** |
| 停用模組預設安裝（移出 `depends`）| 本輪確認 |
| 移除模組底層程式碼 | 等 dms_sale/dms_visit/dms_finance 遷移完成後 |

> 標記方式：在 `dms_product/__manifest__.py` 與 `dms_pricelist/__manifest__.py` 的 `description` 欄位加入：
> `⚠️ DEPRECATED：功能已整併至 dms_catalog，本模組待相依模組完成遷移後移除。`

---

## 3. 業務流程

```
品牌（dms.brand / dms_core）
  └── 車系（dms.product.series）                 ← 本輪新增
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

> **UI 準則（OQ-5）：List 視圖為主要入口，Kanban 降為次要（可摺疊或頁籤切換）。圖片（image_1920）不顯示於 List / Form / Kanban 主要畫面。**

| 視圖 | 類型 | 說明 |
|---|---|---|
| `dms.product.series` | List / Form | 車系主檔管理【本輪新增】|
| `dms.product.template` | **List（主）** / Form / Kanban（次）| 型式管理；List 欄位含 series_id；Form 不顯示圖片 avatar |
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

> **OQ-5 補充**：Kanban 視圖降為次要，不得包含圖片 avatar；預設選單入口導向 List 視圖。

---

## 6. 安全權限

| 群組 | 模型 | CRUD |
|---|---|---|
| `dms_catalog.group_catalog_manager` | 全部模型 | ✓✓✓✓ |
| `dms_catalog.group_catalog_user` | template / sku / price | R___（唯讀）|
| `base.group_user` | 無 | — |

---

## 7. 資料遷移策略（本輪定義結構，下一輪執行）

遷移腳本放置於 `dms_catalog/data/migration/` 目錄：

1. `migrate_product.py`：`dms.product` → 映射到 `dms.product.template` + `dms.product.sku`
2. `migrate_price.py`：`dms.vehicle.price` → `dms.price.version` + `dms.price.line`；`dms.installment.plan` → `dms.installment.rule` + `dms.installment.rule.line`

遷移腳本須確保冪等性（可重複執行不會產生重複資料）。
