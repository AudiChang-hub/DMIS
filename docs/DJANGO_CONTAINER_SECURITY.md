# Django 容器與正式環境安全邊界

本文件說明目前 Django runtime 的建置、防外洩與正式對外連線邊界。它是部署檢查表，
不是滲透測試或 GitHub 代管安全功能已啟用的證明。

## 1. 映像內容採雙層 allowlist

1. `.dockerignore` 預設排除全部內容，只放行 `Dockerfile.django`、
   `requirements-django.txt`、`manage.py`、`config/`、`sales/`、`templates/`、
   `static/` 與 Django 啟動／smoke 腳本。
2. `Dockerfile.django` 再逐項 `COPY` runtime 必要檔案，不使用 `COPY . .`。

因此 `.env*`、`secrets/`、`.git/`、`db.sqlite3`、客戶媒體、log、備份、規格、測試與
legacy Odoo addons 不應進入 image。變更 `.dockerignore` 或 `Dockerfile.django` 時，必須
重新執行下方映像內容檢查。

## 2. 容器身分與持久資料

- image 以非 root 的 `dmis` 帳號執行，預設 UID/GID 為 `1000:1000`；其他主機可用
  `DJANGO_UID`、`DJANGO_GID` build args 調整。
- `/app/media` 與 `/app/staticfiles` 由建置階段建立並授予 `dmis`。正式綁定的媒體目錄
  必須讓相同 UID/GID 可寫，不得為了省事改成 root 或放寬整個主機目錄權限。
- PostgreSQL、Redis、媒體與備份不寫入 image。正式 secret 僅能透過環境變數或唯讀
  secret mount 提供。
- Cloudflare Tunnel token 放在 `secrets/cloudflare-tunnel.token`，Google Vision 金鑰
  放在 `secrets/google-vision.json`；兩者不得提交 Git、複製進 image 或寫入 log。

## 3. PostgreSQL 角色分工

正式 `.env.django` 使用兩組不同帳號：

```dotenv
POSTGRES_USER=dmis_admin
POSTGRES_PASSWORD=請替換為資料庫管理角色強密碼
DJANGO_DB_USER=dmis_app
DJANGO_DB_PASSWORD=請替換為應用程式資料庫強密碼
```

- `POSTGRES_USER`／`POSTGRES_PASSWORD`：PostgreSQL 管理角色，僅用於資料庫初始化、維護與
  備份，不作為 Django 一般查詢連線。
- `DJANGO_DB_USER`／`DJANGO_DB_PASSWORD`：Django web 與 workers 實際使用的 app role。
  `config/settings.py` 有設定 `DJANGO_DB_*` 時會優先使用它，不會用管理角色連線。
- 管理角色與 app role 的帳號、密碼都必須不同；初始化腳本會在兩邊密碼相同時停止，
  且不會把密碼寫進輸出。
- Compose 會在 web、OCR、搜尋及匯入 worker 內將 `POSTGRES_USER`／`POSTGRES_PASSWORD`
  覆寫為空值；管理角色的實際帳密只留給 DB container。若新增 application service，必須
  同樣清空這兩個變數並使用 `DJANGO_DB_*`。
- `scripts/init_django_db.sh` 建立或收斂可登入的 app role，使其成為指定 database owner，
  同時明確保持 `NOSUPERUSER`、`NOCREATEDB`、`NOCREATEROLE`、`NOREPLICATION`。手動套用於
  既有 volume 時只移交目前 database 的非系統物件，不會使用可能波及其他 database 或
  tablespace 的 `REASSIGN OWNED`。

初始化腳本由 PostgreSQL 官方 image 放在 `/docker-entrypoint-initdb.d/`，只在全新資料
volume 自動執行。既有 volume 要先完成可還原備份，再由管理者明確補跑：

```bash
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml exec -T db \
  bash /docker-entrypoint-initdb.d/10-dmis-app-role.sh
```

