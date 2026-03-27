# 規格（01-spec）— dms_pricelist 價目管理模組

> 歷史文件註記（2026-03-27）：此規格描述的是 `dms_pricelist` 獨立存在時的設計。現況已整併至 `dms_sale`，請以 [`specs/006-dms-sale/01-spec.md`](/home/audi/project/DMIS/specs/006-dms-sale/01-spec.md) 與 [`specs/014-module-removal/01-spec.md`](/home/audi/project/DMIS/specs/014-module-removal/01-spec.md) 為準。

## 模組資訊
| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_pricelist` |
| 顯示名稱 | DMS 價目管理 |
| 版本 | 16.0.1.0.0 |
| 依賴 | `dms_core`, `dms_product` |
| installable | True |
| application | True |

---

## 模型 1：`dms.vehicle.price`（車款售價）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → `dms.product` | ✓ | 車款 |
| `cash_price` | Float(12, 0) | | 現金售價 |
| `valid_year_month` | Char | | 有效月份（格式 YYYY-MM） |
| `is_promotion` | Boolean | | 當月活動 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |
| `installment_ids` | One2many → `dms.installment.plan` | | 分期方案明細 |

`_rec_name = 'product_id'`，`_order = 'product_id, valid_year_month desc'`

> 設計說明：車款售價為市場底價，不綁車行。車行銷售差異由 `dms_sale` 處理。

---

## 模型 2：`dms.installment.plan`（分期方案）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `price_id` | Many2one → `dms.vehicle.price` | ✓ | 所屬車款售價（ondelete=cascade） |
| `installment_periods` | Integer | ✓ | 分期期數 |
| `installment_monthly` | Float(12, 0) | | 月付金 |
| `finance_company` | Char | | 分期公司 |
| `active` | Boolean | | 啟用（default=True） |

`_rec_name = 'price_id'`，`_order = 'price_id, installment_periods'`

> 設計說明：無獨立選單，僅透過車款售價 form 的 One2many 欄位維護。

---

## 模型 3：`dms.accessory`（精品售價）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 精品名稱 |
| `model_number` | Char | | 型號 |
| `unit_price` | Float(12, 0) | | 單價 |
| `install_fee` | Float(12, 0) | | 安裝費 |
| `bundle_name` | Char | | 套裝組合名稱 |
| `valid_from` | Date | | 有效起始 |
| `valid_to` | Date | | 有效截止 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |

`_order = 'name'`

> 設計說明：原「精品品項 + 精品售價」兩層合併為單一扁平模型。

---

## 模型 4：`dms.ev.fee.schedule`（電車牌險費率）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → `dms.product` | ✓ | 車款（domain: energy_type=electric） |
| `fee_vehicle_registration` | Float(12, 0) | | 代繳行照費 |
| `fee_inspection` | Float(12, 0) | | 代繳檢驗費 |
| `fee_plate` | Float(12, 0) | | 代繳號牌費 |
| `fee_stamp` | Float(12, 0) | | 代繳刻印費 |
| `fee_insurance` | Float(12, 0) | | 代繳保險費 |
| `fee_guild_cert` | Float(12, 0) | | 公會證明費 |
| `fee_document` | Float(12, 0) | | 文件處理費 |
| `fee_other` | Float(12, 0) | | 其他 |
| `fee_total` | Float（compute，store=True） | | 合計（自動加總） |
| `valid_from` | Date | | 有效起始 |
| `valid_to` | Date | | 有效截止 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |

`_rec_name = 'product_id'`，`_order = 'product_id, valid_from desc'`

> 設計說明：僅維護電車固定費率。Form view 頂部顯示提示：「油車牌險費：依監理站換發單據計算，請於銷售紀錄中填入實際金額。」

---

## 模型 5：`dms.commission.rule`（傭金規則）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `dealer_id` | Many2one → `dms.dealer` | ✓ | 車行 |
| `product_id` | Many2one → `dms.product` | | 車款（留空=適用全部） |
| `installment_periods` | Integer | | 分期期數（0=現金） |
| `commission_amount` | Float(12, 0) | | 傭金金額 |
| `commission_rate` | Float(6, 2) | | 傭金比例（%） |
| `valid_from` | Date | | 有效起始 |
| `valid_to` | Date | | 有效截止 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |

`_rec_name = 'dealer_id'`，`_order = 'dealer_id, product_id, installment_periods'`

---

## 視圖規範

每個主模型皆需：**tree**（所有欄位 optional）、**form**（分組佈局）、**search**（啟用中/已歸檔篩選）

依 UI 標準：
- active 欄位 `optional="show"`
- 所有欄位皆出現在 tree（One2many 除外）
- search view 必須有「啟用中」和「已歸檔」篩選器
- `dms.ev.fee.schedule` form 頂部有油車提示橫幅
- `dms.installment.plan` 無獨立視圖，僅 vehicle.price form 內 One2many

## 選單架構

```
DMS 價目管理（menu_dms_pricelist_root，頂層）
  ├── 車款售價（sequence=10）→ action_vehicle_price
  ├── 精品售價（sequence=20）→ action_accessory
  ├── 電車牌險費率（sequence=30）→ action_ev_fee_schedule
  └── 傭金規則（sequence=40）→ action_commission_rule
```

## ACL

所有模型均開放全員讀寫（與 dms_core 相同策略）：

| model | group | R | W | C | D |
|---|---|---|---|---|---|
| dms.vehicle.price | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.installment.plan | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.accessory | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.ev.fee.schedule | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.commission.rule | 全員 | ✓ | ✓ | ✓ | ✓ |
