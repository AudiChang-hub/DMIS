# Plan：DMIS Git 自動部署

1. 新增具鎖定、dirty tree 與 fast-forward 保護的部署腳本。
2. 更新前使用 `pg_dump` 產生壓縮備份。
3. 依 Git diff 判斷需升級的自訂 addons。
4. 重建、升級、啟動並執行 smoke test。
5. 使用 systemd user service／timer 排程。
6. 以 dry-run、Shell syntax、systemd verify 與正式 smoke 驗證。
