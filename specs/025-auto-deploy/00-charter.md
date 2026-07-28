# Charter：DMIS Git 自動部署

## 目標

當指定 Git branch 出現新 commit 時，由 T470P 自動、安全地更新 DMIS，
並保留資料庫備份、部署日誌與失敗診斷資訊。

## 非目標

- 不接受 force push 或非 fast-forward 更新。
- 不覆蓋正式主機上的未提交檔案。
- 不把 GitHub token、資料庫密碼或 Cloudflare token寫入 repository。
