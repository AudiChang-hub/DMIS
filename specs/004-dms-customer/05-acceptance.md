# 驗收條件（05-acceptance）— dms_customer

## 安裝驗收
- [ ] `--stop-after-init` 升級 dms_customer 無錯誤
- [ ] `/web/login` HTTP 200

## 功能驗收
- [ ] 首頁出現「DMS 客戶管理」App 圖示
- [ ] 客戶清單預設只顯示 is_dms_customer=True 的聯絡人
- [ ] 新增客戶：勾選「DMS 客戶」後存檔，出現在客戶清單
- [ ] 填入生日（西元），民國生日欄位自動顯示正確（e.g. 1990/01/15 → 079/01/15）
- [ ] 可在客戶 form 的「舊車資訊」頁籤新增/刪除舊車記錄
- [ ] 搜尋身分證字號可找到對應客戶
