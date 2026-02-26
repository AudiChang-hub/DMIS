# 規格 03 — DMS 車行欄位選擇與 UI 改善

目的
- 依 specs/002 實作 `dms.dealer` 的 master-data。
- 提供使用者可自訂車行列表欄位的 UI（每使用者偏好）。

變更說明
- 新增/修改模組：`addons/dms_core`
  - `models/dealer.py`：`dms.dealer`、`dms.dealer.columns.wizard`、`res.users.dms_dealer_tree_cols`。
  - `views/dealer_views.xml`：車行列表/表單/搜尋視圖；新增「欄位選擇」wizard action/menu；在 wizard 中顯示欄位標籤。
  - `security/ir.model.access.csv`：新增必要的 ACL（若尚未包含，請補上）。
  - `data/seed.xml`：示範資料（若有）。

操作與驗證步驟（可重複）
1. 啟動環境

```powershell
# 啟動服務
docker compose up -d
```

2. 升級並套用模組

```powershell
# 在容器內升級 dms_core
docker compose exec -T odoo bash -lc "odoo -d postgres -u dms_core --stop-after-init --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo"
```

3. 簡易 smoke 測試

```powershell
# 檢查 Odoo Web
docker compose exec -T odoo bash -lc "curl -s -o /dev/null -w '%{http_code}' http://localhost:8069/web/login"
# 預期回傳 200 或 302
```

4. UI 驗證（手動）
- 以系統管理員登入：前往 DMS → 車行 → 列表。
- 點擊工具列或選單的「欄位選擇」，開啟 wizard。
- 使用欄位搜尋/選取，點選「套用」。
- 確認列表欄位依使用者設定改變。

注意事項
- 若修改 `addons/`、`docker-compose.yml`，請同時更新 `specs/`。此檔案即為本次變更的 specs。
- ACL 建議：初期可允許 `base.group_user` 讀取 wizard，正式環境請依權限策略收斂建立/修改權限。

驗證命令摘要

```powershell
# 啟動
docker compose up -d
# 升級模組
docker compose exec -T odoo bash -lc "odoo -d postgres -u dms_core --stop-after-init --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo"
# 檢查
docker compose exec -T odoo bash -lc "curl -s -o /dev/null -w '%{http_code}' http://localhost:8069/web/login"
```
