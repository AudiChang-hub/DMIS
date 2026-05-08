# 開發清單（04-tasks）— channel rule 朋友推薦/代申請補助歸店內

## 規格

- [x] `specs/025-channel-rule/01-spec.md`
- [x] `specs/025-channel-rule/02-plan.md`
- [x] `specs/025-channel-rule/03-tasks.md`
- [x] `specs/025-channel-rule/05-acceptance.md`

## 程式

- [x] `addons/dms_report_ds/models/ds_sales_report.py`
- [x] `dealer` / `dealer_not_null` 對 `朋友推薦` 顯示為 `店內`
- [x] `dealer` / `dealer_not_null` 對 `代申請補助` 顯示為 `店內`

## 驗證

- [x] `docker compose exec -T odoo odoo --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo -d dmis_dev -u dms_report_ds --stop-after-init`
- [x] `docker compose restart odoo`
- [x] `docker compose exec -T db psql -U odoo -d dmis_dev -c "select sales_source, sales_type, dealer from ds_sales_report where dealer = '朋友推薦';"`
- [x] `docker compose exec -T db psql -U odoo -d dmis_dev -c "select dealer, dealer_not_null, sales_source, sales_type from ds_sales_report where sales_source = '店內員工' and sales_type = '本店';"`
- [x] `docker compose exec -T db psql -U odoo -d dmis_dev -c "select dealer, dealer_not_null, sales_source, sales_type from ds_sales_report where dealer in ('代申請補助', '店內') or dealer_not_null in ('代申請補助', '店內');"`
- [x] `docker compose ps`
- [x] `make smoke`
