# 油車銷售統計：唯讀來源核對（2026/09/08）

原頁 `p_vi50zol3wd`；屬紅勾範圍。以下是設定查核，不是已完成重建。
資料來源清單僅一筆 `PostgreSQL - grafana_US_Sales`（ds0，100 圖表），沒有修改連線或儲存原設定。

## 圖表

| 元件 | 維度／系列 | 指標 | 限制與排序 |
| --- | --- | --- | --- |
| cd-ri50zol3wd | LicenseDate 年→月，預設月／Sales Source | Record Count | 主軸24、系列10，其他皆關；日期遞減、數量遞減 |
| cd-511eacq9yd | LicenseDate 日期／Model | Record Count | 主軸20、系列10，其他皆關；日期遞減、數量遞減 |
| cd-o720nfq9yd | Model | Record Count | 前20、其他關；數量遞減 |

- 三圖皆有汽油車篩選器與排除空白資料；日期範圍維度 LicenseDate，自動 All available dates。
- 汽油車篩選器已開啟確認：包含 `Energy Type` 等於 `油車`，只有一個子句；儲存按鈕停用，未修改。
- 三圖皆允許交叉篩選與排序；長條圖縮放關閉，每日圖下鑽關閉。
- 每日油車圖系列只有10，與電動車圖20不同，不可直接不加核對地複製設定。

## 明細 cd-ui50zol3wd

- 維度依序：領牌日期、車行、類型、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖。
- 指標：收款價。各顯示名稱的底層欄位仍須逐一核對，不能僅憑名稱認定。
- 每頁10；觀察到752分組列；摘要列關閉。
- 第一排序 SortLicenseDate 遞減，第二排序 Sales Source 遞減。
- 同上固定條件與日期範圍；交叉篩選關閉、新分頁連結開啟。

## 尚未釐清

- 原公式與已匯出電車／平台列的分類差異未查明，不能直接改成子字串匹配湊數。
- Google 官方 REGEXP_CONTAINS 說明指出 REGEXP_MATCH 預設匹配完整值；本次再次查核，仍不構成連接器實際執行或資料快取一致性的證據。
  參考：https://cloud.google.com/looker/docs/studio/regexpcontains
- 此頁尚未建立候選草稿、跨來源對帳或正式逐頁驗收；原始資料、訂單、金額均未修改。
