# 01 — Spec：產品定價測試頁面

## 1. 模型變更

### 1.1 `dms.product.installment.line` — 新增欄位

| 欄位 | 類型 | 說明 |
|---|---|---|
| `finance_company` | Char | 分期公司名稱（如：和潤、遠信、中信卡），自由輸入 |

- 選填，無唯一限制
- 搭配 `periods` + `monthly_payment` 一起顯示

---

## 2. 新增視圖：`views/product_pricing_test_views.xml`

### 2.1 列表視圖（`view_product_pricing_test_tree`）

顯示欄位：內部代碼、車種（template_id）、年份、現金價、分期筆數（installment_line_count）

### 2.2 表單視圖（`view_product_pricing_test_form`）

**單頁式佈局，無 notebook tab**：

```
[標題]  內部代碼

[基本資訊區]
  左：模板 / 年份 / 啟用
  右：品牌 / 車種名稱 / 能源

[售價區]
  牌價 | 現金直扣 | 現金價（computed: 牌價 − 直扣）
  活動價 | 活動說明

[顏色區]
  inline editable list（名稱 / 啟用）

[分期方案區]  ← 核心測試區
  editable list：
  - 分期公司（新欄位）
  - 期數
  - 月付金（computed, readonly）
  - 設定費
  - 開辦費
  - 備註
```

### 2.3 action（`action_product_pricing_test`）

- model: `dms.product`
- views: tree + form（使用測試專用視圖）

---

## 3. 選單

```
產品及零件管理
├── 車型產品
│   └── 產品頁面
├── 零件管理
│   ├── 零件清單
│   └── 零件分類
└── 測試頁面           ← 新增，sequence=30
    └── 定價測試       ← action_product_pricing_test
```

---

## 4. 注意事項

- 本測試頁面為暫時性 UI 實驗，確認方向後將整合回正式產品頁或另建正式需求
- `finance_company` 欄位為永久新增（後續正式頁面也需要），不會刪除
- 不修改現有 `product_sku_views.xml` 或任何已有 action
