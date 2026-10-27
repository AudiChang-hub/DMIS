# 01 — Spec：產品定價測試頁面

## 1. 模型變更

### 1.1 `dms.product.installment.line` — 新增欄位（已完成）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `finance_company` | Char | 分期公司名稱（如：和潤、遠信、中信卡），自由輸入 |

### 1.2 `dms.product` — 新增欄位（v2）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `cash_discount` | Float (12,0) | 現金直扣金額，選填 |
| `installment_36_price` | Float (12,0) | 36期分期月付金，選填，手動填寫 |
| `installment_18_price` | Float (12,0) | 18期專案月付金，選填，手動填寫 |
| `gift_note` | Char | 顧客贈品說明，選填 |

---

## 2. 測試頁面視圖設計（v2）

### 2.1 測試頁面主視圖（`view_installment_group_test_tree`）

- **Model**: `dms.product`
- **群組**: 以 `template_id`（機種）為收折群組標頭
- **展開後列欄位**（全部可直接在列表內編輯）：

| 欄位 | 來源 | 備註 |
|---|---|---|
| `production_year` | 年份 | Char，可編輯 |
| `color` | 車色 | Char，可編輯 |
| `installment_36_price` | 36期分期價 | Float，手動填寫 |
| `cash_discount` | 現金直扣 | Float，可編輯 |
| `cash_price` | 現金價 | Float，可編輯 |
| `installment_18_price` | 18期專案價 | Float，手動填寫 |
| `gift_note` | 顧客贈品 | Char，可編輯 |

### 2.2 action（`action_installment_group_test`）

- model: `dms.product`
- view_mode: `tree`
- context: `{'group_by': ['template_id']}`

---

## 3. 選單

```
產品及零件管理
├── 車型產品
│   └── 產品頁面
├── 零件管理
│   ├── 零件清單
│   └── 零件分類
└── 測試頁面           ← sequence=30
    └── 定價測試       ← action_installment_group_test
```

---

## 4. 注意事項

- 本測試頁面為暫時性 UI 實驗，確認方向後將整合回正式產品頁或另建正式需求
- 新增欄位（`cash_discount`、`installment_36_price`、`installment_18_price`、`gift_note`）視測試結果決定是否整合至正式流程
- 不修改現有 `product_sku_views.xml` 或任何已有 action
