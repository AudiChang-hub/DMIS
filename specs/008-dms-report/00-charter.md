# 00 — Charter：報表分析模組（dms_report）

## 宗旨

整合 dms_sale 與 dms_finance 的資料，提供銷售量、利潤、傭金等多維度 BI 報表，讓管理者能直接在 Odoo 中查看跨月/跨車款/跨車行的趨勢，減少手動匯總 Excel 的工作。

## 範圍

- 新增 `dms_report` 模組於 `addons/dms_report/`。
- 不建立新資料表，直接使用 `dms.sale.order` 與 `dms.sale.finance` 作為資料來源。
- 提供三個報表：銷售報表、利潤報表、傭金報表。
- 主選單「報表分析」，sequence=40，位於財務結算之後。

## 目標用戶

- 管理者：查看月度銷售趨勢、淨利走勢、車行傭金分配。
- 業務主管：比較不同車款的銷售表現。

## 成功指標

1. 安裝後選單出現「報表分析」子項目。
2. 銷售報表可用 Pivot 依月份/車款 group by。
3. 利潤報表可展示逐月淨利走勢 Graph。
4. `make smoke` 180 秒內通過，無 ERROR。

## 限制

- Odoo 16 Community Edition，不使用 Enterprise 的 Dashboard。
- 初期只提供三個基礎報表，後續可擴充精品報表等。
