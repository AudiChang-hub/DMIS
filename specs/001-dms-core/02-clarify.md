# Clarify（澄清）

- 目標：最小可用模組，能在 Odoo Apps 中看到並安裝。
- 不包含複雜權限或額外商業邏輯。

## 問題紀錄（自動化啟動驗證時遇到）
## 清理與組態整理紀錄

- 時間：2026-02-25
- 決策：為了消除 `docker compose` 在執行時出現的 obsolete 警告，並降低因殘留或舊容器（或phan/ orphan containers）誤判而影響自動化驗證的風險，採取以下最小變更：
	1. 從 `docker-compose.yml` 移除頂層 `version` 欄位（該屬性在新版本的 compose 中已為過時屬性，會被忽略並顯示警告）。
	2. 確認 `docker-compose.yml` 僅包含本專案所需服務：`odoo` 與 `db`。若有其他舊服務（例如先前專案殘留的 `redis` container）會出現 orphan 提示，應透過下列方式處理：
		 - 在本次最小變更中不把外部 orphan container 加回 compose，而是記錄並建議維護者手動清理或使用 `--remove-orphans`。
		 - 對於非必要服務，建議以 `profiles` 或可選服務形式加入，而非永遠啟動，以減少殘留風險。
	3. 新增 `Makefile` 的 `ps` 目標以便快速回報 `docker compose ps` 結果。

- 原因與理由：
	- 移除 `version` 可消除 CLI 提示與混淆，讓 CI/agent 日誌更乾淨。 
	- 限制 compose 服務可以減少 orphan 與其他專案殘留容器干擾自動化判斷。 
	- 提供 `make ps` 有助於快速回報狀態，方便 CI/人工排查。

- 後續建議：
	- 若需保留 `redis` 等非必要服務，請使用 `profiles` 或額外的 compose 檔（例如 `docker-compose.override.yml` 或 `docker-compose.redis.yml`）以避免常駐。
	- CI 可加入 `docker compose ps` 與 orphan 偵測步驟，並在 PR 說明上要求清理或說明是否故意改動服務。

- 問題：在本機使用 `docker compose up -d` 啟動後，`odoo` container 日誌反覆出現：
	"Database connection failure: connection to server at "0.0.0.0", port 5432 failed: Connection refused"。
- 時間：2026-02-25
- 原因分析：`odoo` container 未正確接收指向 `db` 服務的資料庫主機設定，環境變數不足或被其他變數覆寫，導致 Odoo 嘗試連線到 `0.0.0.0` 而非 compose 內部服務名 `db`。此外 `depends_on` 只保證啟動順序，並不保證 DB 可接受連線。
- 解法：在 `docker-compose.yml` 的 `odoo` 服務明確加入 `DB_HOST=db`（以及 `DB_PORT=5432`、`DB_USER`、`DB_PASSWORD`）環境變數，確保 Odoo 連到正確的 DB 主機；若需要可在 CI 中加入 DB ready 檢查（非本次最小修正）。
- 決策：採用最小修正（在 `docker-compose.yml` 補上 DB_* 環境變數）以快速讓容器互連並通過 smoke 測試。

後續建議：避免在 Odoo 相關環境中使用可能會覆寫資料庫參數的通用變數，並在 CI 或啟動腳本加入資料庫 ready 檢查以提高穩定性。