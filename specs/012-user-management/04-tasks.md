# 04 — Tasks：使用者管理模組（user_management）

## Phase 1：規格與設計

- [x] 建立 `specs/012-user-management/` 完整規格文件（00~05）
- [x] 確認選單過濾邏輯設計（聯集、空群組行為、管理員不受限）

## Phase 2：模型

- [x] `addons/user_management/models/um_access_group.py` — um.access.group（含 menu_ids、user_ids、computed counts、cache 失效）
- [x] `addons/user_management/models/res_users.py` — res.users 擴充（um_group_ids、cache 失效）
- [x] `addons/user_management/models/ir_ui_menu.py` — ir.ui.menu 覆寫（_visible_menu_ids 選單過濾邏輯）
- [x] `addons/user_management/models/um_audit_log.py` — um.audit.log（稽核日誌）
- [x] `addons/user_management/models/base_audit.py` — 基礎稽核 mixin
- [x] `addons/user_management/models/__init__.py`
- [x] `addons/user_management/__init__.py`
- [x] `addons/user_management/__manifest__.py`

## Phase 3：安全設定

- [x] `addons/user_management/security/ir.model.access.csv` — 僅 base.group_system 可存取 um.access.group

## Phase 4：視圖

- [x] `addons/user_management/views/um_access_group_views.xml` — 清單 + 表單（菜單分頁 + 使用者分頁）
- [x] `addons/user_management/views/res_users_inherit.xml` — 使用者表單新增「存取群組」分頁
- [x] `addons/user_management/views/um_audit_log_views.xml` — 稽核日誌清單視圖
- [x] `addons/user_management/views/um_menu_views.xml` — 根選單 + 存取群組管理子選單

## Phase 5：測試

- [x] `addons/user_management/tests/__init__.py`
- [x] `addons/user_management/tests/test_um.py`
  - [x] test_01：無 um_group_ids 時不施加額外限制
  - [x] test_02：指派含菜單 A 的群組後，只見菜單 A 及其祖先
  - [x] test_03：指派兩個群組（A+B）後，見 A∪B 及其祖先
  - [x] test_04：base.group_system 使用者不受 um_group 限制
  - [x] test_05：um_group 無任何 menu_ids 時使用者看不到任何菜單
  - [x] test_06：修改 um_group 的 menu_ids 後 ir.ui.menu cache 被清除
  - [x] test_07：修改 res.users.um_group_ids 後 cache 被清除
  - [x] test_08：子菜單指派後，自動包含所有祖先菜單

## Phase 6：收尾

- [x] 8 個單元測試全部通過（0 FAIL / 0 ERROR）
- [x] 模組升級無 ERROR/WARNING
- [x] Commit & Push
