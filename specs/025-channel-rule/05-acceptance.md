# 驗收標準（05-acceptance）— channel rule 朋友推薦/代申請補助歸店內

## 功能驗收

- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料不再顯示 `sales_source = '車行'`。
- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料應顯示 `sales_source = '店內員工'`。
- [x] `ds_sales_report` 中 `dealer = '朋友推薦'` 的資料應顯示 `sales_type = '本店'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '朋友推薦'` 的資料，顯示欄位應改為 `dealer = '馭盛'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '朋友推薦'` 的資料，不應再顯示 `dealer_not_null = '朋友推薦'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料不再顯示 `sales_source = '車行'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料應顯示 `sales_source = '店內員工'`。
- [x] `ds_sales_report` 中 `dealer = '代申請補助'` 的資料應顯示 `sales_type = '本店'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '代申請補助'` 的資料，顯示欄位應改為 `dealer = '馭盛'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '代申請補助'` 的資料，不應再顯示 `dealer_not_null = '代申請補助'`。
- [x] `ds_sales_report` 中原始 `display_dealer_name IN ('朋友推薦', '代申請補助')` 的資料，`dealer_region_city` / `dealer_region_district` 應顯示 `馭盛` 主檔地址對應的縣市與行政區，而非 `未設定`。
- [x] `ds_sales_report` 中原始 `display_dealer_name = '中古車'` 的資料，應顯示 `dealer='馭盛'`、`sales_source='馭盛'`、`sales_type='本店'`，且 `dealer_region_city` / `dealer_region_district` 應顯示 `馭盛` 主檔地址對應的縣市與行政區。

## 系統驗收

- [x] `docker compose ps` 顯示 `odoo`、`db`、`metabase` 服務為 `Up`。
- [x] `make smoke` 通過。
