# 規格（01-spec）— dms_sale 銷售管理模組

## 模組資訊

| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_sale` |
| 顯示名稱 | DMS 銷售管理 |
| 版本 | 16.0.2.0.0 |
| 依賴 | `dms_core`, `dms_customer` |
| installable | True |
| application | True |

---

## 模組定位更新（014 / 015）

自 `014-module-removal` 起，`dms_sale` 承接了原 `dms_product` / `dms_pricelist` 的核心技術模型，以維持既有交易流程不斷線：

- `dms.product`
- `dms.product.color`
- `dms.kanban.product.config`
- `dms.accessory`
- `dms.vehicle.price`
- `dms.installment.plan`
- `dms.ev.fee.schedule`
- `dms.commission.rule`

自 `015-dms-product-rebuild` 起：

- 正式的產品管理入口已移至新 `dms_product` 模組
- `dms_sale` 保留交易流程與 legacy 相容模型
- `dms.sale.order` 查價時，優先讀取 `dms_product` 提供的 `dms.price.line` 生效版本；若查無資料，再 fallback 舊 `dms.vehicle.price`

---

## 模型 1：`dms.sale.order`（銷售訂單）

### 識別區塊

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 訂單編號（自動序號 `SO{YYYYMM}{四碼}`，default='/'） |
| `order_date` | Date | ✓ | 訂單日期（default=today） |
| `sale_type` | Selection | ✓ | 交易類型：`store`=店面、`dealer`=車行（default='store'） |
| `state` | Selection | ✓ | 狀態：`draft`=草稿、`confirmed`=確認、`cancel`=取消（default='draft'） |
| `active` | Boolean | | 啟用（default=True） |

### 客戶資訊區塊

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `customer_id` | Many2one → res.partner | | 已建檔客戶（可選）；選取後 onchange 自動填入以下欄位 |
| `customer_name` | Char | ✓ | 客戶姓名（可直接填入，不需先建檔） |
| `customer_phone` | Char | | 聯絡電話 |
| `id_number` | Char（stored） | | 身分證字號（可直接填入） |
| `birthday_roc` | Char（stored） | | 民國生日（可直接填入，例：080年01月01日） |
| `address_registered` | Text（stored） | | 戶籍地址（可直接填入） |

> **UX 說明**：`customer_id` 僅為連結已建檔 Partner 的可選欄位；所有客戶資料欄位均可直接填寫，不需預先建立客戶資料。選取 `customer_id` 時 onchange 自動帶入姓名、電話、身分證、生日、戶籍地址。

### 車輛資訊區塊

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → dms.product | ✓ | 車款 |
| `product_energy_type` | Selection（related） | | 能源型式（唯讀，store=False，供 invisible 判斷） |
| `color_id` | Many2one → dms.product.color | | 顏色（domain: product_id，可選清單） |
| `engine_number` | Char | | 引擎號碼 |
| `frame_number` | Char | | 車身號碼 |
| `plate_number` | Char | | 車牌號碼 |
| `registration_date` | Date | | 領牌日期 |

### 金流區塊

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `cash_price` | Float(12,0) | | 參考售價（onchange product_id 自動帶出） |
| `amount_total` | Float(12,0) | | 實際收款價 |
| `cost` | Float(12,0) | | 成本 |
| `payment_method` | Selection | | 付款方式：`cash`=現金、`credit`=信用卡、`installment`=分期 |
| `finance_company` | Char | | 分期公司（payment_method=installment 時顯示） |
| `installment_periods` | Integer | | 分期期數（default=0） |
| `installment_monthly` | Float(12,0) | | 月付金 |

### 車行金流區塊（sale_type=dealer 時顯示）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `dealer_id` | Many2one → dms.dealer | | 車行 |
| `dealer_amount` | Float(12,0) | | 車行收款 |
| `commission` | Float(12,0) | | 傭金（onchange dealer_id/product_id/periods 自動帶出） |

### 牌險費區塊

| 欄位 | 型別 | 說明 |
|---|---|---|
| `fee_vehicle_registration` | Float(12,0) | 代繳行照費 |
| `fee_inspection` | Float(12,0) | 代繳檢驗費 |
| `fee_plate` | Float(12,0) | 代繳號牌費 |
| `fee_stamp` | Float(12,0) | 代繳刻印費 |
| `fee_insurance` | Float(12,0) | 代繳保險費 |
| `fee_guild_cert` | Float(12,0) | 公會證明費 |
| `fee_document` | Float(12,0) | 文件處理費 |
| `fee_other` | Float(12,0) | 其他 |
| `fee_plate_selection` | Float(12,0) | 選號費 |
| `fee_total` | Float（compute, store=True） | 牌險合計（以上 9 欄加總） |

> **電車**：onchange product_id 時自動從 `dms.ev.fee.schedule` 帶入全部 9 個欄位，Form 頂部顯示資訊橫幅。
> **油車**：僅顯示 3 個欄位：`fee_insurance`（強制險）、`fee_vehicle_registration`（領牌費）、`fee_other`（其他），其餘欄位隱藏，Form 頂部顯示警告橫幅。
> 未選車款（product_energy_type 為空）：牌險費欄位全部隱藏，顯示提示訊息。

### 精品與其他

| 欄位 | 型別 | 說明 |
|---|---|---|
| `order_line_ids` | One2many → dms.sale.order.line | 精品明細 |
| `deposit_amount` | Float(12,0) | 訂金 |
| `balance_amount` | Float（compute, store=True） | 尾款：amount_total - deposit_amount |
| `is_settled` | Boolean | 已結清（default=False） |
| `settle_date` | Date | 結清日期 |
| `helmet_count` | Integer | 安全帽（頂） |
| `gift_voucher` | Float(12,0) | 禮卷/匯款 |
| `gift_note` | Char | 贈品說明 |
| `special_plan` | Char | 特殊方案 |
| `note` | Text | 備註 |

`_rec_name = 'name'`，`_order = 'order_date desc, name desc'`

---

## 模型 2：`dms.sale.order.line`（精品明細）

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `order_id` | Many2one → dms.sale.order | ✓ | 所屬訂單（ondelete=cascade） |
| `sequence` | Integer | | 排序（handle widget，default=10） |
| `accessory_id` | Many2one → dms.accessory | ✓ | 精品 |
| `unit_price` | Float(12,0) | | 單價（onchange 自動帶入） |
| `install_fee` | Float(12,0) | | 安裝費（onchange 自動帶入） |
| `quantity` | Integer | | 數量（default=1） |
| `subtotal` | Float（compute, store=True） | | 小計：(unit_price + install_fee) × quantity |

`_rec_name = 'accessory_id'`，`_order = 'order_id, sequence'`

---

## 自動帶入邏輯（Onchange）

| 觸發欄位 | 目標欄位 | 來源 | 邏輯 |
|---|---|---|---|
| `product_id` | `cash_price` | `dms.price.line` / `dms.vehicle.price` | 先取 `effective_date <= 查詢日` 的最新生效版本；若無新價格，fallback 取最新 valid_year_month，active=True |
| `product_id`（電車） | 牌險費 8 欄 | `dms.ev.fee.schedule` | 取最新 valid_from，active=True |
| `dealer_id` + `product_id` + `installment_periods` | `commission` | `dms.commission.rule` | 精確匹配 dealer+product+periods；fallback 至 product=留空 |
| `accessory_id`（在 line） | `unit_price`, `install_fee` | `dms.accessory` | 直接帶出欄位值 |

---

## 狀態機

```
草稿（draft）→ 確認訂單 → 確認（confirmed）
草稿（draft）→ 取消訂單 → 取消（cancel）
確認（confirmed）→ 重回草稿 → 草稿（draft）
取消（cancel）→ 重回草稿 → 草稿（draft）
```

---

## 序號規則（ir.sequence）

| 項目 | 值 |
|---|---|
| code | `dms.sale.order` |
| prefix | `SO%(year)s%(month)s` |
| padding | 4 |
| 範例 | `SO2026030001` |

---

## 視圖規範

- **tree**：所有欄位 optional（active=show，One2many 不顯示）
- **kanban**：新增，顯示 name、state badge、customer_name、product_id、amount_total；action view_mode 改為 `kanban,tree,form`
- **form**：5 個 notebook tab（客戶與車輛、金流、牌險費、精品、其他）
- **search**：欄位搜尋 + 店面/車行/狀態篩選 + 月份 groupby

## 選單架構

```
DMS 銷售管理（menu_dms_sale_root，頂層）
  └── 銷售訂單（sequence=10）→ action_sale_order
```

## ACL

| model | group | R | W | C | D |
|---|---|---|---|---|---|
| dms.sale.order | 全員 | ✓ | ✓ | ✓ | ✓ |
| dms.sale.order.line | 全員 | ✓ | ✓ | ✓ | ✓ |
