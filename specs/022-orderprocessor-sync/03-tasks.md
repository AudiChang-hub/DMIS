# 實作任務（03-tasks）— OrderProcessor 暫存區

- [x] 更新 `01-spec.md`，將 OrderProcessor 改為 staging/debug 流程
- [x] 新增 `02-plan.md` 說明過渡期架構
- [x] 擴充 `addons/dms_sale/models/order_sync_log.py` 的暫存/debug 欄位
- [x] 修正 `addons/dms_sale/models/order_sync.py`，停止建立/更新 `dms.sale.order`
- [x] 修正 `addons/dms_sale/views/order_sync_log_views.xml`，改為顯示 staging/debug 資訊
- [x] 修正 `action_resync`，重跑時不再刪除銷售訂單
- [x] 升級 `dms_sale` 並驗證 OrderProcessor 新資料不再進入銷售大表
- [x] 執行 `docker compose ps` 與 `bash scripts/smoke_odoo.sh`
