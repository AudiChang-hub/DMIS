# 開發清單（04-tasks）— OrderProcessor 暫存區

## 程式

- [x] `addons/dms_sale/models/order_sync.py`
- [x] `addons/dms_sale/models/order_sync_log.py`
- [x] `addons/dms_sale/views/order_sync_log_views.xml`

## 行為調整

- [x] OrderProcessor 同步成功時僅建立 `dms.sync.log` 暫存紀錄
- [x] 暫存紀錄保存原始 JSON、xlsx fallback 與標準化後欄位快照
- [x] `重新同步` 僅重建暫存紀錄，不刪除 `dms.sale.order`
- [x] 選單名稱與畫面文案調整為 debug/staging 用途

## 驗證

- [x] `docker compose exec -T odoo odoo --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo -d dmis_dev -u dms_sale --stop-after-init`
- [x] `docker compose ps`
- [x] `bash scripts/smoke_odoo.sh`
