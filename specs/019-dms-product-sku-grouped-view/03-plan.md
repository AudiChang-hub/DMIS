# 03 實作計畫

## 步驟

1. 在 `addons/dms_product/views/product_sku_views.xml` 末端新增：
   - `view_product_sku_grouped_tree`（tree view）
   - `action_product_sku_grouped`（act_window）

2. 在 `addons/dms_product/views/menu_views.xml` 新增：
   - `menu_product_sku_grouped`（menuitem）

3. manifest version 不需升級（純 view/action/menu，不涉及 model 或 data）

4. `--update dms_product` 後重啟驗證
