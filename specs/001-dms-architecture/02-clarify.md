# Clarify（澄清）

Why / 為何

- 我們需要一個穩定且可長期演化的架構憲章，以避免專案變成功能碎片（feature soup）。
- 001 應作為平台性的架構錨點（architecture anchor），將設計原則、資料分層、規則版本化等核心決策集中管理，避免每個功能模組各自決策造成破壞性相依。

What / 做什麼

- 將 `specs/001-dms-core` 的角色轉為歷史追溯與範例，並把正式的架構憲章移至 `specs/001-dms-architecture/`。
- 規範本次憲章包含：Bounded Context 定義、三層資料分層原則、規則與計算版本化策略、Docker/Infra 分層與責任、以及未來擴張策略。
- 本憲章只描述高階原則與設計決策；具體功能欄位或公式細節應在後續 `specs/00X-*` 中定義（002 起為功能規格）。

範圍與限制

- 不會在本文件列出任何具體業務欄位或獎金公式。
- 本文件所列決策為憲章級，變更需經過 PR 與審核流程，並附對應的 migration / compatibility 計畫（若為 breaking change）。
