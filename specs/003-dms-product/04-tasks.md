# 任務清單（04-tasks）— dms_product 遷移

> 歷史文件註記（2026-03-27）：本任務清單僅保留早期拆模記錄；現行產品相關維護已併入 `dms_sale`，請改看 [`specs/014-module-removal/04-tasks.md`](/home/audi/project/DMIS/specs/014-module-removal/04-tasks.md)。

## Step 1：建立模組骨架
- [x] `addons/dms_product/__init__.py`
- [x] `addons/dms_product/__manifest__.py`
- [x] `addons/dms_product/models/__init__.py`

## Step 2：遷移模型
- [x] `git mv` 將 `dms_core/models/product.py` → `dms_product/models/product.py`
- [x] 從 `dms_core/models/__init__.py` 移除 `from . import product`

## Step 3：遷移視圖
- [x] `git mv` 將 `dms_core/views/product_views.xml` → `dms_product/views/product_views.xml`
- [x] 更新跨模組 menuitem：`parent="menu_dms_root"` → `parent="dms_core.menu_dms_root"`
- [x] 從 `dms_core/__manifest__.py` 的 `data` 中移除 `views/product_views.xml`

## Step 4：遷移 ACL
- [x] 建立 `dms_product/security/ir.model.access.csv`（只含 dms.product）
- [x] 從 `dms_core/security/ir.model.access.csv` 移除 dms.product 行

## Step 5：遷移前端 JS
- [x] `git mv` 將 `dms_core/static/src/js/dms_product_column_limit.js` → `dms_product/static/src/js/dms_product_column_limit.js`
- [x] 更新 patch 名稱為 `dms_product.productColumnLimit`
- [x] 從 `dms_core/__manifest__.py` assets 移除 `dms_product_column_limit.js`

## Step 6：驗證
- [x] restart odoo
- [x] CLI upgrade（dms_core + dms_product）
- [x] HTTP 200 確認