腳本不會更新已存在 role 的密碼。輪替既有 `DJANGO_DB_PASSWORD` 時，必須先由資料庫管理者
安全地變更 app role 密碼，再同步環境設定；不得把密碼放在 shell history 或 log。單純
修改 `.env.django` 的 `POSTGRES_PASSWORD` 也不會變更既有 volume 內的管理角色密碼。

CI 會在一次性 `postgres:16` container 實際執行初始化腳本，再查詢系統 catalog，確認
app role 可登入、不是 superuser、不能建立 database／role、不能 replication，且只擁有
指定 database、不擁有 tablespace。另建立一張管理角色所有的既有資料表，模擬重跑腳本
後 app role 可查詢、新增與 `ALTER TABLE`，並確認意外的高權限會被收斂。密碼每次隨機
產生、不印到輸出，並以 timeout 與 `trap` 清除 container。

## 4. 正式 port 與 Tunnel

`docker-compose.django.yml` 將 Django 發布 port 固定綁到 loopback：

```yaml
ports:
  - "127.0.0.1:${DJANGO_PORT:-19999}:8000"
```

正式 `.env.django` 的 `DJANGO_PORT` 只填主機 port，例如 `19999`，不要再填 IP。外部使用者
只能經 `https://dmis.moto-core.com/` 與 Cloudflare Tunnel 進入；不得另外把 `19999`
開放給區網或 Internet。`tunnel-proxy` 沿用既有來源名稱 `odoo:8069`，實際轉送 Django
`web:8000`；此相容名稱不代表 Odoo 仍是正式服務。

部署前後核對：

```bash
docker compose -f docker-compose.django.yml \
  -f docker-compose.django.prod.yml config
ss -ltnp | grep ':19999'
curl --fail --silent --show-error http://127.0.0.1:19999/health/
curl --fail --silent --show-error https://dmis.moto-core.com/health/
```

`ss` 應顯示 `127.0.0.1:19999`，不得是 `0.0.0.0:19999` 或 `[::]:19999`。

## 5. CI 與本機驗證

GitHub Actions 目前會執行：

- `pip-audit -r requirements-django.txt`。
- Django 一般 system check 與使用安全測試設定的 `check --deploy`。
- migration 漂移檢查、全部 SQLite 測試及關鍵財務 PostgreSQL 測試。
- 既有前端靜態行為測試。
- `Dockerfile.django` 建置、非 root 身分、runtime allowlist、空白 media 及映像內
  `check --deploy`。
- 一次性 PostgreSQL 16 驗證 app role 的權限與 database owner；無論成功、失敗或 timeout
  都會清除測試 container。
- PR 的 spec 同步檢查。

本機可重現映像檢查：

```bash
docker build --pull -f Dockerfile.django -t dmis-django:local .
docker run --rm --entrypoint sh dmis-django:local -c '
  set -eu
  test "$(id -u)" -ne 0
  test -f /app/manage.py
  test -f /app/scripts/start_django.sh
  test ! -e /app/.git
  test ! -e /app/.env
  test ! -e /app/.env.django
  test ! -e /app/secrets
  test ! -e /app/db.sqlite3
  test -z "$(find /app/media -mindepth 1 -print -quit)"
'
```

依賴與 Django 正式設定另行檢查：

```bash
python -m pip_audit -r requirements-django.txt
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

以上值只供檢查，不得改用正式 secret；資料庫名稱也必須指向隔離測試資料庫。

## 6. 目前限制

- GitHub Code scanning、Secret scanning 與 Dependabot alerts API 目前尚未在此 repo 啟用；
  `pip-audit` 只能比對 Python 依賴，不能取代程式碼掃描、秘密外洩偵測或持續告警。
- `check --deploy`、單元測試與 image allowlist 不等於滲透測試，也不驗證 Cloudflare 帳號、
  主機防火牆、SSH、作業系統更新或備份可還原性。
- 正式部署仍需人工確認 Tunnel、loopback 監聽、登入、權限、媒體上傳、背景 workers 與
  關鍵業務流程；CI 綠燈本身不代表已部署完成。
- 任何掃描結果都要記錄被測 commit、日期、命令、失敗／skip 與未涵蓋範圍，才可納入
  管理者的「系統完整性報告」。
