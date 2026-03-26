# 01 — Spec：使用者管理模組（user_management）

## 1. 模組目的

在 Odoo 原有群組機制之上，增加一層「自訂存取群組」（`um.access.group`），
讓管理者以圖形介面勾選各群組可見的菜單項目，並將使用者指派到群組。
使用者若歸屬多個群組，其可見菜單取所有群組的**聯集**。
若使用者未指派任何自訂群組，不施加額外限制（與原始 Odoo 行為相同）。
管理介面僅限 `base.group_system`（系統管理員）可見。

**不修改**現有群組、菜單原始設定或 ir.model.access 規則；
僅在渲染階段動態過濾菜單，確保現有功能完全不受影響。

---

## 2. 資料模型

### 2.1 `um.access.group`（自訂存取群組）

| 欄位 | 類型 | 說明 |
|---|---|---|
| `name` | Char | 群組名稱，必填 |
| `description` | Text | 說明 |
| `active` | Boolean | 啟用，預設 True |
| `menu_ids` | Many2many → ir.ui.menu | 允許可見的菜單（含子系自動包含祖先菜單） |
| `user_ids` | Many2many → res.users | 所屬使用者（與 `um_group_ids` 互為反向） |
| `menu_count` | Integer | computed，菜單數 |
| `user_count` | Integer | computed，使用者數 |

**中繼表：**
- 菜單：`um_access_group_menu_rel`（group_id, menu_id）
- 使用者：`um_user_group_rel`（group_id, user_id）

**Cache 失效：**`write()` 若修改 `menu_ids` 時呼叫 `ir.ui.menu.clear_caches()`。

### 2.2 `res.users`（繼承擴充）

新增欄位：
| 欄位 | 類型 | 說明 |
|---|---|---|
| `um_group_ids` | Many2many → um.access.group | 所屬自訂存取群組 |

`write()` 若修改 `um_group_ids` 時呼叫 `ir.ui.menu.clear_caches()`。

### 2.3 `ir.ui.menu`（繼承覆寫）

覆寫 `_visible_menu_ids(debug=False)`：

```
1. 呼叫 super() 取得 Odoo 原本的 visible 清單
2. 若 uid == SUPERUSER_ID → 直接回傳
3. 若 user.has_group('base.group_system') → 直接回傳
4. 取 user.um_group_ids；若為空 → 直接回傳（無限制）
5. 計算 allowed = union(group.menu_ids.ids for group in um_groups)
6. base_allowed = set(visible) ∩ allowed
7. 為每個 base_allowed 中的菜單，沿 parent_id 向上收集所有祖先
8. 回傳 final_allowed（leaf menus + 祖先）
```

> **注意**：由於原始方法有 `@ormcache`（以 user.groups_id 為 key），
> 覆寫後需確保 um_group_ids 變更時也呼叫 `clear_caches()`。

---

## 3. 安全規則

| 規則 | 模型 | 群組 | R/W/C/D |
|---|---|---|---|
| `access_um_access_group_admin` | um.access.group | base.group_system | 1/1/1/1 |

---

## 4. 視圖規格

### 4.1 `um.access.group` 清單視圖
欄位：名稱、菜單數、使用者數、啟用

### 4.2 `um.access.group` 表單視圖
- 標題：群組名稱
- 說明、啟用欄位
- 分頁：**可存取菜單**（many2many tree，顯示 complete_name）
- 分頁：**使用者**（many2many tree，顯示 name、login）

### 4.3 `res.users` 表單繼承
在 `base.view_users_form` 的 `notebook` 中新增分頁「**存取群組**」，
顯示 `um_group_ids` widget=many2many_tags。

### 4.4 菜單
```
使用者管理系統（根菜單，groups=base.group_system）
└── 存取群組管理 → action_um_access_group
```

---

## 5. 自動感知新菜單/模組

由於 `menu_ids` 直接指向 `ir.ui.menu`，任何新安裝模組所建立的菜單
會自動出現在管理表單的選擇器中，無需額外 hook。

---

## 6. 測試案例

| 測試 | 預期結果 |
|---|---|
| 使用者無 um_group_ids，查詢可見菜單 | 與 Odoo 原始結果相同 |
| 指派 um_group（含菜單 A）後查詢 | 僅見菜單 A 及其祖先 |
| 指派兩個 um_group（A+B）後查詢 | 見 A∪B 及其祖先 |
| base.group_system 使用者查詢 | 不受 um 群組限制 |
| um_group 無任何 menu_ids | 使用者看不到任何菜單 |
| 修改 um_group 的 menu_ids | ir.ui.menu cache 被清除 |
