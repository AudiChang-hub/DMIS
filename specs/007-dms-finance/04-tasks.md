# 04 — Tasks：財務結算模組開發任務

## Sprint 1（本 PR）

- [x] 建立 specs/007-dms-finance/ 下的五份規格文件
- [x] 建立 `addons/dms_finance/` 模組骨架
- [x] 實作 `dms.sale.finance` 主模型（含計算欄位）
- [x] 實作 `dms.sale.finance.income` 收入明細模型
- [x] 實作 `dms.sale.finance.expense` 支出明細模型
- [x] 建立自動帶入邏輯（on_create, populate_defaults）
- [x] 繼承 `dms.sale.order` 加入 Smart Button（finance_count）
- [x] 建立 list/form/search 視圖
- [x] 建立繼承 dms.sale.order 的 Smart Button 視圖
- [x] 設定 security/ir.model.access.csv
- [x] 設定主選單「財務結算」
- [x] 更新 README.md 模組列表
- [x] 升級模組驗證無 ERROR

## Sprint 2（下一 PR）

- [ ] 加入「重新帶入預設金額」按鈕（覆蓋現有明細前需確認）
- [ ] 加入結算狀態機（草稿→確認）
- [ ] Phase 4 BI 報表初步規劃
