# 驗收條件（05-acceptance）— dms_product

## 安裝驗收
- [ ] `--stop-after-init` 升級 dms_core + dms_product 無錯誤
- [ ] `/web/login` HTTP 200

## 功能驗收
- [ ] 登入後 DMS → 產品管理 選單可見
- [ ] 產品清單（list）預設顯示 8 欄（brand_id、name、model、year、brake_type、energy_type、color、active）
- [ ] 勾選第 16 個欄位時出現 warning notification 且 checkbox 自動回復未勾選
- [ ] 新增油車產品：基本資料含年份/啟用；動力規格(油車)頁籤可見；電車頁籤隱藏
- [ ] 新增電車產品：電車頁籤可見；油車頁籤隱藏
- [ ] brand_id 下拉選單顯示 dms.brand 中的品牌資料（dms_core 提供）
- [ ] 產品 active=False 後，預設 list 不顯示該筆（歸檔行為）
