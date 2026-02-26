# 可執行重構任務清單（Tasks）

以下為可逐條完成、可驗收的任務，供第一階段（MVP Core）執行：

1. 建立 `specs/001-dms-architecture/`（完成）與四份文件（01~04）。
   - 驗收：資料夾與檔案存在且內容可讀。

2. 在 Odoo module 層級標註 Domain Owner（metadata）：
   - 於 `addons/dms_core/__manifest__.py` 加入 `category` 與 `maintainer` 欄位說明（非破壞性）。
   - 驗收：manifest 已包含 maintainer 字段（PR）。

3. 實作 Staging 層匯入範例（最小）：
   - 新增 `addons/dms_import` skeleton module（含 model staging.table 與基本 import script）。
   - 驗收：能把 CSV 匯入至 staging table，並可重跑且結果一致。

4. 建立 Outbox table 與 consumer skeleton：
   - 新增 `outbox` model（id, payload, event_type, state, created_at）與管理介面（非公開）。
   - 驗收：能在 DB 中看到 outbox entry，consumer 能成功讀取並標記完成。

5. 建立 worker-compose profile：
   - 更新 `docker-compose.yml` 增加 `worker-import`、`worker-compute` 服務（可透過 profile 啟動）。
   - 驗收：使用 `docker compose --profile workers up -d` 可以啟動兩個 worker 服務。

6. 建立 Reporting Layer 範例：
   - 實作一個 materialized view（例如 `mv_sales_daily`）並加入 refresh script。 
   - 驗收：能建立 view 並在資料變動後手動 refresh，查詢回傳預期結果。

7. 規則版本化 PoC：
   - 建立 `rule_version` table（id, rule_json, effective_start, effective_end, version_label）。
   - 驗收：能新增多個版本並在計算時選擇指定版本回算。

每項 task 完成時，請建立獨立 branch 與 PR，PR 必須包含對應的 specs 更新或指向 `specs/001-dms-architecture/` 的相關段落。
