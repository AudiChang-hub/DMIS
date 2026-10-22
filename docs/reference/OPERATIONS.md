# 正式維運（僅部署／維運任務讀取）

## 安全與完成條件

- 先確認 T470P checkout、branch、工作樹、備份與可回復版本；只用 Django base＋prod compose。
- 應用更新不得任意重啟 PostgreSQL、Redis 或同機其他服務。Web port 只綁 loopback，由 Cloudflare Tunnel 對外 HTTPS。
- Django web／workers 使用非 superuser DB app role；管理角色只供初始化、維護與備份，不把管理帳密給 application containers。
- 金鑰以環境或唯讀 secret mount 提供，不進 image／Git／log。
- 完成需 compose health、workers、本機和公開 `/health/`、至少一個登入後关键流程；僅容器 Up 不算。
- migration、儲存或重大財務異動前備份；還原步驟必須可操作，不用 `docker compose down` 或破壞性 Git 解決失敗。
- 下列流程移自 README；執行前核對目前腳本及實際部署。文件整理本身不授權重啟或部署。

## T470P 正式部署

正式專案目錄為 `/home/audi/project/DMIS-next`。第一次設定：

```bash
cp .env.django.example .env.django
# 設定獨立 secret、PostgreSQL 強密碼、正式網域與本機綁定 port
```

正式 `.env.django` 的 Web port 必須只綁 loopback：

```dotenv
DJANGO_PORT=19999
DJANGO_DEBUG=0
DJANGO_ENV=production
DJANGO_ALLOWED_HOSTS=dmis.moto-core.com,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://dmis.moto-core.com
POSTGRES_DB=dmis
POSTGRES_USER=dmis_admin
POSTGRES_PASSWORD=請替換為資料庫管理角色強密碼
DJANGO_DB_USER=dmis_app
DJANGO_DB_PASSWORD=請替換為應用程式資料庫強密碼
```

`POSTGRES_USER`／`POSTGRES_PASSWORD` 是 PostgreSQL 管理角色，供資料庫初始化與備份；
Django 的一般連線只使用 `DJANGO_DB_USER`／`DJANGO_DB_PASSWORD`。初始化腳本會讓 app
role 成為該 database owner，但保持 `NOSUPERUSER`、`NOCREATEDB`、`NOCREATEROLE` 與
`NOREPLICATION`。既有 volume 補跑時只移交目前 database 的非系統物件，不會變更其他
database 或 tablespace 的所有權。Compose 會在 web 與三個 worker 內清空管理角色變數，
避免應用程式取得管理密碼。兩組帳密必須不同，且不得沿用範例文字。

`scripts/init_django_db.sh` 只會由 PostgreSQL 官方 image 在**全新資料 volume** 自動執行。
既有正式 volume 不會補跑；升級前須先完成可還原備份，再以既有管理角色在 DB container
內明確執行一次，確認 app role 建立成功後才切換 Django 連線：

```bash
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml exec -T db \
  bash /docker-entrypoint-initdb.d/10-dmis-app-role.sh
```

若 app role 已存在，初始化腳本不會替它輪替密碼；更換既有密碼須由資料庫管理者安排，
並同步更新 `DJANGO_DB_PASSWORD`。不要只改 `POSTGRES_PASSWORD` 就假設既有 volume 的管理
角色密碼已變更。

`19999` 是 T470P 上的本機健康檢查入口（綁在 `tunnel-proxy`），不應直接暴露給區網或 Internet。正式使用者
只經 `https://dmis.moto-core.com/` 與 Cloudflare Tunnel 進入；
`docker-compose.django.prod.yml` 的 `tunnel-proxy` 保留舊來源名稱 `odoo:8069`，轉送到
目前接流量的 `web-blue:8000` 或 `web-green:8000`（見下方「藍綠部署」）。Tunnel connector 固定使用 HTTP/2。
`deployment/nginx/tunnel-proxy.conf` 必須轉送 `Upgrade`／`Connection`，訂單草稿即時共編
（`/ws/orders/drafts/…`）才能建立 WebSocket；少了會回 404，畫面一直顯示重新連線。
`X-Forwarded-For` 只送 Cloudflare 覆寫的 `CF-Connecting-IP`（不可改回 `$proxy_add_x_forwarded_for`：
daphne 取最左邊的值，用戶端可偽造，登入節流就失效）。登入失敗：同帳號＋來源 5 次／15 分、同帳號不分來源
20 次／1 小時，各暫停 15 分鐘並在接流量那色的 web 日誌記 `login_account_locked`；急件解除：
`compose exec -T web python manage.py shell -c "from config.auth_views import clear_account_login_lock as c; c('帳號')"`。
正式站的 `web` 服務不接流量，只當管理指令容器：`compose exec -T web python manage.py …`
（systemd 排程、本文件的維運指令）照舊可用，image 與上線版本同一次建置。

