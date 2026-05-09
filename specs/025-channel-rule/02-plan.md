# 實作計畫（02-plan）— channel rule 朋友推薦/代申請補助歸店內

## 背景

- `ds_sales_report` 目前只以空白 dealer、`網路平台` 與 `文傑` 關鍵字判斷內部通路，其餘一律歸為 `車行`。
- 現場資料中存在 `display_dealer_name = '朋友推薦'` 與 `display_dealer_name = '代申請補助'`，目前都不應被歸為 `車行`。

## 本次變更

1. 在 `spec 025` 明確定義 `朋友推薦` 與 `代申請補助` 為店內引薦/代辦單，不得歸為 `車行`。
2. 修改 `addons/dms_report_ds/models/ds_sales_report.py` 的 SQL view CASE，將 `朋友推薦` 與 `代申請補助` 歸入內部通路。
3. 同步將 `dealer` / `dealer_not_null` 顯示值正規化為 `馭盛`，並讓車行地址解析也 fallback 到 `馭盛` 主檔。
4. 升級 `dms_report_ds` 模組並重啟 Odoo，讓 SQL view 重建。
5. 以 SQL 驗證 `朋友推薦` 與 `代申請補助` 已改為 `sales_source='店內員工'`、`sales_type='本店'`，並在 dealer 維度顯示為 `馭盛`。
6. 同步將 `中古車` 資料列在 dealer 維度、`sales_type` 與地址解析上正規化為 `馭盛` / `本店`。
6. 執行 `docker compose ps` 與 `make smoke` 確認服務恢復正常。
