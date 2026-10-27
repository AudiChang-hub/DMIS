# 實作任務（03-tasks）— channel rule 朋友推薦/代申請補助歸店內

- [x] 補齊 `specs/025-channel-rule/01-spec.md` 的 `朋友推薦` 分類規則
- [x] 擴充 `specs/025-channel-rule/01-spec.md`，將 `代申請補助` 一併定義為店內
- [x] 建立 `specs/025-channel-rule/02-plan.md`
- [x] 建立並完成 `specs/025-channel-rule/04-tasks.md`、`05-acceptance.md`
- [x] 修正 `addons/dms_report_ds/models/ds_sales_report.py` 的 `sales_source` / `sales_type` CASE
- [x] 修正 `addons/dms_report_ds/models/ds_sales_report.py` 的 `dealer` / `dealer_not_null` 顯示值
- [x] 修正 `addons/dms_report_ds/models/ds_sales_report.py` 的 `dealer_address` fallback，讓 `朋友推薦` / `代申請補助` 走 `馭盛` 主檔地址
- [x] 修正 `addons/dms_report_ds/models/ds_sales_report.py` 的 `中古車` 正規化規則，讓 dealer / sales_type / dealer_address 都視為 `馭盛`
- [x] 升級 `dms_report_ds` 模組並重啟 Odoo 讓 `ds_sales_report` view 重建
- [x] 驗證 `朋友推薦` 已改歸 `店內員工` / `本店`
- [x] 驗證 `代申請補助` 已改歸 `店內員工` / `本店`
- [x] 驗證 `朋友推薦` 不再出現在 `dealer` 顯示欄位
- [x] 驗證 `代申請補助` 不再出現在 `dealer` 顯示欄位
- [x] 執行 `docker compose ps` 與 `make smoke`
