# Spec 018 — 任務清單

## Phase 1：model（product_compat.py）
- [x] 新增 `_compute_color_summary`：從 color_ids 彙整 → 寫 `color` Char
- [x] `@api.depends('color_ids.name', 'color_ids.active')` 觸發
- [x] `store=True`（讓清單可搜尋/排序）

## Phase 2：sale_order domain
- [x] `color_id` 補 `domain="[('product_id','=',product_id)]"`
- [x] `_onchange_product_id` 已有 `self.color_id = False` ✅

## Phase 3：視圖
- [x] `product_sku_views.xml` tree：移除 `color` Char，加 `color_ids` count
- [x] `product_sku_views.xml` form：`color` Char 設 invisible
- [x] `sale_order_views.xml`：color_id domain

## Phase 4：Migration 16.0.2.0.1
- [x] `post_migrate.py` 合併同 template+year 重複 product
- [x] 重算 color summary

## Phase 5：測試 + 升級 + commit
- [x] 新測試：`test_color_summary_computed`
- [x] 新測試：`test_sale_order_color_domain`
- [x] 升級驗證 + smoke + commit + push
