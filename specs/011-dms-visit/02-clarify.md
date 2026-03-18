# 02 — Clarify：拜訪紀錄模組（dms_visit）

## 已澄清事項

### Q1：items_delivered 使用 product.product 還是 dms.product？
**A**：使用 `dms.product`（本系統自訂產品模型），因為本專案未安裝 Odoo 標準 `product` 模組，且 `dms_product` 已是系統內的車款/物品資料來源。中間關係表命名為 `dms.visit.item`（非多對多 through table，而是標準 One2many），便於儲存數量與備註。

### Q2：application=False 時選單如何掛載？
**A**：在 `views/visit_views.xml` 及 `views/visit_purpose_views.xml` 的 menuitem 中，以 `parent="dms_core.menu_dms_root"` 掛載至「車行管理」主選單下，不建立新的頂層選單（`<menuitem>` 無 parent 或 parent 為空會建立頂層選單）。

### Q3：Calendar view 的顏色欄位？
**A**：使用 `color="state"` 以狀態區分顏色（draft=灰、done=綠、cancel=紅），Odoo 16 Calendar 支援此用法。

### Q4：智能按鈕是否在 dealer 沒有拜訪時也顯示？
**A**：是，始終顯示數量（0 時顯示 0），讓使用者可直接點擊新建拜訪，`context` 預帶 `default_dealer_id`。

### Q5：dms.dealer 的 visit_ids 是否影響現有功能？
**A**：不影響。`visit_ids` 是額外 One2many 欄位，不修改原有欄位或邏輯，只在 `dealer_visit.py` 用 `_inherit = 'dms.dealer'` 新增。既有測試不需改動。

### Q6：Record Rule 與 admin bypass？
**A**：`base.group_system`（Odoo 超級管理員）預設繞過所有 Record Rules，因此超管永遠可讀寫所有紀錄。`group_dms_visit_admin` 額外設定 `[(1, '=', 1)]` rule 確保此群組成員（非超管）也能看到所有紀錄。

### Q7：回填日期的警告如何實作？
**A**：使用 `@api.onchange('visit_date')`，當日期早於目前時間時返回 `warning` dict，顯示提醒對話框但不阻擋儲存。

### Q8：是否需要 mail.thread（Chatter）？
**A**：本版本不加入 `mail` 依賴，以保持輕量。若未來需要討論串、追蹤，可在後續版本繼承 `mail.thread` 與 `mail.activity.mixin`。
