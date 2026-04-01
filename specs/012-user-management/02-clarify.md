# 02 — Clarify：使用者管理模組澄清記錄

## Q1：當使用者屬於多個 um_group，選單邏輯是交集還是聯集？

**A**：取**聯集**（union）。各群組的 `menu_ids` 合併後，使用者可見所有群組加起來允許的選單。
這讓管理員可以建立「基礎選單群組」+「額外功能群組」組合授權，彈性較高。

## Q2：若使用者沒有指派任何 um_group，行為為何？

**A**：**不施加任何限制**，與原始 Odoo 行為完全相同。
空 um_group_ids 被視為「未設定自訂限制」，而非「看不到任何選單」。

## Q3：um_group 完全沒設定 menu_ids（空白名單），使用者看得到什麼？

**A**：**看不到任何選單**（回傳空集合）。這是蓄意設計——空白名單代表「完全限制」，
不同於 Q2 的「未指派群組」。

## Q4：`base.group_system`（管理員）和 SUPERUSER 受 um_group 影響嗎？

**A**：**完全不受影響**。程式碼在第一步就直接回傳原始可見菜單，不套用 um_group 過濾。

## Q5：新安裝的模組新增選單，管理員需要手動同步嗎？

**A**：**不需要**。由於 `menu_ids` 直接指向 `ir.ui.menu`，任何新選單都會自動出現在
群組管理介面的選擇器中，勾選後即生效。

## Q6：`ir.ui.menu` 有 `@ormcache`，覆寫後 cache 會失效嗎？

**A**：已在 `um.access.group.write()` 和 `res.users.write()` 中主動呼叫
`ir.ui.menu.clear_caches()`，確保 `um_group_ids` / `menu_ids` 變更時 cache 立即失效。

## Q7：稽核日誌（um.audit.log）記錄哪些操作？

**A**：目前記錄 `um.access.group` 的建立、修改、刪除事件，以及
`res.users.um_group_ids` 的變更，供後續稽核追蹤。
