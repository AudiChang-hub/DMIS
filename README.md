# DMIS Next — Django 訂單與庫存 MVP

2026-07-28 起新增 Django 版本，目標是取代 Odoo 作為後續正式系統。既有
`addons/` 與 Odoo 規格暫時保留作歷史參考，不再作為新功能實作入口。

目前第一個可操作流程：

1. 手機建立訂單並拍攝證件正反面。
2. 列印一式兩份的正式訂購合約。
3. 可選擇上傳合約附件歸檔。
4. 訂單建立後即可從跨門市庫存配車。
5. 配車後鎖定實體車，避免重複銷售。
6. 首頁集中顯示全部門市待辦，並支援跨欄位搜尋。

本機快速啟動：

```powershell
python manage.py migrate
python manage.py seed_demo --username admin --password 請設定測試密碼
python manage.py runserver
```

開啟 `http://127.0.0.1:8000/`。

T470P Ubuntu Docker 啟動：

```bash
cp .env.django.example .env.django
# 修改 .env.django 中的 secret、密碼與網域
docker compose -f docker-compose.django.yml up -d --build
docker compose -f docker-compose.django.yml exec web \
  python manage.py seed_demo --username admin --password '請設定強密碼'
```

驗證：

```powershell
python manage.py check
python manage.py test sales
```

### T470P 儲存與備份

正式環境的 PostgreSQL 保留在 SSD；訂單媒體與本機備份位於
`/srv/dmis-data/dmis-next`。`dmis-next-backup.timer` 每日執行：

- PostgreSQL 每日備份保留 14 天、每週保留 8 週、每月保留約 12 個月。
- 媒體每日同步目前鏡像，並建立每週、每月封存。

維運檢查：

```bash
findmnt /srv/dmis-data
systemctl status dmis-next-backup.timer
journalctl -u dmis-next-backup.service -n 100 --no-pager
```

舊的 `dmis-next_django_media` volume 是遷移回復點，確認新儲存穩定前不得刪除。

UI 有異動時，另以桌機、平板及手機 viewport 開啟主要頁面，並在網址加入
`?ui_audit=1`。頁面根元素的 `data-ui-layout-issues` 必須為 `0`；完整檢查清單
見 `specs/026-django-order-mvp/04-tasks.md`。

訂單、配車、補助、領牌、交付、取消退款、工作日提醒、營運財務、
歷史 Excel 匯入及定位套表均已納入 Django 系統。LicenseWatcher Ubuntu
worker 依目前決策暫緩，不列入本次正式部署；後續若啟動，仍以
`specs/026-django-order-mvp/` 的自動監控與回傳候選號碼邊界為準。

### 正式環境安全與容量

- PostgreSQL 保留於 SSD；媒體檔與備份放在 Toshiba 資料碟。
- 全欄位訂單搜尋使用單筆彙整索引；PostgreSQL 另建立 `pg_trgm` GIN index。
- 訂單日期、實際領牌日期及收款確認查詢均建立資料庫索引。
- 上傳請求上限為 30 MB，超過 5 MB 的單一檔案會改用暫存檔處理，避免擠占 Web 記憶體。
- 正式環境必須設定獨立 `DJANGO_SECRET_KEY` 與 PostgreSQL 強密碼；不得提交 `.env.django` 或 Google Vision 金鑰。
- 若直接在內網以 `http://T470P:19999` 存取，須將 HTTPS 相關環境變數設為 `0`；若前方有 HTTPS reverse proxy，則維持安全 Cookie、HSTS 與 SSL redirect。

---

## 舊版 Odoo 歷史說明

如何載入示範資料（Seed / Demo）：

1. 安裝 `DMS Core` 模組時，系統會自動載入 `data/seed.xml` 的示範資料（若 manifest 中 `data` 包含 `data/seed.xml`）。
2. 若需要重新載入示範資料，可於模組安裝前先移除模組後重新安裝；或在開發環境使用匯入工具匯入 `addons/dms_core/data/seed.xml` 中的紀錄。

驗證步驟（示範資料）：

1. 啟動專案：

```bash
make up
```

2. 確認 Odoo 可達並登入後台（http://localhost:8069）。
3. 在 Apps 更新應用清單，安裝 `DMS Core`。
4. 安裝完成後，前往 `DMS -> 車行`，應可看到至少三筆示範資料（D001、D002、D003）。
# DMIS

此專案為 Odoo Community 最小專案骨架，包含 docker-compose 一鍵啟動、smoke 測試與規格治理。所有文件皆以繁體中文為主。

> 2026-03-27 架構更新：
> - `dms_catalog` 與舊 `dms_pricelist` 已終止，歷史收尾以 `014-module-removal` 為準
> - `dms_product` 已依 `015-dms-product-rebuild` 重建為新的獨立產品管理模組
> - `dms_sale` 保留銷售交易與 legacy 相容模型，查價邏輯優先讀取 `dms_product` 的 canonical 價格結構

快速開始：

1. 複製 `.env.example` 為 `.env` 並調整必要參數。
2. 啟動：

```bash
make up
```

3. 看日誌：

```bash
make logs
```

4. 驗證：

```bash
make smoke
```

若目前環境沒有安裝 `make`，可直接使用：

```bash
docker compose up -d
bash scripts/smoke_odoo.sh
```

Windows 使用者備註：

