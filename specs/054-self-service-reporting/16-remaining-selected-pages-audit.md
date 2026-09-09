# 剩餘紅勾頁核對與候選設定（2026/09/09）

只讀取原報表編輯介面；未儲存原篩選器、未修改資料來源。以下是來源核對及實作進度，不是完整驗收證明。

## 車型 X 顏色：p_ppopd2w7wd

月份控制 `.cd-npopd2w7wd`；四張長條圖，主維度與細目均為 CarColor，Record Count；主要 100、系列 10、Other 均關閉；LicenseDate 全可用日期；主要及次要 Count 降冪，變更排序開啟。各圖均 Model 非 NULL。

| 圖 | 圖表 ID | 原型號條件 | 交叉篩選 |
| --- | --- | --- | --- |
| FUN | opopd2w7wd | 包含 EV060，不是性別頁的 EV060L | 關 |
| RUN | xf0tnfx7wd | EV076 開頭，排除精確 EV076SZV | 開 |
| 70 皮帶 | j6iejhx7wd | EV070 開頭，不是性別頁的包含 | 關 |
| 76 皮帶 | rjotfv09wd | 精確 EV076SZV | 關 |

DMIS 候選將重複的 CarColor／CarColor 用單分類長條表達，沒有刪掉不同分類維度；仍需驗證色彩與提示。原圖系列 10 的限制與超限顯示待勾稽。

## 性別 X 車型顏色：p_auqkqjx7wd

月份 `.cd-e2pkqjx7wd`；四張 CarColor／sex／Record Count 長條圖，主要 100、系列 10、Other 關閉，LicenseDate 全可用日期。使用已核對的 FUN_性別、RUN_性別、70B_性別、76B_性別，以及 Model 非 NULL。

- FUN `.cd-7tqkqjx7wd`、RUN `.cd-8tqkqjx7wd`：Count 降冪／Count 降冪。
- 70 `.cd-9tqkqjx7wd`、76 `.cd-otig0y09wd`：Count 降冪／sex 降冪。
- RUN 交叉篩選開，其餘關；四圖都可排序。
- 附表 `.cd-o652r68bxd`：CarColor、OwnerName、sex、ID_No／Record Count；僅 Model 非 NULL，**不限上述四個車型**；LicenseDate 全可用日期，100 筆分頁，Count 降冪，摘要與交叉篩選關、新分頁開。
- 證號遮罩選擇已提出使用者確認；候選目前只提供訂單明細核對，附表完整分組、100 筆分頁尚未完成，不可視為交付。

## 油車車行銷售：p_qr8kpyn3wd

車行與月份控制 `.cd-or8kpyn3wd`／`.cd-nr8kpyn3wd`。

- `.cd-mr8kpyn3wd`：橫向車行名稱／LicenseDate 年月／Count，50 主分類 Other 關、20 系列 Other 開，Count 降冪／月份降冪；交叉與排序開、縮放關。
- `.cd-pr8kpyn3wd`：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券/匯款、公司贈品、訖／收款價。**沒有電動車車行頁的備註欄**。10 筆分頁，SortLicenseDate 降冪，摘要與交叉關、新分頁開。
- 兩者均油車＋車行＋Model 非 NULL，LicenseDate 全可用日期。

## 油車台數：p_lrht80w3wd

車行與月份控制 `.cd-jrht80w3wd`／`.cd-hrht80w3wd`。

- 彙總 `.cd-irht80w3wd`：車行／台數，25 筆分頁、Record Count 降冪，交叉及新分頁開。
- 明細 `.cd-krht80w3wd`：領牌日期、車行、車主、車型、顏色、車牌／獎勵金，25 筆分頁、LicenseDate 降冪，新分頁開。
- 兩者均油車＋車行＋Model 非 NULL，LicenseDate 全可用日期。
- 獎勵金依使用者要求改為 DMIS 已保存獎金分配；共用按訂單先彙總的查詢，不將多筆獎金 JOIN 後倍增台數、車價或傭金。

## 候選與未完成清單

`SOURCE_TEMPLATES` 已涵蓋紅勾 13 頁；建立命令全部保持 admin 草稿、不覆寫既有編輯、不自動發布。

仍待：跨來源逐筆差異、人口附表分組與證號處理、彙總分頁、電動車車行原備註映射、方向及色彩與互動完整驗證、CI 與部署。完成分母仍 13，完整驗收目前 0／13。
