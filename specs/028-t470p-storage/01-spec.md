# T470P 儲存分流與備份規格

## 架構

- SSD 保留 Ubuntu、Docker runtime、PostgreSQL、Redis 與所有既有服務。
- Toshiba 500GB HDD 固定掛載 `/srv/dmis-data`。
- 僅將 DMIS Next 的媒體檔與備份放到 HDD。
- 不搬移 `/var/lib/docker`，不變更其他 Compose 專案及其 volumes。

## 備份週期

- PostgreSQL 每日備份保留 14 天。
- 每週備份保留 8 週。
- 每月備份保留約 12 個月。
- 媒體維持一份每日同步鏡像，另保留每週及每月封存。
- 備份失敗必須回傳非零狀態並保留 systemd journal。

## 遷移安全

- 格式化前確認磁碟型號、序號、SMART 與既有檔案系統。
- 遷移前後比對所有容器名稱、狀態與健康度。
- 媒體切換期間只停止 DMIS Next web 與 OCR worker。
- 舊 Docker media volume 至少保留一輪驗證，不立即刪除。
