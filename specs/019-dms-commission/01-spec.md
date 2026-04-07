# 019-dms-commission 規格（01-spec）

> 最後更新：2026-04-07（配合實作同步）

## 模組資訊

| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_commission` |
| 顯示名稱 | DMS 傭金管理 |
| 依賴 | `dms_core`, `dms_product`, `dms_sale`, `dms_parts` |
| 頂層選單 | `menu_dms_commission_root`，name="傭金管理"，sequence=50 |

---

## 一、模型規格

### 1. `dms.commission.rule`（基礎傭金規則）

每個車型定義一條通用基礎傭金，作為所有計算的底數。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `product_tmpl_id` | Many2one → `dms.product.template` | 車型，必填 |
| `base_amount` | Monetary | 基礎傭金金額，必填，≥ 0 |
| `currency_id` | Many2one → `res.currency` | 幣別，預設 TWD |
| `note` | Text | 備註，可空 |

**限制**：`product_tmpl_id` 唯一（同一車型只能有一條基礎規則）。

---

### 2. `dms.commission.dealer.rule`（車行覆蓋規則）

特定車行在基礎傭金之上套用**固定加碼**，可限定品牌與能源型式，並可附帶實物激勵明細。
一條規則可套用多個車行（Many2many）。

> ⚠️ 架構異動記錄（2026-04-07）：
> 原設計為 dealer_id（單一）× product_tmpl_id（必填）× formula_type，
> 已重構為 dealer_ids（M2M）× brand_id + energy_type 篩選 × addon_amount 固定加碼，
> 並移除 formula_type/addon_percent，加入實物激勵明細子表。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `name` | Char | 自動計算（車行名稱 ／ 品牌 ／ 能源型式），store=True |
| `dealer_ids` | Many2many → `dms.dealer` | 適用車行，必填（可多選） |
| `brand_id` | Many2one → `dms.brand` | 限定品牌（空 = 所有品牌） |
| `energy_type` | Selection | 限定能源型式（空 = 油車+電車都適用）；`oil`/`electric` |
| `addon_amount` | Float | 每台固定加碼金額（正數加碼，負數扣減） |
| `incentive_line_ids` | One2many → `dms.commission.dealer.rule.incentive.line` | 實物激勵明細（每台結案後附帶的零件） |
| `incentive_summary` | Char | 實物激勵摘要（compute，如 機油 ×1、零件 ×2） |
| `note` | Text | 備註 |

**子表模型 `dms.commission.dealer.rule.incentive.line`**：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `sequence` | Integer | 排序，預設 10 |
| `rule_id` | Many2one → `dms.commission.dealer.rule` | 所屬規則，必填 |
| `part_id` | Many2one → `dms.part` | 零件，必填（來自 dms_parts） |
| `quantity` | Float | 每台給出數量，預設 1.0 |

**篩選方法 `is_applicable_for(tmpl)`**：品牌 + 能源型式雙重篩選，回傳 bool。

---

### 3. `dms.commission.volume.rule`（台數獎金規則）

當月車行達到門檻台數後，每台結案訂單額外加碼。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `name` | Char | 規則名稱，必填 |
| `dealer_ids` | Many2many → `dms.dealer` | 適用車行（空 = 全部車行） |
| `brand_id` | Many2one → `dms.brand` | 限定品牌（空 = 不限）；設定後只計算該品牌台數 |
| `product_tmpl_ids` | Many2many → `dms.product.template` | 限定車型（空 = 不限） |
| `energy_type` | Selection | 限定能源型式（空 = 不分）；`oil`/`electric` |
| `min_qty` | Integer | 月達標門檻台數，必填，≥ 1 |
| `bonus_per_unit` | Float | 達標後每台加碼金額，必填，> 0 |
| `date_from` | Date | 規則生效起日（空 = 無限制） |
| `date_to` | Date | 規則生效迄日（空 = 無限制） |
| `active` | Boolean | 預設 True |
| `rule_type` | Selection | 系統自動判斷：有指定車行 = `specific`；否則 = `general`（compute，store） |
| `note` | Text | 備註 |

---

### 4. `dms.commission.record`（傭金計算記錄）

訂單結案時自動寫入，存放計算結果，不允許手動新增/刪除。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `sale_order_id` | Many2one → `sale.order` | 對應銷貨訂單，必填，唯一 |
| `dealer_id` | Many2one → `dms.dealer` | 車行（從訂單複製） |
| `product_tmpl_id` | Many2one → `dms.product.template` | 車型（從訂單複製） |
| `closed_date` | Datetime | 結案時間 |
| `closed_month` | Char | 月份字串，格式 `YYYY-MM`（compute，store=True） |
| `base_commission` | Monetary | 基礎或車行覆蓋後的傭金 |
| `volume_bonus` | Monetary | 台數獎金（0 = 未達標或無規則） |
| `total_commission` | Monetary | `base_commission + volume_bonus` |
| `currency_id` | Many2one → `res.currency` | 幣別 |
| `state` | Selection | `active`（正常）/ `voided`（已撤銷） |

**計算邏輯（`_compute_commission`）**：
1. 查 `dms.commission.dealer.rule`：找 `(dealer_id, product_tmpl_id)` 匹配的覆蓋規則
2. 若無覆蓋，查 `dms.commission.rule`：找 `product_tmpl_id` 匹配的基礎規則
3. 查 `dms.commission.volume.rule`：找所有適用車行 + 本月 + 車型/能源別的規則
4. 計算當月同車行已結案（`state=active`）訂單數，判斷是否達標

**重算邏輯**：每次結案或撤銷，取同車行同月份所有 `state=active` 的 record，重新執行步驟 3-4 並更新 `volume_bonus`。

---

### 5. `dms.incentive.type`（激勵品項類型）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `name` | Char | 品項名稱，必填（如：機油、紅包、刮刮卡） |
| `type` | Selection | `physical`（實物）/ `voucher`（憑證）/ `points`（點數） |
| `active` | Boolean | 預設 True |
| `note` | Text | 備註 |

---

### 6. `dms.incentive.rule`（激勵觸發規則）

定義哪些車行在哪些條件下應給予什麼激勵。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `name` | Char | 規則名稱，必填 |
| `incentive_type_id` | Many2one → `dms.incentive.type` | 激勵品項，必填 |
| `dealer_ids` | Many2many → `dms.dealer` | 適用車行（空 = 全部） |
| `product_tmpl_ids` | Many2many → `dms.product.template` | 限定車型（空 = 不限） |
| `trigger` | Selection | `per_unit`（每台）/ `volume`（達門檻） |
| `min_qty` | Integer | 門檻台數（僅 `trigger=volume` 時使用） |
| `qty_per_trigger` | Integer | 每次觸發給幾個，預設 1 |
| `date_from` | Date | 生效起日 |
| `date_to` | Date | 生效迄日 |
| `active` | Boolean | 預設 True |
| `note` | Text | 備註 |

---

### 7. `dms.incentive.delivery`（激勵核銷記錄）

一台已結案訂單對應一條激勵核銷記錄（每種激勵品項各一筆）。訂單結案時自動產生，不允許手動新增。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `sale_order_id` | Many2one → `dms.sale.order` | 對應銷貨訂單，必填 |
| `dealer_id` | Many2one → `dms.dealer` | 車行 |
| `incentive_rule_id` | Many2one → `dms.incentive.rule` | 觸發規則（激勵規則產生者） |
| `dealer_rule_line_id` | Many2one → `dms.commission.dealer.rule.incentive.line` | 來源車行覆蓋規則明細（實物折換產生者） |
| `part_id` | Many2one → `dms.part` | 零件（車行覆蓋規則折換用，如機油）；選填 |
| `incentive_type_id` | Many2one → `dms.incentive.type` | 激勵品項（激勵規則觸發用）；**選填**（與 `part_id` 擇一） |
| `qty` | Integer | 數量，必填，預設 1 |
| `state` | Selection | `pending`（待給）/ `delivered`（已給）/ `voided`（已作廢） |
| `delivery_method` | Selection | `self`（自送）/ `manufacturer`（原廠區經理）；`state=delivered` 時必填 |
| `delivered_date` | Date | 實際給出日期 |
| `delivered_by` | Char | 給出人員姓名或備註 |
| `closed_month` | Char | 月份字串（related from sale_order_id，store=True，格式 YYYY-MM） |
| `remark` | Text | 備註 |

> ⚠️ 架構調整記錄（2026-04-07）：`incentive_type_id` 已由 required 改為選填，增加 `dealer_rule_line_id` 與 `part_id` 兩個欄位，以支援車行覆蓋規則的實物折換場景。

---

### 8. `sale.order`（繼承擴充，`_inherit`）

`dms_commission` 以非侵入方式在 `sale.order` 加入以下欄位與按鈕：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `is_closed` | Boolean | 是否已結案，預設 False |
| `closed_date` | Datetime | 結案時間，自動填入 |
| `commission_record_id` | Many2one → `dms.commission.record` | 對應傭金記錄（compute，唯讀） |

**按鈕**（Form view 右上方）：
- **「結案」**：`is_closed=False` 時顯示；呼叫 `action_close_order()`
- **「撤銷結案」**：`is_closed=True` 時顯示；呼叫 `action_reopen_order()`

**`action_close_order()` 流程**：
1. 設 `is_closed=True`, `closed_date=now`
2. 建立 / 更新 `dms.commission.record`
3. 依 `dms.incentive.rule` 產生 `dms.incentive.delivery` 記錄
4. 重算同車行同月份所有 active commission record 的 `volume_bonus`

**`action_reopen_order()` 流程**：
1. 設 `is_closed=False`, `closed_date=False`
2. 將對應 `dms.commission.record.state` 設為 `voided`
3. 將對應 `dms.incentive.delivery.state` 設為 `voided`（僅 pending 者）
4. 重算同車行同月份所有 active commission record 的 `volume_bonus`

---

## 二、選單結構

```
傭金管理（sequence=50）
├── 傭金設定
│   ├── 基礎傭金規則          → dms.commission.rule tree/form
│   ├── 車行覆蓋規則          → dms.commission.dealer.rule tree/form
│   └── 台數獎金規則          → dms.commission.volume.rule tree/form
├── 激勵設定
│   ├── 激勵品項定義          → dms.incentive.type tree/form
│   └── 激勵觸發規則          → dms.incentive.rule tree/form
├── 傭金記錄                  → dms.commission.record tree（唯讀）
├── 激勵核銷                  → dms.incentive.delivery tree（可標記已給）
└── 報表
    ├── 月結報表              → wizard 選月份 → pivot/xlsx
    └── 總報表                → wizard 選日期區間 → pivot/xlsx
