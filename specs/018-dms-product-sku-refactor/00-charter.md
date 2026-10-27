# Spec 018 — 車型產品 SKU 架構重構（Template + SKU + 顏色三層）

## 背景

目前 `dms.product` 以「品牌 + 名稱 + 年份 + 顏色」四維度定義一筆記錄，
導致同一車款的多種顏色和多個年份必須分別建立多筆資料：

```
SUI 2025 亮光灰   ← 一筆（規格重複）
SUI 2025 白色     ← 一筆（規格重複）
SUI 2026 消光灰   ← 一筆（規格重複，年份+顏色不同）
SUI 2026 白色     ← 一筆（完全重複）
```

5 色 × 2 年 = 10 筆，規格改一次要改 10 次，且每年新增一款需重複輸入。

## 目標架構

```
dms.product.template「車型」
  ├─ 存：規格（引擎、電池、車身）+ 品牌 + 機種
  └─ 不管年份、不管顏色

    ↓ one2many（sku_ids）

dms.product「年度車款 SKU」
  ├─ 存：production_year（年份）+ 定價
  ├─ template_id → dms.product.template
  └─ color_ids → dms.product.color (O2M)

    ↓（訂單選色）

dms.sale.order
  ├─ product_id → dms.product（選車款+年份）
  └─ color_id  → dms.product.color（domain 過濾至該 product）
```

## 範圍

- 模組：`dms_product`（視圖、model）、`dms_sale`（sale_order）
- **不動** `dms_core`（凍結模組）
- 資料遷移：合併舊的「一色一筆」為「一年一筆 + 多色記錄」

## 不在範圍

- `dms.product.template` 規格欄位搬移（留給後續 spec）
- `color`（Char）欄位物理刪除（暫時保留為 readonly，待所有資料遷移完畢再刪）
