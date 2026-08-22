# T470P 舊 Odoo 退役評估

評估日期：2026-08-22
本文件僅盤點與提出可回復的退役順序；在完成備份與依賴確認前，不直接刪除容器、volume 或舊專案。

## 現況結論

| 元件 | 現況 | 初步判斷 |
|---|---|---|
| `dmis-odoo-1` | 已停止 7 天 | Odoo Web 已由 Django DMIS 取代，可進入封存候選 |
| `dmis-cloudflared-1` | 已停止 4 天 | 舊 Odoo 對外通道已不服務正式 DMIS，可進入封存候選 |
| `dmis-db-1` | PostgreSQL 15，仍運作 | **暫不可刪**；保存舊 Odoo 資料，且 Metabase 仍同步名為 DMIS 的 PostgreSQL 資料來源 |
| `dmis-metabase-1` | 正常運作並持續同步 | **暫不可刪**；需先確認使用者是否仍使用舊統計報表，以及是否改接 Django 資料庫 |
| `dmis-cloudflared-metabase-1` | 正常運作 | **暫不可刪**；與 Metabase 對外存取綁定 |
| `dmis_odoo_data` | Odoo filestore volume | 先封存備份，確認無待搬附件後才能刪除 |
| `dmis_db_data` | 舊 PostgreSQL volume | 先做可還原的完整備份並驗證；在 Metabase 切換前保留 |
| `dmis_metabase_data` | Metabase 設定／儀表板 volume | 在報表搬遷或正式確認停用前保留 |

舊資料庫內 `dmis_dev` 仍有 411 張 public tables，包含 Odoo 模組、同步紀錄與 DMIS 商品資料；因此「Odoo 畫面已不用」不等於「整個舊資料庫可直接刪除」。

## 建議退役順序

### 第 1 階段：凍結與備份

1. 保持 `dmis-odoo-1`、`dmis-cloudflared-1` 停止，不再寫入舊 Odoo。
2. 產生舊 PostgreSQL 全庫 dump、Odoo filestore、Metabase application DB 三份備份。
3. 對備份記錄 SHA-256、檔案大小與還原測試結果。
4. 將舊 compose、`.env` 與 Cloudflare tunnel 對應關係另行封存，但不得把 secret commit 到 Git。

### 第 2 階段：確認 Metabase 去留

1. 列出 Metabase 現有儀表板、最近瀏覽與實際使用者。
2. 若仍要保留報表，將資料來源改接 `dmis-next-db-1`，逐張驗證欄位與數字。
3. 若營運總表已完整取代 Metabase，先停止 Metabase 與其 tunnel 14 天觀察，不立刻刪除 volume。

### 第 3 階段：可回復停用

1. 將舊 compose 改成不會因主機重啟而自動拉起 Odoo。
2. 移除已停止的 Odoo／舊 tunnel 容器，但保留映像與三個 volume。
3. 驗證 `dmis.moto-core.com`、19999、備份排程與 T470P 其他服務均正常。

### 第 4 階段：永久清理

只有在以下條件全部通過後，才刪除舊映像、專案與 volumes：

- Django DMIS 已覆蓋需要保留的 Odoo 資料與操作。
- Metabase 已改接新資料庫或經使用者確認停用。
- 備份在獨立位置完成還原演練。
- 可回復停用觀察期至少 14 天且沒有回復需求。
- 取得使用者再次明確授權永久刪除。

## 本輪明確不做

- 不執行 `docker compose down -v`。
- 不刪除 `dmis_db_data`、`dmis_odoo_data`、`dmis_metabase_data`。
- 不停止仍在運作的 Metabase、舊 PostgreSQL 或 Metabase tunnel。
- 不變更 T470P 其他服務。
