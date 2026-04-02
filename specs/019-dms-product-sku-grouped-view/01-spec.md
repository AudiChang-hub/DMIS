# 01 功能規格

## 新增清單 View：`view_product_sku_grouped_tree`

- 模型：`dms.product`
- 顯示欄位（由左至右）：
  1. 「開啟」按鈕（icon=fa-external-link，type=object，呼叫 `action_open_installment_dialog`）
  2. 內部唯一代碼（readonly）
  3. 出廠年份（readonly）
  4. 顏色（readonly）
  5. 現金售價（readonly，optional show）
  6. 牌價（readonly，optional show）
  7. 活動特殊價（readonly，optional show）
  8. 有效售價（readonly，optional show）
  9. 啟用（readonly，optional show）
- 整個 tree 為 readonly（不允許行內編輯）
- 不允許在此列表直接新增/刪除（create="false" delete="false"）

## 新增 Action：`action_product_sku_grouped`

- res_model：`dms.product`
- view_mode：`tree,form`
- view_id：`view_product_sku_grouped_tree`
- context：`{'search_default_groupby_template': 1, 'active_test': False}`
- 預設啟用「產品模板」分組（search_default_groupby_template 對應 search view 內 groupby_template filter）

## 新增選單：`menu_product_sku_grouped`

- parent：`menu_dms_product_master_group`
- sequence：12（在「產品頁面」之後）
- name：SKU 折疊總覽
