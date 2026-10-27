# Clarify：DMIS Git 自動部署

- 正式主機沒有 passwordless sudo，因此採 systemd user timer。
- `audi` 已啟用 systemd linger，可在未登入桌面時持續執行 timer。
- Git remote 使用既有 SSH deploy key，不新增 GitHub token。
- 初期沿用正式環境目前 branch；待產品重建 branch 合併後再切換 `main`。
- 資料庫備份保留 14 天，可透過環境變數調整。
