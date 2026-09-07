# DMIS Next｜車輛銷售管理系統（Django）

DMIS Next 是目前正式維護的車輛銷售、庫存與營運系統。2026-07-28 起由
Django 版本接手新功能。舊 Odoo、Metabase 及其資料源已退役，舊模組與部署入口已移除；
歷史規格僅供追溯，不可依其重新啟動舊系統。

## 目前功能

- 訂單草稿、證件 OCR、建立／修改、列印與完整變更紀錄。
- 配車、改配、庫存位置與車況歷程、領牌、補助、交付、取消與全額退款。
- 訂金、尾款、分期／平台撥款、刷卡費、成本、收入、支出、對帳與單筆淨利。
- 車行傭金、單筆台數與傭金歸屬、跨品牌／能源／車型／車行的台數獎金。
- 車型別附加獎勵，以及實物、紅包、禮券、點數品項與成本版本。
- 本店人員、合作車行、網路平台、通路分類、車型、售價、分期與牌險等主檔。
- 每月價格表分發：負責人、拖拉順序、電話、Google Maps、完成狀態與當月備註。
- 全欄位搜尋、歷史 Excel 預覽／匯入、工作日曆、定位套表與每帳號手機捷徑。

操作規則以 [使用者操作手冊](docs/USER_MANUAL.md) 與登入後右上角「使用說明」
為準。管理者可由「資料維護區 → 系統完整性報告」查看目前版本的稽核摘要；
即時資料庫、背景工作、搜尋索引及儲存空間則看「系統狀態檢查」。

## 本機開發

需求：Python 3.12、Node.js（只用於前端靜態測試），以及可讀取繁中文字型的環境。

```powershell
python -m pip install -r requirements-django.txt
python manage.py migrate
python manage.py seed_demo --username admin --password 請設定測試密碼
python manage.py runserver
```

開啟 `http://127.0.0.1:8000/`。未設定 `POSTGRES_HOST` 時使用本機 SQLite；這只適合
開發與測試，正式環境必須使用 PostgreSQL。

## 自動驗證

提交前至少執行：

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test sales
node --test tests/frontend/floating-list.test.cjs tests/frontend/bonus-periods.test.cjs tests/frontend/bonus-model-filter.test.cjs
```

依賴弱點比對：

```powershell
python -m pip install pip-audit
python -m pip_audit -r requirements-django.txt
```

財務一致性稽核是唯讀命令；先在備份或只讀可接受的環境確認，再對正式資料執行：

```powershell
python manage.py audit_financial_consistency --sample-limit 30
```

正式設定檢查需使用測試專用 secret 與 PostgreSQL 測試連線，不能把正式 secret 寫進
命令、CI 或 log：

```bash
DJANGO_DEBUG=0 \
DJANGO_ENV=production \
DJANGO_SECRET_KEY=ci-only-7Vf4pQ9xT2mR8kN5sL1dC6wH3zB0yG7uJ4aE9rP2nX8qM5 \
DJANGO_ALLOWED_HOSTS=dmis.example.test,localhost,127.0.0.1 \
DJANGO_CSRF_TRUSTED_ORIGINS=https://dmis.example.test \
POSTGRES_HOST=127.0.0.1 \
POSTGRES_DB=finance_ci \
POSTGRES_USER=finance_ci \
POSTGRES_PASSWORD=ci-isolated-only \
DJANGO_DB_USER=finance_ci_app \
DJANGO_DB_PASSWORD=ci-app-isolated-only \
python manage.py check --deploy
```

GitHub Actions 目前執行：

- `pip-audit`、Django 一般與 `--deploy` system check。
- migration 漂移檢查、全部 Django SQLite 測試及關鍵財務 PostgreSQL 測試。
- 三組既有前端行為測試。
- `Dockerfile.django` 正式映像建置、非 root 身分、runtime allowlist 與映像內
  `check --deploy`。
- 一次性 PostgreSQL 16 初始化，驗證 Django app role 為 database owner 且沒有
  superuser、createdb、createrole 或 replication 權限。
- PR 的 spec 同步檢查。

目前 repo 未啟用 GitHub Code scanning、Secret scanning 與 Dependabot alerts API；
`pip-audit` 與本機程式檢查不能取代持續式代管掃描。若 GitHub 方案與權限允許，應再
開啟這三項服務。CI 也不是實體手機、相機、分享與印表機驗收的替代品。

UI 有異動時，另以桌機 `1440×900`、平板 `820×1180`、手機 `390×844` 開啟受影響
頁面，並在網址加入 `?ui_audit=1`；根元素的 `data-ui-layout-issues` 應為 `0`。
同時以鍵盤檢查焦點順序、下拉選單、彈窗、固定操作列、拖拉替代操作及放大後內容。
驗收項目見 `specs/026-django-order-mvp/04-tasks.md`。

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

## 已知功能邊界

- 車行附加獎勵會保存承諾內容與單位成本快照，但尚未自動建立庫存出庫、應付款或
  單筆淨利支出；正式發放仍須依單據處理。
- 日常營運頁目前採內部帳號互信，多數登入者權限相同；「帳號與權限」及「系統完整性
  報告」只開放 superuser。這不代表可以查看或修改與工作無關的個資。
- Django admin 僅供系統管理者在緊急狀況下查詢。訂單、庫存、財務、獎勵、匯入及其他
  正式資料異動一律走系統業務頁面，以保留驗證、連動與稽核紀錄；admin 中的資料模型
  全部為唯讀。
- LicenseWatcher Ubuntu worker 尚未啟用；指定號碼仍依人工流程處理。
- 實體手機相機、分享、印表機偏移與現場網路需人工驗收。

## 正式備份自動還原演練

詳見 [還原演練與舊系統退役](docs/RESTORE_DRILL.md)。每週日清晨使用正式備份在隔離
環境還原，逐表核對筆數、附件 SHA-256、Django migration 與健康檢查。結果只供
superuser 在「系統完整性報告」查看；過期、失敗與未執行不會顯示成通過。

```bash
python3 scripts/restore_drill.py
```

此演練不覆寫正式庫，也不代表已完成異地整機切換。歷史 JSON 主檔匯入指令保留相容性，
但不連線舊 Odoo；未來報表須重新規劃，不沿用已刪除的 Metabase 資料源。
