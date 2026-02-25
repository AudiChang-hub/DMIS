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

如何安裝 `dms_core` 模組（繁中）：

1. 確保專案已啟動：`make up`。
2. 開啟瀏覽器至 http://localhost:8069，登入 Odoo 後台（或建立管理員帳號）。
3. 進入「應用程式（Apps）」，點選右上角的「更新應用清單」或在開發者模式下按「更新模組清單」。
4. 在搜尋欄輸入「DMS Core」或「車行」，找到 `DMS Core` 模組後按安裝。
5. 安裝後可在側邊選單 `DMS -> 車行` 瀏覽/建立車行。

提示：若在 Apps 找不到模組，請確認 `addons/` 已正確掛載到容器的 `/mnt/extra-addons`，並在 Odoo 的 Apps 頁面中按「更新應用清單」。


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
2. 在 `specs/` 完成並確認後，建立 feature branch、實作最小變更、執行 `make smoke`。
3. 開 PR，PR 描述必填對應 specs 路徑；CI 會檢查若修改 `addons/**` 或 `docker-compose.yml`、`scripts/**`、`Makefile` 必須同步更新 `specs/**`。
4. 使用 `/dms-merge` 產出合併檢查清單後再合併。

