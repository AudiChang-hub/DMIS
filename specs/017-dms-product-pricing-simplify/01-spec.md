# 01 — Spec：產品定價簡化（017-dms-product-pricing-simplify）

## 1. 資料模型變更

### 1.1 `dms.product`（`dms_sale.models.product`）— 新增欄位

| 欄位 | 類型 | 說明 | 備註 |
|---|---|---|---|
| `cash_price` | Float (12, 0) | 現金售價（當前有效） | 原廠公告後直接填入 |
| `list_price` | Float (12, 0) | 牌價（MSRP） | 僅資訊用途 |
| `promo_price` | Float (12, 0) | 活動特殊價 | 0 = 無活動，> 0 = 啟用活動價 |
| `promo_note` | Char | 活動說明 | 如「2026 Q2 原廠補助」 |
| `installment_rule_ids` | Many2many → `dms.installment.rule` | 適用分期規則（取代 binding） | 中繼表名：`dms_product_installment_rule_rel` |
| `price_log_ids` | One2many → `dms.product.price.log` | 價格異動日誌（唯讀） | 系統自動寫入，使用者唯讀 |
| `effective_price` | Float (computed) | computed，有效售價 | `promo_price > 0` 時回傳 `promo_price`，否則 `cash_price` |

**compute 邏輯：**
```python
@api.depends('cash_price', 'promo_price')
def _compute_effective_price(self):
    for rec in self:
        rec.effective_price = rec.promo_price if rec.promo_price > 0 else rec.cash_price
```

**write() 覆寫（自動稽核）：**
修改 `cash_price` 或 `list_price` 時，自動建立一筆 `dms.product.price.log`，記錄舊值與新值。

---

### 1.2 新模型 `dms.product.price.log`

| 欄位 | 類型 | 說明 |
|---|---|---|
| `product_id` | Many2one → `dms.product` | 產品項（required, ondelete=cascade） |
| `changed_at` | Datetime | 異動時間（auto_now_add） |
| `user_id` | Many2one → `res.users` | 操作者（auto） |
| `old_cash_price` | Float (12, 0) | 舊現金價 |
| `new_cash_price` | Float (12, 0) | 新現金價 |
| `old_list_price` | Float (12, 0) | 舊牌價 |
| `new_list_price` | Float (12, 0) | 新牌價 |
| `note` | Char | 異動說明（可由使用者在儲存時填入） |

- `_order = 'changed_at desc'`
- 使用者唯讀（`readonly=True` in view），僅系統可 create

---

### 1.3 廢棄的模型（保留空殼）

| 模型 | 處置 |
|---|---|
| `dms.price.version` | 保留空殼，`_description` 加註「已廢棄，請改用 dms.product.cash_price」；選單移除 |
| `dms.price.line` | 保留空殼，同上 |
| `dms.installment.rule.binding` | 保留空殼，同上 |

> 空殼保留策略：不刪除 model 定義，僅移除選單與視圖入口，避免第一次升級時 ORM 錯誤。
> 下一 PR（018）再透過 `pre_migrate` 安全清除資料表。

---

## 2. Migration Script

位置：`addons/dms_product/migrations/16.0.2.0.0/post_migrate.py`

執行順序：
1. 讀取所有 `dms.price.line`，取同一 `product_id` 最新 `effective_date` 的版本 → 寫入 `dms.product.cash_price` 和 `list_price`
2. 讀取所有 `dms.installment.rule.binding` → 在 `dms_product_installment_rule_rel` 中繼表建立 M2M 記錄
3. 對每個 product 補寫一筆 `dms.product.price.log`（`note='Migration from dms.price.version'`）

---

## 3. `dms_sale` 查價邏輯修改

檔案：`addons/dms_sale/models/sale_order.py`

修改 `_onchange_product_id`：

**Before：**
```python
if 'dms.price.line' in self.env.registry.models:
    effective_price_line = self.env['dms.price.line'].get_effective_line(...)
if effective_price_line:
    self.cash_price = effective_price_line.cash_price
else:
    # fallback: dms.vehicle.price ...
```

**After：**
```python
# 直接讀取產品上的有效售價（effective_price = promo_price if promo_price > 0 else cash_price）
if self.product_id.cash_price:
    self.cash_price = self.product_id.effective_price
else:
    # fallback：舊 dms.vehicle.price（相容層，待 018 清除）
    price = self.env['dms.vehicle.price'].search(...)
    if price:
        self.cash_price = price.cash_price
```

---

## 4. 視圖規格

### 4.1 `dms.product` 表單視圖

新增「**定價與分期**」Tab（加在「規格」Tab 之後）：

```
[Tab: 定價與分期]
  ─── 目前售價 ─────────────────────────────────────
  現金售價          [cash_price]    牌價  [list_price]
  有效售價（唯讀）  [effective_price]

  ─── 活動特殊價 ──────────────────────────────────
  活動價            [promo_price]   活動說明 [promo_note]
  （promo_price = 0 時顯示「無活動」提示）

  ─── 適用分期規則 ──────────────────────────────────
  [Many2many tree widget: installment_rule_ids]
  欄位：規則名稱、規則明細筆數

  ─── 價格異動日誌（唯讀） ─────────────────────────
  [One2many tree: price_log_ids, readonly]
  欄位：異動時間、操作者、舊現金價→新現金價、說明
```

### 4.2 選單異動

| 動作 | 選單項目 |
|---|---|
| 移除 | 產品管理 → 價格與規則 → **價目版本** |
| 移除 | 產品管理 → 價格與規則 → **規則掛接** |
| 保留 | 產品管理 → 價格與規則 → 分期規則模板 |
| 保留 | 產品管理 → 價格與規則 → 費用類型 |

---

## 5. 版本號升級

`addons/dms_product/__manifest__.py`：`version` 從 `16.0.1.0.0` → `16.0.2.0.0`
