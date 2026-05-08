# 開發清單（04-tasks）— Metabase 車行月銷量與累計趨勢

## 程式

- [x] `scripts/metabase_add_p20_dealer_monthly_trends.py`

## Metabase 變更

- [x] `P20-1 車行月銷量（長條圖）` 已更新為原始車行名稱維度
- [x] `P20-1 車行月銷量（長條圖）` 已調整為不造成過長捲動的緊湊版位
- [x] `P20-2 車行累計銷量（折線圖）` 已建立並掛入 P20 dashboard
- [x] `P20-3 車行月銷量明細（表格）` 已建立並掛入 P20 dashboard
- [x] `P20-3 車行月銷量明細（表格）` 已調整為每列三組資料的矩陣版型，欄頭不顯示 A/B/C，並於銷量欄套用非藍色 heatmap
- [x] `領牌年月` 篩選器已改為字串下拉式
- [x] `能源類型` 篩選器已建立並對應三張卡片
- [x] `車行名稱` 篩選器已建立並對應兩張圖表
- [x] `銷售來源` 篩選器保留並套用至兩張圖表
- [x] `領牌年月` 預設值已設為最近半年（含當前月份）
- [x] `銷售來源` 預設值已設為 `車行`

## 驗證

- [x] `python3 scripts/metabase_add_p20_dealer_monthly_trends.py --apply`
- [x] `curl http://localhost:3000/api/health`
- [x] `make smoke`
- [x] `docker compose ps`