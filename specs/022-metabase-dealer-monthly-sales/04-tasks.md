# 開發清單（04-tasks）— Metabase 車行月銷量與累計趨勢

## 程式

- [x] `scripts/metabase_add_p20_dealer_monthly_trends.py`

## Metabase 變更

- [x] `P3-1 車行月銷量（長條圖）` 已更新為原始車行名稱維度
- [x] `P3-1 車行月銷量（長條圖）` 已調整為不造成過長捲動的緊湊版位
- [x] `P3-2 車行累計銷量（折線圖）` 已建立並掛入 P3 dashboard
- [x] `P3-3 車行月銷量明細（表格）` 已建立並掛入 P3 dashboard
- [x] `P3-4 車行區域銷量排行（長條圖）` 已建立並掛入 P3 dashboard
- [x] `P3-4 車行區域銷量排行（長條圖）` 已改為直接使用 `dealer_region_district` 欄位的 field-backed query，`未設定` 也可作為可點擊維度值
- [x] `ds_sales_report.dealer_region_district` 已加入 `網路平台 -> 網路` 的前置分類規則，讓 P3-4 與 `車行區域` 篩選可直接辨識網路通路
- [x] `ds_sales_report.dealer_address` 已在 `display_dealer_name` 空白且報表 fallback 為 `馭盛` 時改用 `馭盛` 主檔地址，讓 `dealer_region_city` / `dealer_region_district` 與 `dealer` 顯示一致
- [x] `ds_sales_report.dealer` / `dealer_not_null` 已將 `朋友推薦` / `代申請補助` 正規化為 `馭盛`，且 `dealer_address` 同步 fallback 到 `馭盛` 主檔地址
- [x] `P3-3 車行月銷量明細（表格）` 已調整為每列三組資料的矩陣版型，欄頭不顯示 A/B/C，並於銷量欄套用非藍色 heatmap
- [x] `領牌年月` 篩選器已改為字串下拉式
- [x] `能源類型` 篩選器已建立並對應四張卡片
- [x] `車行縣市` 篩選器已建立並對應四張卡片
- [x] `車行區域` 篩選器已建立並對應四張卡片
- [x] `車行名稱` 篩選器已建立並對應四張卡片
- [x] `銷售來源` 篩選器保留並套用至四張卡片
- [x] `領牌年月` 預設值已設為最近一年（12 個月份，含當前月份）
- [x] `銷售來源` 預設值已移除

## 驗證

- [x] `python3 scripts/metabase_add_p20_dealer_monthly_trends.py --apply`
- [x] `curl http://localhost:3000/api/health`
- [x] `make smoke`
- [x] `docker compose ps`