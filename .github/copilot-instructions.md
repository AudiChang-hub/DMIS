此 repo 的 Copilot 指令（全域）

- 所有產出文字請以繁體中文為主。
- 修改 `addons/`、`docker-compose.yml` 時請同步更新 `specs/`。
- commit 與 PR 請使用清楚的繁中訊息，並在 PR 描述中註明驗證步驟。

補充規則（強制遵守）：

- 規格優先（Spec-first）：任何需求變更或功能新增須先建立或更新 `specs/`（包含 01/02/03/04/05）；未有相符 specs，請勿直接修改程式碼。
- 文件/PR/commit 一律繁體中文（charter 文件可夾帶英文說明）。
- Odoo 自訂模組僅放在 `addons/`，且不得修改 Odoo 核心。任何修改 `addons/**` 或 `docker-compose.yml`、`Makefile`、`scripts/**`，必須同步更新 `specs/**`，CI 會強制檢查。
- 每次交付必須附上可重現的驗證指令（至少：`make up` / `make smoke` / `docker compose ps`），並在 PR 描述中列出完整驗證步驟。
- 若需要建立示範資料，請放在模組的 `data/` 下並在 `__manifest__.py` 中註明；示範資料應標註為 demo 或可安全重複載入。
- 任何變更若需要重啟 Odoo 才會生效，實作者必須在修改完成後**自動**執行 `docker compose restart odoo`，不得等使用者提醒。至少以下情況預設需要重啟：`addons/**` 下的 Python、XML 視圖/選單/權限、`__manifest__.py`、static assets、以及任何會影響 Odoo registry / menu / web client 載入結果的變更；若無法完全判斷，預設重啟並再執行驗證。
- 自動重啟後，至少需補做 `docker compose ps` 與 `bash scripts/smoke_odoo.sh` / `make smoke` 其中之一，確認服務已回復並可正常存取。
- **每次 git commit 後必須立即執行 `git push`（VS Code「Sync Changes」），確保遠端同步；不得只 commit 不 push，不得等使用者提醒。**

車行管理模組（`addons/dms_core/`）維護規範（強制遵守）：

- **凍結模組**：`addons/dms_core/` 視為功能完整的凍結模組。任何修改須先取得專案負責人書面核准，並在 `specs/001-dms-core/06-maintenance.md` 記載修改原因與範圍，否則一律禁止直接改動。
- **非侵入擴充**：新功能必須以 `_inherit` 繼承或另建獨立模組實作，不得直接修改 `dms_core` 原始檔案。
- **安全設定不動**：`addons/dms_core/security/` 下的 ACL 與 Record Rules 禁止隨意變更；如需調整，需先驗證與現有規則無衝突，並於測試環境充分驗證後才可合併。
- **向下相容**：任何涉及資料結構的變更（欄位新增/刪除/改型）須附帶 migration script，確保現有生產資料不受損。
- **測試覆蓋**：修改前後須確保 `addons/dms_core/tests/` 所有測試通過（`make smoke` 驗證）。

Prompt 與 Slash Commands：

- 將 prompt files 放在 `.github/prompts/`，副檔名使用 `.prompt.md`，並在 frontmatter 提供 `name`、`description`、`argument-hint`、`agent`，以便 Copilot Chat 的 slash command 能識別並顯示。
