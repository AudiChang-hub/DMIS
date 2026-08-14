# Acceptance：DMIS Git 自動部署

- timer 顯示 active，且下一次執行時間可查。
- 無新 commit 時不重啟 Odoo。
- dirty tree 時拒絕部署且不改動檔案。
- 新 commit 推送後能自動 fast-forward。
- 更新前產生非空的 PostgreSQL 壓縮備份。
- 有 addon 變更時執行對應 module upgrade。
- 部署後 `/web/login` 在 180 秒內回傳 200、302 或 303。
- `journalctl --user` 可追查每次成功或失敗結果。
- 純文件／規格 commit 可自動 fast-forward，且 Odoo container 不重啟。

## DMIS Next 正式入口

- Django `tunnel-proxy` 在 `dmis-next_default` 使用唯一的 `odoo` alias。
- Cloudflare connector 不得同時連接舊 `dmis_default`，避免 Docker DNS 輪流
  導向 Odoo 與 Django。
- 部署後 `scripts/verify_django_public_route.sh` 連續檢查至少 12 次，首頁不得
  導向 `/web` 或出現 Odoo 頁面內容。
- 舊 `/web` 與 `/zh_TW/data/vehicle-models/` 捷徑會導回目前 Django 畫面。
- 只有通過健康檢查與正式入口驗證後才寫入 `deployed-sha`；若 Git 已更新但
  上次部署中斷，下一次必須續跑服務重建，不可誤判為完成。
- web container 重建後必須強制重建 `tunnel-proxy`，不可沿用 nginx 已解析的
  舊 web IP；正式健康檢查不得持續出現 502。
