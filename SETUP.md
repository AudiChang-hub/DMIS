# DMIS 系統部署指引（Ubuntu）

> 適用版本：Odoo 16 Community + PostgreSQL 15  
> 容器化工具：Docker + Docker Compose  
> 最後更新：2026-03-17

閱讀本文件後，您可在一台全新的 Ubuntu 機器上完整重建 DMIS 系統，包含容器、資料庫、所有自訂模組。

---

## 目錄

1. [系統需求](#1-系統需求)
2. [安裝 Docker 與 Docker Compose](#2-安裝-docker-與-docker-compose)
3. [安裝 make（選用）](#3-安裝-make選用)
4. [取得原始碼](#4-取得原始碼)
5. [設定環境變數](#5-設定環境變數)
6. [啟動容器](#6-啟動容器)
7. [初始化資料庫與安裝模組](#7-初始化資料庫與安裝模組)
8. [驗證安裝](#8-驗證安裝)
9. [日常操作指令](#9-日常操作指令)
10. [目錄結構說明](#10-目錄結構說明)
11. [疑難排解](#11-疑難排解)

---

## 1. 系統需求

| 項目 | 最低規格 | 建議規格 |
|------|---------|---------|
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| CPU | 2 核心 | 4 核心以上 |
| RAM | 4 GB | 8 GB 以上 |
| 磁碟 | 20 GB | 50 GB 以上 |
| Docker | 24.x | 最新穩定版 |
| Docker Compose | v2（`docker compose`） | 最新穩定版 |
| Git | 2.x | 最新穩定版 |

> **注意：** 本專案使用 `docker compose`（Compose V2，內建於 Docker）。若系統只有舊版的 `docker-compose`（V1），請先升級。

---

## 2. 安裝 Docker 與 Docker Compose

```bash
# 移除舊版（若有）
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# 安裝相依套件
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# 新增 Docker 官方 GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 新增 Docker apt 來源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安裝 Docker Engine + Compose
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 將目前使用者加入 docker 群組（免 sudo）
sudo usermod -aG docker $USER
newgrp docker

# 驗證安裝
docker --version
docker compose version
```

---

## 3. 安裝 make（選用）

`make` 指令可簡化操作，若不安裝則可使用文件中標示的等效指令。

```bash
sudo apt-get install -y make
```

---

## 4. 取得原始碼

```bash
# 選擇您要存放的目錄
cd ~

# 複製 repo（替換 <user> 為實際 GitHub 帳號）
git clone https://github.com/<user>/DMIS.git
cd DMIS

# 確認目前所在分支
git branch -a
git checkout feat/dms_visit   # 若要重現目前整併後版本，可切換至此分支
```

---

## 5. 設定環境變數

```bash
# 從範例建立 .env 檔案
cp .env.example .env

# 編輯 .env（建議修改密碼）
nano .env
```

`.env` 欄位說明：

| 變數 | 預設值 | 說明 |
|------|-------|------|
| `ODOO_PORT` | `8069` | Odoo 對外 HTTP 埠 |
| `DB_PORT` | `5433` | PostgreSQL 對外埠（主機側，避免與本機 PG 衝突） |
| `POSTGRES_USER` | `odoo` | 資料庫使用者名稱 |
| `POSTGRES_PASSWORD` | `odoo` | **請修改為強密碼** |
| `POSTGRES_DB` | `postgres` | PostgreSQL 預設 DB（系統用，非業務 DB） |

> **安全提醒：** `.env` 已在 `.gitignore` 中排除，不會被 commit。請勿在此檔案中使用弱密碼部署至對外服務。

---

## 6. 啟動容器

```bash
# 啟動（背景執行）
make up
# 或不使用 make：
docker compose up -d
```

等待容器就緒（約 20-30 秒）：

```bash
# 確認服務狀態
docker compose ps
```

預期輸出（兩個服務皆為 `Up`）：

```
NAME            IMAGE         STATUS        PORTS
dmis-odoo-1     odoo:16       Up            0.0.0.0:8069->8069/tcp
dmis-db-1       postgres:15   Up            0.0.0.0:5433->5432/tcp
```

查看 Odoo 啟動日誌：

```bash
make logs
# 或：
docker compose logs -f odoo
```

看到 `odoo.service: Odoo Server is running` 或 Werkzeug 行即代表啟動完成，按 `Ctrl+C` 離開日誌。

---

## 7. 初始化資料庫與安裝模組

### 方法 A：透過 Web 介面（建議第一次使用）

1. 開啟瀏覽器，前往 `http://<伺服器 IP>:8069/web/database/manager`
2. 點擊 **「建立資料庫」**
3. 填寫：
   - **主密碼（Master Password）**：`odoo`（預設，可在 odoo.conf 修改）
   - **資料庫名稱**：`dmis_dev`
   - **語言**：繁體中文（`zh_TW`）
   - **Email**：管理員 Email
   - **密碼**：管理員密碼
   - 勾選 **「載入示範資料」可跳過**（不需要 Odoo 原廠示範資料）
4. 按 **「建立」** 並等待完成（約 1-2 分鐘）

### 方法 B：命令列一鍵初始化（適合自動化）

```bash
# 建立資料庫並安裝 base（第一步）
docker compose exec odoo odoo \
  -d dmis_dev \
  --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
  --without-demo=all \
  -i base \
  --stop-after-init

# 安裝所有 DMIS 自訂模組（第二步）
docker compose exec odoo odoo \
  -d dmis_dev \
  --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo \
  -i dms_core,dms_customer,dms_sale,dms_visit,dms_finance,dms_report,dms_report_rule,dms_report_virtual,user_management \
  --stop-after-init
```

> 安裝完成後，容器會自動停止（`--stop-after-init`），需再次啟動：
>
> ```bash
> docker compose up -d
> ```

### 方法 C：透過 Odoo Apps 介面（已有資料庫）

1. 登入 Odoo 後台 `http://<IP>:8069`
2. 進入 **「應用程式（Apps）」**
3. 點選 **「更新應用清單」**（右上角選單）
4. 搜尋並依序安裝（數字順序代表依賴關係）：
   1. `DMS 車行管理`（dms_core）
   2. `DMS 客戶管理`（dms_customer）
   3. `DMS 銷售管理`（dms_sale，內含產品資料 / 價目資料）
   4. `DMS 拜訪紀錄`（dms_visit）
   5. `DMS 財務結算`（dms_finance）
   6. `DMS 報表分析`（dms_report）
   7. `報表規則設定`（dms_report_rule）
   8. `報表虛擬欄位`（dms_report_virtual）
   9. `使用者管理`（user_management）

---

## 8. 驗證安裝

### 快速 smoke 測試

```bash
make smoke
# 或：
bash scripts/smoke_odoo.sh
```

預期輸出：`OK: received 200 from http://localhost:8069/web/login`

### 手動驗證

1. 開啟瀏覽器前往 `http://<IP>:8069`
2. 以管理員帳號登入
3. 確認上方選單包含：**車行管理、客戶管理、銷售管理、財務結算、報表分析、使用者管理**
4. 進入 **「銷售管理」** 後，確認可看到 **「產品資料」** 與 **「價目資料」** 子選單

### 模組安裝驗證指令（逐一確認無 ERROR）

```bash
PGHOST=db PGUSER=odoo PGPASSWORD=odoo \
docker compose exec -T odoo bash -lc \
  "odoo -d dmis_dev --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init 2>&1 | grep -E 'ERROR|Module.*loaded' | tail -20"
```

---

## 9. 日常操作指令

| 動作 | make 指令 | 等效 docker 指令 |
|------|-----------|----------------|
| 啟動服務 | `make up` | `docker compose up -d` |
| 停止服務 | — | `docker compose down` |
| 停止並清除資料庫 Volume | `make down` | `docker compose down -v` |
| 查看日誌 | `make logs` | `docker compose logs -f odoo` |
| 確認服務狀態 | `make ps` | `docker compose ps` |
| Smoke 測試 | `make smoke` | `bash scripts/smoke_odoo.sh` |
| 重啟 Odoo | — | `docker compose restart odoo` |
| 清理已移除模組殘留 metadata / 舊頂層選單 / 模組登記 | — | `python3 scripts/cleanup_dms_catalog_metadata.py` |

### 手動安裝/更新模組

```bash
docker compose exec odoo odoo -d dmis_dev --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo -i <模組名稱> --stop-after-init
# 更新（已安裝的模組重新載入）
docker compose exec odoo odoo -d dmis_dev --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo -u <模組名稱> --stop-after-init
```

安裝後記得重新啟動 Odoo：

```bash
docker compose up -d
```

---

## 10. 目錄結構說明

```
DMIS/
├── addons/                     # 所有 DMIS 自訂 Odoo 模組
│   ├── dms_core/               # 車行管理（基礎模組）
│   ├── dms_customer/           # 客戶管理
│   ├── dms_sale/               # 銷售管理（含產品資料、價目資料）
│   ├── dms_visit/              # 拜訪紀錄
│   ├── dms_finance/            # 財務結算（含動態類別）
│   ├── dms_report/             # 報表分析（pivot + graph）
│   ├── dms_report_rule/        # 報表規則管理
│   ├── dms_report_virtual/     # 動態虛擬欄位（computed 分類）
│   └── user_management/        # 使用者管理（菜單白名單 / 稽核）
├── docs/                       # 文件
│   ├── USER_MANUAL.md          # 使用者操作手冊
│   ├── CHANGELOG.md            # 版本變更紀錄
│   └── CONSTITUTION.md         # 開發規範憲章
├── scripts/                    # 維運腳本
│   ├── smoke_odoo.sh           # Smoke 測試（bash）
│   ├── smoke_odoo.ps1          # Smoke 測試（PowerShell）
│   ├── validate_views_fields.py # 視圖欄位驗證
│   └── cleanup_dms_catalog_metadata.py # 清理已移除模組 metadata、舊頂層選單與模組登記
├── specs/                      # 模組規格文件（spec-first）
├── logs/                       # 容器日誌（.gitignore 排除 *.log）
├── docker-compose.yml          # Docker Compose 設定
├── Makefile                    # 常用指令捷徑
├── .env.example                # 環境變數範例（複製為 .env 後填入）
├── .env                        # 實際環境變數（已 gitignore，勿 commit）
├── SETUP.md                    # 本部署文件
└── README.md                   # 專案簡介
```

### 模組依賴關係

```
dms_report_virtual
    └── dms_report_rule
            └── dms_report
                    ├── dms_finance
                    │       └── dms_sale
                    │               ├── dms_customer
                    │               └── dms_core
                    └── dms_visit
                            ├── dms_sale
                            └── dms_core
```

---

## 11. 疑難排解

### 問題：`docker compose up` 後 Odoo 頁面無法存取

1. 確認 port 未被佔用：`ss -tlnp | grep 8069`
2. 查看 Odoo 錯誤：`docker compose logs odoo | tail -30`
3. 確認 db 容器已就緒：`docker compose ps`；若 db 尚在啟動，Odoo 會自動重連

### 問題：在 Apps 找不到 DMIS 模組

1. 確認 addons 掛載正確：
   ```bash
   docker compose exec odoo ls /mnt/extra-addons
   ```
   應看到 `dms_core dms_customer dms_sale dms_visit ...` 等目錄
2. 進入 Odoo 後台 → Settings → 開啟 **Developer Mode** → Apps → 點擊 **「Update Apps List」**

### 問題：安裝模組時出現 ERROR

```bash
# 查看詳細安裝日誌
docker compose exec odoo odoo -d dmis_dev -i dms_core --stop-after-init 2>&1 | grep -E 'ERROR|Traceback'
```

### 問題：資料庫連線失敗（`could not connect to server`）

1. 確認 `.env` 中的 `POSTGRES_USER` / `POSTGRES_PASSWORD` 與 `docker-compose.yml` 一致
2. 重建容器：`docker compose down && docker compose up -d`

### 問題：`make` 指令無法執行

安裝 make 後仍出現問題，可直接使用 `docker compose` 等效指令（見第 9 節表格）。

### 問題：Odoo 資料庫需要完整重置

```bash
# 警告：此操作會刪除所有資料
docker compose down -v
docker compose up -d
# 然後重新執行第 7 節的初始化步驟
```

---

## 附錄：生產環境建議事項

> 以下建議適用於將系統對外服務時，開發/測試環境可略過。

1. **修改 `.env` 密碼**：`POSTGRES_PASSWORD` 請設定為 16 字元以上的強密碼
2. **設定 Master Password**：Odoo 資料庫管理頁面有 master password，預設為 `admin`，請至 Settings → Technical → Database Structure 修改
3. **加上 Nginx 反向代理**：在 Odoo 前端加上 Nginx，啟用 HTTPS 與壓縮
4. **定期備份 volume**：備份 Docker volume `db_data`：
   ```bash
   docker run --rm -v dmis_db_data:/data -v $(pwd):/backup \
     ubuntu tar czf /backup/db_backup_$(date +%Y%m%d).tar.gz /data
   ```
5. **日誌管理**：設定 Docker log rotation，避免磁碟爆滿：
   ```json
   // /etc/docker/daemon.json
   {
     "log-driver": "json-file",
     "log-opts": { "max-size": "50m", "max-file": "5" }
   }
   ```
