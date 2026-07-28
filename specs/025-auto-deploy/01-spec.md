# Spec：DMIS Git 自動部署

1. T470P 每分鐘檢查 `origin/feat/015-dms-product-rebuild`。
2. 無新 commit 時不重啟服務。
3. 工作樹不乾淨或遠端不是 fast-forward 時停止部署並寫入日誌。
4. 更新前備份 `dmis_dev` PostgreSQL database。
5. 僅升級本次 commit 範圍內有變更的 Odoo addons。
6. 重建並啟動 Odoo 後執行 HTTP smoke test。
7. 使用 systemd user timer，主機重新開機後仍會自動執行。
