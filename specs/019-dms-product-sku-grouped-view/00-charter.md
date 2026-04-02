# Spec 019 — 產品 SKU 群組折疊總覽

## 背景
目前「產品頁面」列表顯示 `dms.product.template`（大項目），使用者須逐一點進每筆記錄才能查看底下所有 SKU 的年份、顏色與售價。

## 目標
在「車型產品」選單下新增一個「**SKU 折疊總覽**」入口：
- 以 `dms.product`（SKU）為資料來源
- 預設依「產品模板（`template_id`）」分組，可折疊/展開
- 展開後直接顯示每個 SKU 的年份、顏色、現金售價、牌價、活動特殊價、有效售價
- 每行附「開啟」按鈕，可進入現有 4-Tab 操作對話框（定價 / 分期 / 日誌）

## 範圍
| 類型 | 說明 |
|---|---|
| 新增 view | `view_product_sku_grouped_tree`（dms.product） |
| 新增 action | `action_product_sku_grouped` |
| 新增選單 | 「SKU 折疊總覽」under 車型產品 |
| 不修改 | 現有模板列表 / 模板表單 / SKU dialog |
