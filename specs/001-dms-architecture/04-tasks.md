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

## 後續規格拆分（002+）

下列為本憲章接續的建議規格拆分（範例目錄）。每項僅包含目標與必要的驗收語句，實作細節應放在對應的 002+ 文件中。

- `specs/002-sales-core/`
  - 目標：定義 Sales Context 的核心交易模型、匯入接口與 DoD，確保交易資料在 Core 的一致性與完整性。
  - 驗收語句：交易匯入/建立流程必須支持 idempotent 與 replay；所有交易記錄擁有可追溯的匯入稽核資訊。

- `specs/003-import-pipeline/`
  - 目標：描述 Import Context 的管線、Staging schema 與錯誤處理策略，確保外部資料可安全落地與重放。
  - 驗收語句：外部/Excel 檔案必須先落在 Staging，重放相同匯入不得造成重複或資料失敗（idempotent & replayable）。

- `specs/004-incentive-engine/`
  - 目標：定義 Incentive Context 的規則版本化、計算流程與審計模型，保證計算結果可重現並可追溯規則版本。
  - 驗收語句：計算規則具版本號與生效區間；計算結果需保留 raw inputs 與 computed outputs 分離的紀錄，並可依指定位準回算歷史結果。

- `specs/005-analytics/`
  - 目標：規範 Analytics Context 的讀取模型、materialized views 與 BI 存取策略，確保報表層為唯讀且具溯源性。
  - 驗收語句：Reporting 層為唯讀，且所有 materialized views 包含回溯至 Core 或 Staging 的來源連結；BI 查詢不得直接改寫 Core。

