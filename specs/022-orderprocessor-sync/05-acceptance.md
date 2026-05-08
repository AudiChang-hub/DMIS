# 驗收標準（05-acceptance）— OrderProcessor 暫存區

## 功能驗收

- [x] 手動觸發 OrderProcessor 同步後，會在 `dms.sync.log` 看到新的暫存紀錄
- [x] 暫存紀錄可查看 `customer_name`、`id_number`、`customer_phone`、`source_product_name`、`dealer_id` 等解析結果
- [x] 暫存紀錄可查看原始 `result.json` 與 xlsx fallback 內容
- [x] `重新同步` 後只會重建暫存紀錄，不會刪除或改寫既有 `dms.sale.order`
- [x] 在 Excel 匯入仍存在的期間，OrderProcessor 新資料不會新增 `sale_origin='order_processor'` 的銷售訂單

## 系統驗收

- [x] `docker compose exec -T odoo odoo --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo -d dmis_dev -u dms_sale --stop-after-init` 無 ERROR
- [x] `docker compose ps` 顯示 `odoo`、`db` 正常
- [x] `bash scripts/smoke_odoo.sh` 通過