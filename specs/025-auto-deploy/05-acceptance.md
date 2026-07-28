# Acceptance：DMIS Git 自動部署

- timer 顯示 active，且下一次執行時間可查。
- 無新 commit 時不重啟 Odoo。
- dirty tree 時拒絕部署且不改動檔案。
- 新 commit 推送後能自動 fast-forward。
- 更新前產生非空的 PostgreSQL 壓縮備份。
- 有 addon 變更時執行對應 module upgrade。
- 部署後 `/web/login` 在 180 秒內回傳 200、302 或 303。
- `journalctl --user` 可追查每次成功或失敗結果。
