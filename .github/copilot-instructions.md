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

Prompt 與 Slash Commands：

- 將 prompt files 放在 `.github/prompts/`，副檔名使用 `.prompt.md`，並在 frontmatter 提供 `name`、`description`、`argument-hint`、`agent`，以便 Copilot Chat 的 slash command 能識別並顯示。

