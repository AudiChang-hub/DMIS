# 實作計畫（02-plan）— Metabase 車行月銷量與累計趨勢

## 背景

- 現有 P3 dashboard 只有一張按月份與通路維度統計的圖，缺少使用者要求的「車行月銷量」與「累計銷量」組合視角。
- 目前 dashboard 雖已有 `車行區域` 初步概念，但還缺少 `車行縣市` 的上層篩選與直接呈現熱門地區的排行圖。

## 實作步驟

1. 新增一支專用 Metabase API 腳本，定位並更新 P3 dashboard。
2. 將既有 P3 月銷量圖改為以原始 `dealer` 欄位顯示車行名稱。
3. 將 P3 月銷量圖調整回緊湊版位，避免為了展開全部 dealer 而造成 dashboard 過長。
4. 新增一張 native SQL 折線圖，計算每個車行依月份累加的銷量。
5. 新增一張車行月銷量明細表，提供完整 dealer 清單，並以每列三組資料的矩陣版型與強化樣式提升判讀性。
6. 於 `ds_sales_report` 新增 `dealer_region_district` 與 `dealer_region_city` 欄位，來源明確取自 `dms_dealer.address` 解析出的車行區域與縣市。
7. 在 P3 dashboard 新增 `P3-4 車行區域銷量排行（長條圖）`，直接呈現熱門地區。
8. 將 P3 dashboard 篩選器調整為 `領牌年月`、`銷售來源`、`能源類型`、`車行縣市`、`車行區域`、`車行名稱` 六個下拉式欄位。
9. 將 `領牌年月` 預設為腳本套用時計算的最近一年（12 個月份，含當前月份），並移除 `銷售來源` 的預設值。
10. 執行腳本套用後，透過 Metabase API 與 public dashboard 驗證圖表、明細表與篩選器可正常顯示。
11. 若 P3-4 出現 `未設定` 這類實際維度值，必須保留為可點擊的 field-backed breakout，避免因 native alias 失去與其他圖表/表格的互動能力。
12. 若資料列類型屬於 `網路平台`，則 `dealer_region_district` 應在 `ds_sales_report` 層直接歸類為 `網路`，避免 P3-4 再次落入 `未設定`。
13. 若資料列因 `display_dealer_name` 空白而依既有規則 fallback 顯示為 `馭盛`，則 `dealer_region_city` 與 `dealer_region_district` 應同步改用 `馭盛` 車行主檔地址解析，避免 P3-4 與篩選器出現名稱為 `馭盛` 但區域為 `未設定` 的不一致。
14. 若資料列屬 `朋友推薦` / `代申請補助` 這類店內引薦或代辦單，則應在 dealer 維度正規化顯示為 `馭盛`，並同步以 `馭盛` 主檔地址解析車行縣市與區域，但 `sales_source` / `sales_type` 仍保留 `店內員工` / `本店`。