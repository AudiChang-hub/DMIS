# 電動車平台／車行分頁核對（2026/09/08）

## 電動車－網路平台銷售統計

原頁 `p_oyi9bhn3wd`（第 4 個可見頁），不是三圖電動車頁的單純複製。

- 控制項：平台名稱、領牌年月。
- `cd-s6h9bhn3wd`：一張水平堆疊，領牌年→領牌年月（預設月），
  系列「平台名稱」實際為 Dealer_NotNull / calc_fbnrfzm2wd，Record Count。
  前 24 群、10 系列，其他皆關；LicenseDate 全期間，主排序 LicenseDate 日期遞減，
  次排序 Record Count 遞減；交叉篩選／變更排序開、縮放關。
- 固定條件：電動車＋排除 Model NULL＋Sales Source 等於「網路平台」。
- `cd-nyi9bhn3wd`：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券／匯款、
  平台贈品、公司贈品、訖，指標收款價。292 列、每頁 10；同固定條件，LicenseDate
  全期間，SortLicenseDate 遞減，摘要／交叉篩選關，新分頁連結開。
- 舊名稱清洗僅作報表維度：空名稱為馭盛，移除 RE2 `\s` 的 ASCII 空白並轉大寫。
  不改寫合作車行、不把同名訂單合併。

## 電動車－車行銷售統計

原頁 `p_x9z82fo3wd`（第 5 個可見頁）。

- 控制項：車行名稱、領牌年月。
- `cd-1hz82fo3wd`：水平堆疊主維度為**車行名稱**（不是月份），
  系列 LicenseDate 年月；Record Count，前 50 車行、20 月份系列，系列其他開。
  LicenseDate 全期間，台數遞減、次排序月份遞減；下鑽關，交叉篩選／排序開，縮放關。
- 固定條件：電動車＋排除 Model NULL＋Sales Source 等於「車行」。
- `cd-w9z82fo3wd`：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券／匯款、
  公司贈品、訖、備註（Notes / _Notes_），指標收款價。231 列、每頁 10，
  同固定條件／LicenseDate 全期間／SortLicenseDate 遞減。摘要／交叉篩選關，新分頁連結開。
- 車行主維度實際來源欄位、Notes 對應與可公開範圍仍待補核對，不能少一欄就宣稱完成。

## 參考規則

- [Google RE2 語法](https://github.com/google/re2/blob/main/doc/syntax.txt)：`\s` 為 `[\t\n\f\r ]`，
  不等於 Python 預設 Unicode 空白，不擅自移除中文全形空白。
- [Google TRIM](https://docs.cloud.google.com/data-studio/trim)：移除前後空格。

兩頁均尚未完成數據勾稽、樣式及互動驗收。

## 平台增量驗證

- 平台核對草稿：一張月份／平台堆疊與指定順序的歷史獎勵明細，admin 專用且不自動發布。
- 報表測試 63 項通過；完整測試 849 項，845 通過、4 略過。
- 額外驗證 ASCII 空白清洗、同名分組下鑽、能源條件交集、既有明細欄位順序在儲存後保留。
- 隔離桌面實測：MOMO／PC 分組與明細對應，儲存後欄位順序正確，表格溢出限定在表格容器。
- 手機驗證未完成：工具要求 390px 後仍回報 1600px，不能當作手機實測通過。
- 本節僅為本機增量證據；部署與來源完整數值比對須另行確認。