查慢用的存取紀錄在 `/srv/dmis-data/dmis-next/logs/nginx/access.log`（容器外，部署重建不會消失）：
每行一筆 JSON，`rt` 是總耗時（含使用者上傳／下載），`urt` 是 Django 處理時間，`rid` 對應畫面上的
查修編號；只記路徑，不記查詢字串與來源 IP，`/health/` 不記。tunnel-proxy 每次啟動時把上一段改名
壓縮為 `access-日期.log.gz`，保留 30 天。Django 處理超過 3 秒的請求另記 `slow_request` 到 web 日誌。
不需要時移除 compose 的兩行掛載與 `tunnel-proxy.conf` 的 `access_log /var/log/dmis/…` 即回復。

Tunnel token 只存於 `secrets/cloudflare-tunnel.token`，檔案權限設為 `600`；不得提交
至 Git，也不得放進 `.env.django`。Google Vision 金鑰同樣只能以唯讀 secret mount
提供。

正式啟動與檢查：

```bash
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml up -d --build
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml ps
bash scripts/smoke_django.sh http://127.0.0.1:19999
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml exec -T web python manage.py check --deploy
curl --fail --silent --show-error https://dmis.moto-core.com/health/
```

`/health/` 只回報 Web 與資料庫能否使用，不顯示版本、密碼或環境內容。部署完成不只
看容器是否 `Up`，還要確認本機與正式網域健康檢查、背景 workers，以及實際登入後的
關鍵頁面。

### 安全部署腳本（藍綠部署，零停機）

```bash
chmod +x scripts/deploy_django.sh scripts/deploy_web_bluegreen.sh scripts/backup_django_data.sh
./scripts/deploy_django.sh             # 部署 origin/main
./scripts/deploy_django.sh --rollback  # 秒退：切回上一色
```

`deploy_django.sh` 確認 branch、乾淨工作樹與 fast-forward，先備份 PostgreSQL 和媒體（部署前備份
只新增、不清理過期檔，以免部署帳號刪不掉 root 擁有的備份而中止），核對發布標籤，再交給
`scripts/deploy_web_bluegreen.sh`：

1. 建置新版 image（靜態檔在建置時整理），舊版照常服務。
2. `check_migration_compat` 檢查待套用 migration；相容就先套用（`lock_timeout` 10 秒），舊版仍在服務。
3. 在閒置的那色（`web-blue`／`web-green`）啟動新版，healthcheck 通過才繼續；起不來就停在這裡，流量不動。
4. 把 `/srv/dmis-data/dmis-next/proxy/active.conf` 改成新色並 `nginx -s reload`：手上的請求由舊 worker 處理完，新請求進新版。
5. 等 15 秒排空後**停止但保留**舊的那色（仍是上一版 image，供秒退），再更新管理指令容器與背景工作。
6. 照舊驗證 HTTP/2 connector、正式網域、`record_release` 與部署標記。

- `tunnel-proxy` 只在 compose 設定改變時重建；重建時先起同 alias 的暫代 nginx（`dmis-next-proxy-bridge`）接手，不出現 502。設定檔改了只需 reload（掛整個 `deployment/nginx` 目錄）。
- WebSocket 共編在切換時會斷一次，瀏覽器 1 秒後自動重連到新版。
- 有不相容 migration（刪除／改名欄位等，規則見 [開發驗證](DEVELOPMENT.md)）時自動改用短暫停機部署：先停舊版再遷移，使用者看到約 15～20 秒「系統更新中」頁（與改版前的中斷時間相當；nginx 在連不到 Django 時回 503 並自動重新整理），log 會標明。
- `--rollback` 用 `docker start` 啟動上一色、就緒後切回並停止目前那色；只切 web 流量，管理容器與背景工作仍是新版，資料庫不倒退，所以只適用於相容 migration 的版本，之後應盡快發修正版（部署標記改成上一版，下次部署會重新套用 main）。
- 從單一 web 改成藍綠已在 1.86.47（2026-10-21）完成：舊 web 換成管理指令容器、tunnel-proxy 以暫代代理重建並綁 19999。腳本本身有更新時，合併後會自動改用新版繼續。
- 查目前顏色：`./scripts/deploy_web_bluegreen.sh active`；兩色與暫代代理都只在本專案的 compose network 內。

資料庫與 Redis 不會因應用更新而重啟。任一檢查失敗時不得用 `docker compose down`
繞過保護，應依 log 修正或回復前一個已驗證版本。

## 儲存、備份與排程

正式 PostgreSQL 保留於 SSD，媒體與本機備份位於 `/srv/dmis-data/dmis-next`。
`dmis-next-backup.timer` 每日執行：

