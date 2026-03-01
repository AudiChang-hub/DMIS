# 規格（01-spec）— dms_pricelist 價目管理模組

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
| `dealer_id` | Many2one → `dms.dealer` | | 車行（留空=適用全部） |
| `cash_price` | Float(12, 0) | | 現金售價 |
| `installment_periods` | Integer | | 分期期數（0=不適用） |
| `installment_monthly` | Float(12, 0) | | 月付金 |
| `finance_company` | Char | | 分期公司 |
| `valid_year_month` | Char | | 有效月份（格式 YYYY-MM） |
| `is_promotion` | Boolean | | 當月活動 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |

`_rec_name = 'product_id'`，`_order = 'product_id, installment_periods'`

---

## 模型 2：`dms.accessory`（精品品項）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 精品名稱 |
| `model_number` | Char | | 型號 |
| `active` | Boolean | | 啟用（default=True） |
| `price_ids` | One2many → `dms.accessory.price` | | 售價記錄 |

查詢表（lookup table），`_order = 'name'`

---

## 模型 3：`dms.accessory.price`（精品售價）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `accessory_id` | Many2one → `dms.accessory` | ✓ | 精品品項（ondelete=cascade） |
| `unit_price` | Float(12, 0) | | 單價 |
| `install_fee` | Float(12, 0) | | 安裝費 |
| `bundle_name` | Char | | 套裝組合名稱 |
| `valid_from` | Date | | 有效起始 |
| `valid_to` | Date | | 有效截止 |
| `active` | Boolean | | 啟用（default=True） |

`_rec_name = 'accessory_id'`，`_order = 'accessory_id, valid_from desc'`

---

## 模型 4：`dms.fee.schedule`（牌險費率）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → `dms.product` | ✓ | 車款 |
| `fee_registration` | Float(12, 0) | | 領牌費 |
| `fee_compulsory_insurance` | Float(12, 0) | | 強制險 |
| `fee_agency` | Float(12, 0) | | 代辦費 |
| `valid_from` | Date | | 有效起始 |
| `valid_to` | Date | | 有效截止 |
| `active` | Boolean | | 啟用（default=True） |
| `note` | Text | | 備註 |

`_rec_name = 'product_id'`，`_order = 'product_id, valid_from desc'`

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

每個模型皆需：**tree**（所有欄位 optional）、**form**（分組佈局）、**search**（啟用中/已歸檔篩選）

依 UI 標準：
- active 欄位 `optional="show"`
- 所有欄位皆出現在 tree（One2many 除外）
- search view 必須有「啟用中」和「已歸檔」篩選器
- `dms.accessory` 為 lookup table：`name`/`active` 均 `optional="show"`

## 選單架構

```
DMS 價目管理（menu_dms_pricelist_root，頂層）
  ├── 車款售價（sequence=10）→ action_vehicle_price
  ├── 精品品項（sequence=20）→ action_accessory
  ├── 精品售價（sequence=30）→ action_accessory_price
  ├── 牌險費率（sequence=40）→ action_fee_schedule
  └── 傭金規則（sequence=50）→ action_commission_rule
```

## ACL

所有模型均開放全員讀寫（與 dms_core 相同策略）：

| model | group | R | W | C | D |
|---|---|---|---|---|---|
| dms.vehicle.price | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.accessory | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.accessory.price | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.fee.schedule | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.commission.rule | 全員 | ✓ | ✓ | ✓ | ✓ |
