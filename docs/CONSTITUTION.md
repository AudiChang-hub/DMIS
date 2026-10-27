# 憲法（CONSTITUTION）

本文件為專案治理憲法，旨在確保專案穩定、可測試與規格一致性。

條款（繁體中文為主）：

1. 所有文件、PR 標題/描述、commit message 一律繁體中文；但技術性代號或第三方授權可附英文說明。
2. 任何變更若修改 `addons/**` 或 `docker-compose.yml`，必須同步更新 `specs/**`。CI 會檢查，若未同步則 CI 失敗。
3. 禁止修改 Odoo 核心程式；所有自定義應放在 `addons/` 內的模組中。
4. 必須提供可重現的環境（`docker compose`）與一鍵驗證（`make smoke`）。
5. 規格（`specs/`）為變更合規依據，包含 charter、spec、plan、tasks、acceptance 等文件。
6. 任何變更若需重啟 Odoo 才能生效，實作者必須在修改完成後自動執行 `docker compose restart odoo`，不得等待提醒；若不確定是否需要重啟，預設應重啟並補做基本驗證。
7. 完成自動重啟後，至少需確認 `docker compose ps` 狀態正常，並執行 `bash scripts/smoke_odoo.sh` 或 `make smoke` 其中之一。

違反條款將由維護者要求補正，並可拒絕合併。
