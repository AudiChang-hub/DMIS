# 驗證 view 欄位與 model 一致性

此檔說明如何本地執行與在 CI 中加入 `scripts/validate_views_fields.py` 的驗證流程。

本地執行

```bash
# 在專案根目錄
python scripts/validate_views_fields.py
```

使用 Makefile

```bash
make validate-views
```

建議將 `make ci-checks` 加入 CI 流程的步驟中，若驗證失敗會回傳非零狀態碼。

伺服器上升級模組（範例）

```bash
# 在有 odoo-bin 的環境下，先 pull 最新程式碼並重啟（保留 volumes）
git checkout -b feat/validate-views
git add scripts/validate_views_fields.py Makefile docs/validate_views.md
git commit -m "新增 view/model 欄位驗證腳本與 Makefile 目標"
# push 並建立 PR（代替 <remote> 與 <branch>）
git push -u origin feat/validate-views

# 在伺服器或 container 中重啟 Odoo（保留資料）
docker compose pull
docker compose restart

# 更新模組
docker compose exec odoo ./odoo-bin -c /etc/odoo/odoo.conf -d dmis_dev -u dms_core
```

驗證步驟

- 執行 `make validate-views` 檢查 view 欄位是否存在於 model。
- 若通過，於 Odoo UI 中執行模組升級或以上面指令更新模組。
