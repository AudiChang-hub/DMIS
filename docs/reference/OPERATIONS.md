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

`19999` 是 T470P 上的本機健康檢查入口，不應直接暴露給區網或 Internet。正式使用者
只經 `https://dmis.moto-core.com/` 與 Cloudflare Tunnel 進入；
`docker-compose.django.prod.yml` 的 `tunnel-proxy` 保留舊來源名稱 `odoo:8069`，但實際
轉送到 Django `web:8000`。Tunnel connector 固定使用 HTTP/2。

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

### 安全部署腳本

```bash
chmod +x scripts/deploy_django.sh scripts/backup_django_data.sh
./scripts/deploy_django.sh
```

腳本會確認 branch、乾淨工作樹與 fast-forward，先備份 PostgreSQL 和媒體，再重建
web／OCR／搜尋／匯入服務、重建 tunnel proxy、驗證 HTTP/2 connector 與正式網域。
資料庫與 Redis 不會因應用更新而重啟。任一檢查失敗時不得用 `docker compose down`
繞過保護，應依 log 修正或回復前一個已驗證版本。

## 儲存、備份與排程

正式 PostgreSQL 保留於 SSD，媒體與本機備份位於 `/srv/dmis-data/dmis-next`。
`dmis-next-backup.timer` 每日執行：

- PostgreSQL 每日備份保留 14 天、每週 8 週、每月約 12 個月。
- 媒體每日同步目前鏡像，另建立每週與每月封存。

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


## 正式備份自動還原演練

詳見 [還原演練與舊系統退役](../RESTORE_DRILL.md)。每週日清晨使用正式備份在隔離
環境還原，逐表核對筆數、附件 SHA-256、Django migration 與健康檢查。結果只供
superuser 在「系統完整性報告」查看；過期、失敗與未執行不會顯示成通過。

```bash
python3 scripts/restore_drill.py
```

此演練不覆寫正式庫，也不代表已完成異地整機切換。歷史 JSON 主檔匯入指令保留相容性，
但不連線舊 Odoo；未來報表須重新規劃，不沿用已刪除的 Metabase 資料源。
