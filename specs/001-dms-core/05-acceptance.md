# Acceptance Criteria（驗收）

- `docker compose up` 可啟動 Odoo 與 Postgres
- `make smoke` 能在 180 秒內得到 200/302/303 回應
- PR 若修改 `addons/**` 或 `docker-compose.yml`，且未同步更新 `specs/**`，CI 失敗
- 可在 Odoo Apps 中看到並安裝「經銷商」模組（dealer）