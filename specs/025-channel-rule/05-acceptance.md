# 驗收標準（05-acceptance）— channel rule 朋友推薦/代申請補助歸店內

## 功能驗收

- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料不再顯示 `sales_source = '車行'`。
- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料應顯示 `sales_source = '店內員工'`。
- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料應顯示 `sales_type = '本店'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '朋友推薦'` 的資料，顯示欄位應改為 `dealer = '店內'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '朋友推薦'` 的資料，不應再顯示 `dealer_not_null = '朋友推薦'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料不再顯示 `sales_source = '車行'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料應顯示 `sales_source = '店內員工'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料應顯示 `sales_type = '本店'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '代申請補助'` 的資料，顯示欄位應改為 `dealer = '店內'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '代申請補助'` 的資料，不應再顯示 `dealer_not_null = '代申請補助'`。

## 系統驗收

- [x] `docker compose ps` 顯示 `odoo`、`db`、`metabase` 服務為 `Up`。
- [x] `make smoke` 通過。
