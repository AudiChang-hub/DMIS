# 實作任務（03-tasks）— dms_sale 匯入補正

- [x] 補充 `01-spec.md` 的匯入/同步規則與分期正規化需求
- [x] 新增 `02-plan.md` 說明本次修補範圍
- [x] 修正 `addons/dms_sale/models/order_sync.py` 的 xlsx fallback 合併策略
- [x] 修正 `addons/dms_sale/models/order_sync.py` 的分期公司/期數解析
- [x] 修正 `addons/dms_sale/models/order_sync.py` 的重同步更新既有訂單規則
- [x] 重啟 Odoo 並重跑指定資料夾驗證
- [x] 執行 `docker compose ps` 與 `bash scripts/smoke_odoo.sh` 驗證服務恢復
- [x] 修正 `addons/dms_sale/wizard/excel_import_wizard.py` 的車型匹配 fallback，支援模板 family/model/code 對應
- [x] 重啟 Odoo 並驗證 A1 Excel 訂單可命中既有 `dms.product`
- [x] 補上 `dms.sale.order` 的跨來源同單比對 helper
- [x] 修正 `addons/dms_sale/models/order_sync.py`，命中既有 Excel 訂單時改為更新原單
- [x] 修正 `addons/dms_sale/wizard/excel_import_wizard.py`，命中既有 OrderProcessor 訂單時改為更新原單
- [x] 重啟 Odoo 並驗證 `賴佳郁`、`陳志豪` 類型的跨來源匯入不再新增第二筆