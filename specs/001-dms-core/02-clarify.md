# Clarify（澄清）

- 目標：最小可用模組，能在 Odoo Apps 中看到並安裝。
- 不包含複雜權限或額外商業邏輯。

## 問題紀錄（自動化啟動驗證時遇到）

- 問題：在本機使用 `docker compose up -d` 啟動後，`odoo` container 日誌反覆出現：
	"Database connection failure: connection to server at "0.0.0.0", port 5432 failed: Connection refused"。
- 時間：2026-02-25
- 原因分析：`odoo` container 未正確接收指向 `db` 服務的資料庫主機設定，環境變數不足或被其他變數覆寫，導致 Odoo 嘗試連線到 `0.0.0.0` 而非 compose 內部服務名 `db`。此外 `depends_on` 只保證啟動順序，並不保證 DB 可接受連線。
- 解法：在 `docker-compose.yml` 的 `odoo` 服務明確加入 `DB_HOST=db`（以及 `DB_PORT=5432`、`DB_USER`、`DB_PASSWORD`）環境變數，確保 Odoo 連到正確的 DB 主機；若需要可在 CI 中加入 DB ready 檢查（非本次最小修正）。
- 決策：採用最小修正（在 `docker-compose.yml` 補上 DB_* 環境變數）以快速讓容器互連並通過 smoke 測試。

後續建議：避免在 Odoo 相關環境中使用可能會覆寫資料庫參數的通用變數，並在 CI 或啟動腳本加入資料庫 ready 檢查以提高穩定性。