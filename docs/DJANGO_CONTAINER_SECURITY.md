# Django 容器建置安全邊界

## 目的

正式 Django image 只包含執行系統所需的程式與靜態資源，不得包含開發機上的密碼、客戶文件、資料庫、日誌、備份或 Git 歷程。

## 雙層防線

1. `.dockerignore` 採 allowlist；只有 `requirements-django.txt`、`manage.py`、`config/`、`sales/`、`templates/`、`static/` 與 `scripts/start_django.sh` 能進入 build context。
2. `Dockerfile.django` 再逐項 `COPY` 相同 runtime 檔案，不使用 `COPY . .`。

因此下列內容不會進入 image：

- `.env*` 與 `secrets/`
- `db.sqlite3`、PostgreSQL 資料及 Redis 資料
- `media/`、`logs/`、`backups/`、`output/`、`tmp/`
- `.git/`、規格、開發文件、測試與舊 Odoo addons

容器以非 root 的 `dmis` 系統帳號執行；`media/` 與 `staticfiles/` 於 image 建置時建立並授予該帳號權限。正式環境的密碼與金鑰仍須透過環境變數或唯讀 secret mount 提供，不能寫入 image。

映像預設使用 UID/GID `1000:1000`，與 T470P 的 `audi` 帳號一致；其他主機可用
`DJANGO_UID`、`DJANGO_GID` build args 調整。綁定的媒體目錄必須由同一 UID/GID
可寫，不可因權限問題改回 root 執行。

## CI 驗證

GitHub Actions 的 `Django 品質檢查` 與既有 Odoo job 分離，使用 SQLite 執行：

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test sales
```

本機可用下列命令確認 image 建置內容與執行身分：

```bash
docker build -f Dockerfile.django -t dmis-django:local .
docker run --rm --entrypoint sh dmis-django:local -c 'id && find /app -maxdepth 2 -type f | sort'
```

輸出不應出現 `.env`、`secrets`、`db.sqlite3`、`media` 內的客戶檔案、日誌、備份或 `.git`。
