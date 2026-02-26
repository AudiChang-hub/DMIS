# 憲章層任務（Governance Tasks）

此文件列出本架構憲章（001）層級可驗收的治理任務，供審查者、架構師與 PM 使用。實際實作（新增 module、建立 outbox table、部署 worker、建立 MV 等）應拆分至 002+ 的規格與實作任務。
## 目標

- 確保本憲章的章節、硬規則與驗收標準完整且可被審查。
- 提供 002+ 規格拆分指引與驗收鏈接，確保下層規格遵循憲章原則。
## 主要治理任務

- 補齊與維護憲章內容
   - 說明：定期檢視並補齊 `01-specify.md` 中的章節與硬規則（Bounded Context、Data Layering、計算版本化、Container 責任邊界等）。
   - 驗收標準：變更通過 PR 審查，且所有被變更條款均有相依 002+ 規格或遷移說明。
- 定義 DoD（Definition of Done）與驗收標準
   - 說明：為後續 002+ 規格建立共通 DoD 條目（例如：匯入必須支援 idempotent 與 replay、計算規則需具備版本化與歷史重算能力、報表層為唯讀等）。
   - 驗收標準：每項 DoD 條目以可測試的驗收準則陳述，並在 002+ 規格中引用。
- 建立 002+ 規格拆分指引
   - 說明：提供模板與範例（例如：`002-sales-core`、`003-import-pipeline`、`004-incentive-engine`、`005-analytics`），說明每個規格應如何對應到憲章的章節與驗收標準。
   - 驗收標準：至少提供 4 個示例規格，且每個示例都包含：簡介、受影響的憲章條款、必要遷移步驟、驗收測試定義。
## 關於原先的實作清單

- 原先包含的具體實作項目（例如：新增 module、建立 outbox table、改 docker-compose 加 worker、建立 materialized view）已移轉至 002/003/004/005 的待辦。此處僅保留連結與驗收語句：
   - 連結範例：`See specs/002-sales-core.md`（實作細節應在該文件中）。
   - 驗收語句範例："Sales import pipeline 能夠在重放相同檔案時不重複建立交易（idempotent），並提供完整匯入稽核紀錄。"
## 審查流程（Charter-level）

- 憲章的任何變更需以 PR 提出，且至少包含：變動摘要、相依 002+ 規格或遷移計畫、回滾策略。
- 若變更為 breaking change，PR 必須包含兼容性窗口與遷移步驟，經過架構評審後方可合入。
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