- PostgreSQL 每日備份保留 14 天、每週 8 週、每月約 12 個月；過期清理只由此排程執行。
- 媒體每日同步目前鏡像，另建立每週與每月封存。
- 每週與每月封存每期只建立一次；已存在（例如凌晨 root 排程已建立）就保留原檔，部署當天再跑備份不會因覆寫被拒而中止。

```bash
findmnt /srv/dmis-data
systemctl status dmis-next-backup.timer
journalctl -u dmis-next-backup.service -n 100 --no-pager
```

只有備份檔存在不代表可還原；重大 migration 或儲存異動前應在隔離環境演練還原。
舊的 `dmis-next_django_media` volume 是遷移回復點，確認新儲存與還原流程前不得刪除。

### 工作日行事曆

`dmis-next-calendar-sync.timer` 每月 1 日同步當年與次年的政府辦公日曆。下載、網域、
重新導向、檔案大小或內容驗證失敗時保留既有資料；人工例外日期不會被覆蓋。

```bash
sudo bash scripts/install_django_calendar_sync_timer.sh
systemctl list-timers dmis-next-calendar-sync.timer --all
sudo systemctl start dmis-next-calendar-sync.service
journalctl -u dmis-next-calendar-sync.service -n 50 --no-pager
```

### 每月價格表分發

`dmis-next-price-list-distribution.timer` 每日防呆：缺少本月清單時補建，並於每月最後
一天預先建立隔月清單。

```bash
sudo bash scripts/install_django_price_list_distribution_timer.sh
systemctl list-timers dmis-next-price-list-distribution.timer --all
python manage.py generate_price_list_distribution --month 2026-09
```

### 每週原廠官網檢查

`dmis-next-official-catalog-check.timer` 每週一清晨檢查 SYM、SUZUKI 官網，只寫入比對紀錄；有新車款、變動或讀取失敗時通知 admin。

```bash
sudo bash scripts/install_django_official_catalog_timer.sh
systemctl list-timers dmis-next-official-catalog-check.timer --all
journalctl -u dmis-next-official-catalog-check.service -n 50 --no-pager
```

### 訂單檔案同步到 NAS

系統內的檔案仍是正本；`search-worker` 處理 `archive` 佇列，把每張訂單的檔案複製到
`/mnt/od/DMIS訂單/<車型>/<年>/<月>/<車行>_<車主>_<車型>_<訂單編號>/`（2026-10-13 使用者選定）。
訂單或其檔案一有異動就排入同步；車主、車型、日期改了資料夾跟著搬。NAS 斷線不影響訂單操作，
錯誤記在 `OrderArchiveRecord.last_error`，恢復後由下次異動或每日補同步補上。

- `.env`：`DJANGO_ORDER_ARCHIVE_PATH=/mnt/od`（主機路徑，掛進 search-worker 的 `/app/order-archive`）。
- `.env.django`：`DMIS_ORDER_ARCHIVE_DIR=/app/order-archive`（留空即停用）。
- 首次啟用或要全部重做：`docker compose ... exec -T search-worker python manage.py sync_order_archive [訂單編號…]`；加 `--verify` 只核對 NAS 與系統是否一致。
- 每日 03:40 補同步（需 sudo 安裝一次）：

```bash
sudo bash scripts/install_django_order_archive_timer.sh
systemctl list-timers dmis-next-order-archive-sync.timer --all
```


## 正式備份自動還原演練

詳見 [還原演練與舊系統退役](../RESTORE_DRILL.md)。每週日清晨使用正式備份在隔離
環境還原，逐表核對筆數、附件 SHA-256、Django migration 與健康檢查。結果只供
superuser 在「系統完整性報告」查看；過期、失敗與未執行不會顯示成通過。

```bash
python3 scripts/restore_drill.py
```

此演練不覆寫正式庫，也不代表已完成異地整機切換。歷史 JSON 主檔匯入指令保留相容性，
但不連線舊 Odoo；未來報表須重新規劃，不沿用已刪除的 Metabase 資料源。

## 清除全部業務資料

2026-10-05 已依使用者要求清除一次，清除前備份在 `/srv/dmis-data/dmis-next/backups/pre-reset-20261005/`。

只在使用者明確要求重新開始時執行，且必須先完成可還原的 DB＋媒體備份
（`scripts/backup_django_data.sh`）。指令預設只預覽各表筆數：

```bash
docker compose -f docker-compose.django.yml -f docker-compose.django.prod.yml \
  exec -T web python manage.py reset_business_data
```

加上 `--confirm 清除全部業務資料` 才會在單一交易內清除訂單、庫存、匯入、主檔與規則，
並刪除這些資料引用的附件檔。保留帳號與權限、門市、馭盛公司資料（訂購單公司資訊）、
通路類別、工作日與假日、報表定義與版本歷程；帳號的預設店別會清空，須重新選擇。重建順序見使用者手冊「首次建立基本資料」。