- 若系統沒有 `make` 或使用 Windows 原生 PowerShell，可改用下列等效指令：

	- 啟動服務（PowerShell / CMD）：

		```powershell
		docker compose up -d --build
		```

	- 在 Git Bash 下使用原有 bash 腳本：

		```bash
		bash scripts/smoke_odoo.sh
		```

	- 或在 PowerShell 直接執行新增的檢查腳本：

		```powershell
		.\scripts\smoke_odoo.ps1
		```

VS Code 建議設定（讓自動化/Tasks 使用 PowerShell 不載入使用者 profile）：

- 檔案：`.vscode/settings.json`
- 內容示例：已加入 `terminal.integrated.automationProfile.windows`，會使用 PowerShell 並帶 `-NoProfile` 參數，避免在自動化終端載入使用者的 profile，減少非預期中斷（例如 3 秒退出問題）。


開發：新增 module 至 `addons/`，並同步更新 `specs/` 下對應規格檔。

## T470P 自動部署

正式環境可使用 systemd user timer，每分鐘檢查指定 Git branch。只有遠端
出現 fast-forward commit 且工作樹乾淨時才會部署；更新前會備份 PostgreSQL，
有 addon 變更時會升級對應 Odoo module，最後執行 smoke test。

首次安裝：

```bash
chmod +x scripts/install_auto_deploy.sh scripts/auto_deploy.sh
./scripts/install_auto_deploy.sh
```

查看狀態與日誌：

```bash
systemctl --user status dmis-auto-deploy.timer
journalctl --user -u dmis-auto-deploy.service -n 100 --no-pager
```

手動 dry-run：

```bash
DMIS_DEPLOY_DRY_RUN=1 ./scripts/auto_deploy.sh
```

如何安裝 `dms_core` 模組（繁中）：

1. 確保專案已啟動：`make up`。
2. 開啟瀏覽器至 http://localhost:8069，登入 Odoo 後台（或建立管理員帳號）。
3. 進入「應用程式（Apps）」，點選右上角的「更新應用清單」或在開發者模式下按「更新模組清單」。
4. 在搜尋欄輸入「DMS Core」或「車行」，找到 `DMS Core` 模組後按安裝。
5. 安裝後可在側邊選單 `DMS -> 車行` 瀏覽/建立車行。

提示：若在 Apps 找不到模組，請確認 `addons/` 已正確掛載到容器的 `/mnt/extra-addons`，並在 Odoo 的 Apps 頁面中按「更新應用清單」。

## 模組清單

| Phase | 模組 | 選單名稱 | 狀態 |
|-------|------|----------|------|
| 0 | dms_core | 車行管理 | ✅ 完成 |
| 1 | dms_customer | 客戶管理 | ✅ 完成 |
| 2 | dms_sale | 銷售管理（交易主流程 + legacy 相容） | ✅ 已實作 |
| 2 | dms_product | 產品管理（模板 / SKU / 價格 / 分期 / 費用） | ✅ 已重建 |
| 2 | dms_visit | 拜訪紀錄 | ✅ 完成 |
| 3 | dms_finance | 財務結算 | ✅ 已實作 |
| 4 | dms_report | 報表分析 | ✅ 已實作 |
| 4 | dms_report_rule | 報表規則 | ✅ 已實作 |
| 4 | dms_report_virtual | 虛擬欄位 | ✅ 已實作 |
| Admin | user_management | 使用者管理 | ✅ 完成 |

歷史說明：

- `dms_catalog` 路線已正式撤回，相關歷史脈絡收斂於 `specs/014-module-removal/`
- 舊 `dms_product` / `dms_pricelist` 已在 014 收尾移除；015 之後由新的 `dms_product` 模組重新作為唯一正式產品入口
- 舊 `dms_sale` 產品 / 價目選單已隱藏，正式入口改為「產品管理」App；`dms_sale` 仍保留 `dms.product` / `dms.vehicle.price` 等 legacy 相容結構

## 維運腳本

- 清理已移除 `dms_catalog` / `dms_pricelist` 的殘留 metadata、舊頂層選單與模組登記，並清除重建 `dms_product` 前的孤兒模組 XML ID：

```bash
python3 scripts/cleanup_dms_catalog_metadata.py
```


使用 Slash Commands（Copilot Chat）:

- Prompt 檔放置位置：`.github/prompts/`，副檔名 `.prompt.md`。
- 可用的指令（在 Copilot Chat 輸入 `/` 後可見）：
	- `/dms-specify`：需求變更入口，輸入需求描述後會產出 Spec-first 的影響分析、要更新的 specs 檔案草稿、最小實作步驟與 PR 範本。
	- `/dms-feature`：新功能入口，會在 `specs/` 中建立新的 00~05 檔案骨架、列出 Open Questions/Assumptions，並產出最小實作建議。
	- `/dms-merge`：合併前檢查清單產生器，輸入 PR 編號或連結會回傳繁中合併檢查項與建議（不會合併）。

快速開始（示例）：

- /dms-specify <貼上需求變更>
- /dms-feature <新功能一句話目標>

工作流程（簡要）：

1. 使用 `/dms-specify` 或 `/dms-feature` 產出或更新 specs（Spec-first）。
2. 在 `specs/` 完成並確認後，建立 feature branch、實作最小變更；凡變更需要重啟 Odoo 才生效者，修改後需自動執行 `docker compose restart odoo`，再執行 `make smoke`。
3. 開 PR，PR 描述必填對應 specs 路徑；CI 會檢查若修改 `addons/**` 或 `docker-compose.yml`、`scripts/**`、`Makefile` 必須同步更新 `specs/**`。
4. 使用 `/dms-merge` 產出合併檢查清單後再合併。
