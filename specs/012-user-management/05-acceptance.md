# 05 — Acceptance：使用者管理模組（user_management）

## 驗收指令

```bash
# 升級模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev -u user_management --stop-after-init 2>&1 \
   | grep -E 'ERROR|WARNING|loaded' | tail -10"

# 執行單元測試
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
   odoo -d dmis_dev --test-enable --stop-after-init \
   -u user_management 2>&1 \
   | grep -E 'tests\:|failed' | tail -5"

# 重啟確認
docker compose restart odoo && bash scripts/smoke_odoo.sh
```

## 功能驗收項目

| # | 測試情境 | 預期結果 | 狀態 |
|---|----------|----------|------|
| AC-01 | 升級 `user_management` 無 ERROR/WARNING | 升級成功 | ✅ |
| AC-02 | 「使用者管理系統」根選單出現，僅 base.group_system 可見 | 一般使用者看不到此選單 | ✅ |
| AC-03 | 在「存取群組管理」建立群組，勾選菜單後儲存 | 記錄成功 | ✅ |
| AC-04 | 將使用者 A 指派到群組後，使用者 A 只能看到該群組的白名單選單 | 選單過濾生效 | ✅ |
| AC-05 | 使用者 A 指派兩個群組（X+Y），可見選單為 X∪Y | 聯集邏輯正確 | ✅ |
| AC-06 | 使用者未指派任何群組，可見選單與原始 Odoo 相同 | 無額外限制 | ✅ |
| AC-07 | 群組的 menu_ids 為空，指派後使用者看不到任何選單 | 空白名單完全限制 | ✅ |
| AC-08 | base.group_system 使用者不受 um_group 影響 | 查看所有選單 | ✅ |
| AC-09 | 修改群組的 menu_ids 後，使用者可見選單立即更新（cache 失效） | 無需重啟 | ✅ |
| AC-10 | 稽核日誌正確記錄群組建立 / 修改 / 刪除操作 | um.audit.log 有新記錄 | ✅ |

## 單元測試結果

```
0 failed, 0 error(s) of 8 tests
```

| 測試 | 描述 | 狀態 |
|---|---|---|
| test_01 | 無 um_group_ids 時不施加額外限制 | ✅ |
| test_02 | 指派含菜單 A 的群組後只見 A 及其祖先 | ✅ |
| test_03 | 指派兩個群組（A+B）後見 A∪B 及其祖先 | ✅ |
| test_04 | base.group_system 使用者不受 um_group 限制 | ✅ |
| test_05 | um_group 無 menu_ids 時使用者看不到任何菜單 | ✅ |
| test_06 | 修改 um_group.menu_ids 後 cache 被清除 | ✅ |
| test_07 | 修改 res.users.um_group_ids 後 cache 被清除 | ✅ |
| test_08 | 子菜單指派後自動包含祖先菜單 | ✅ |