```

---

## 三、報表規格

### 月結報表（`dms.commission.monthly.report`，TransientModel）

Wizard 輸入：`month`（字串，格式 `YYYY-MM`）

輸出欄位（每車行一列，或每訂單一列，可切換 group）：

| 欄位 | 說明 |
|---|---|
| 車行名稱 | |
| 車型 | |
| 訂單號 | |
| 結案日期 | |
| 基礎傭金 | |
| 台數獎金 | |
| 合計傭金 | |
| 激勵品項 | 逗號分隔 |
| 激勵核銷狀態 | pending / delivered |

**Excel 匯出**：使用 Odoo `xlsx` report engine（`report_xlsx` 模組），或透過 `xlsxwriter` 直接產生 binary attachment。

### 總報表（`dms.commission.summary.report`，TransientModel）

Wizard 輸入：`date_from` / `date_to`（Date range）

輸出：同月結報表欄位，加上「月份」欄位，支援 Group By 車行。

---

## 四、權限設計

| 群組 | XML ID | 說明 |
|---|---|---|
| 傭金管理員 | `dms_commission.group_manager` | 可設定規則、查看報表、匯出、標記核銷 |
| 一般使用者 | `base.group_user` | 可查看自己車行的傭金記錄與激勵狀態（初期與管理員相同） |

初期所有登入使用者具備相同權限（`base.group_user` 讀取全部，管理員群組寫入），日後可在 `user_management` 調整。

---

## 五、資料關係圖

```
dms.product.template ──── dms.commission.rule (1:1)

dms.dealer ────────────── dms.commission.dealer.rule (many2many)
dms.brand  ─────────────┘ （brand_id / energy_type 為篩選條件）
dms.part   ─────────────── dms.commission.dealer.rule.incentive.line

dms.dealer / dms.brand ─── dms.commission.volume.rule (many2many)

dms.sale.order (is_closed) ── dms.commission.record (1:1)
                           └── dms.incentive.delivery (1:many)

dms.incentive.rule ────────── dms.incentive.delivery (激勵規則觸發)
dms.incentive.type ────────── dms.incentive.rule
                           └── dms.incentive.delivery (incentive_type_id 選填)

dms.commission.dealer.rule.incentive.line ── dms.incentive.delivery (dealer_rule_line_id + part_id)
```
