# 原報表編輯模式查核紀錄

查核日期：2026/09/08。只讀 UI 設定，未變更原報表、連線或資料。
本文件是逐項查核紀錄，不代表 18 頁已完成重建或完成金額勾稽。

## 財務口徑已確認（優先於下方原站公式）

使用者已確認：傭金、獎金及實物應以 DMIS 業務規則為準，不採原報表固定公式。
下方公式僅留作來源稽核與差異說明，不作正式付款計算，也不另設預設舊口徑試算。
報表不得混入第二套傭金或把未發放實物方案當成已發放。

本次已在本機加入 `dealer_commission` 指標，唯讀加總 DMIS 保存的
`OrderOperationsProfile.dealer_commission_expense`，不是已付款。
依 `recipient` 分組時沿用既有有效歸屬規則；不再次加上獎金 allocation。
缺少收支資料時群組與完整合計顯示待補，明細及 CSV 同樣標示。
此指標暫不納入自訂四則試算及占比圖，避免未知金額被當成零。

本機驗證：報表測試 29 項及互動 Node 測試 4 項通過；Django check 無問題，
makemigrations --check --dry-run 無異動。完整 sales 測試 815 項完成，4 項 skipped；
此結果不代表 PostgreSQL CI 已通過。

隔離 SQLite／8024 真實瀏覽器驗證：編輯器選擇傭金指標、按歸屬分類、預覽、
發布測試報表成功；甲車行同頁明細包含 2 張（含原來源乙車行的轉歸屬訂單），
傭金欄位與口徑提示正確。原來源圓環顯示 1／3 與 2／3，各 33.3%／66.7%。
1440×900、820×1180、390×844 下檢查的畫面無橫向溢出；手機複選清單可展開、
Escape 可關閉；桌機明細使用卡片排列。僅夜間主題及上述路徑，不代表全站／全部主題驗收。
測試過程瀏覽器曾逾時，重新連接後繼續；暫時視窗尺寸已還原。
正式訂單與帳務未寫入。後續交付確認：`d3ef855` CI 34188566810 全部通過，
T470P 部署標記與 Git 均為此版本；正式健康檢查通過。唯讀登入驗證核對 1741 張
訂單及 7 群，明細、CSV 與 admin／一般帳號權限通過；臨時驗證工作階段已清除。
22 頁完整映射及獎勵逐單發放仍待完成，不將本批共用功能列入逐頁完成數。

## 已確認來源

- 原報表：SUZUKI銷售統計，檢視模式可見 18 頁；編輯模式「管理頁面」實際列出 22 頁。
- 資料來源管理顯示單一內嵌 PostgreSQL 來源 `PostgreSQL - grafana_US_Sales`。
- 使用範圍：100 個圖表、0 個變數；畫面狀態為運作中。
- 更新間隔 15 分鐘；社群視覺呈現存取權開啟。
- 欄位清單顯示 109 欄，其中 Dimensions 106。尚未逐欄讀完；不將此數量當作已完成映射。
- 不蒐集資料庫憑證；未開啟「編輯連結」。

## 已直接讀取的計算欄位

### age

欄位 ID：`calc_4p4z30q7wd`；數字，預設匯總「無」。

```text
YEAR(CURRENT_DATE()) - YEAR(Birthday)
```

這是依查閱當年的年份差，不是足歲，也不是領牌當時年齡。
重建時須保留原口徑的可追溯性，不得默默換成足歲。

### AgeGroup

欄位 ID：`calc_kdld65q7wd`；文字，預設匯總「無」。

```text
CASE
  WHEN age < 20 THEN "20歲以下"
  WHEN age BETWEEN 20 AND 29 THEN "20-29歲"
  WHEN age BETWEEN 30 AND 39 THEN "30-39歲"
  WHEN age BETWEEN 40 AND 49 THEN "40-49歲"
  WHEN age BETWEEN 50 AND 59 THEN "50-59歲"
  ELSE "60歲以上"
END
```

注意：標籤「20歲以下」實際條件是小於 20；空值沒有獨立分支。
缺少生日的實際分類仍需用資料驗證，不能宣稱已驗證。

### BasicBonus

欄位 ID：`calc_c3tclgn2wd`；數字，預設匯總「無」。

```text
IFNULL(FriendlyBonusOut, 0)
+ IFNULL(FirstSaleBonus, 0)
+ IFNULL(DealerCommOut, 0)
```

必須先核對這三個來源欄位對應 DMIS 的哪個歷史／有效快照金額。
不能直接用車價、單一基礎傭金或台數獎金取代。圖表層彙總方式待查。

### BrandType

欄位 ID：`calc_9v3dccl2wd`；文字，預設匯總「無」。
這是車行歸類，不是車輛廠牌；條件依序比對。

```text
CASE
 WHEN Dealer IS NULL OR Dealer = '' THEN '馭盛網推'
 WHEN REGEXP_MATCH(LOWER(Dealer), 'pc|momo|yahoo|燦坤|小樹購|百利市|friday|蝦皮') THEN '網路平台'
 WHEN REGEXP_MATCH(Dealer, '(鑫輝|特色|捷盛|祥銘|達能|立野|名豐|弘安)') THEN '光陽'
 WHEN REGEXP_MATCH(Dealer, '(永湛|宏堂|見元|萬全|百福|昌億|風火輪|皇韋|成峰|百呈|明達|東永|嘉順)') THEN '三陽'
 WHEN REGEXP_MATCH(Dealer, '(馳機|天佑|旭昇|宏偉|尚勁|德新|凱弘|鋐亞|群陽|德旺|駿翔|輪友|極昇|奕鈞|良澄|岩谷|昌勝|松祥|金利富|泳辰|源泰|旗成|嘉仁|金泰發|日信|名傑|昌勝(試乘車)|鈞鴻)') THEN '山葉'
 WHEN REGEXP_MATCH(Dealer, '(明毅|鑨來|阿松|佳峰|信益|鼎勝|上慶|合聰|宏昌|湖州|鉉豐)') THEN '一般車行'
 WHEN REGEXP_MATCH(Dealer, '(明輝|新隆|旭昶|欣益|富順|運豐)') THEN '台鈴'
 WHEN REGEXP_MATCH(Dealer, '(士辰|北野電能|北野)') THEN '睿能'
 WHEN REGEXP_MATCH(Dealer, '中古車') THEN '中古車'
 WHEN REGEXP_MATCH(Dealer, '彗星') THEN '一般車行'
 ELSE Dealer
END
```

REGEXP_MATCH 的實際比對語意及名稱例外不可擅改；需有原例與新結果對照測試。

### NumberOfUnitsBonus

欄位 ID：`calc_l4j17sn2wd`；Metrics，數字，自動匯總。

```text
CASE
 WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 5
 THEN 500 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
 WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 3
 THEN 200 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
 ELSE 0
END
```

門檻不是各級累進。達 5 台會全部乘 500；只統計 EV 開頭且 Model 非空的記錄。
不能改成所有電動車、全部訂單或各台個別計算；分組依圖表維度，仍須核對。

### TotalBonus

欄位 ID：`calc_4698u5n2wd`；Metrics，數字，自動匯總。
原公式是 `SUM(BasicBonus)` 加上完整複寫的上述 CASE 台數獎金公式。
不能對逐筆的 TotalBonus 再直接加總。

### 未計算的獎金來源欄位

來源欄位 `FirstSaleBonus`、`FriendlyBonusIn`、`FriendlyBonusOut`、
`VolumeBonus`、`YamahaBonusIn` 均為數字，預設匯總「總和」。
`VolumeBonus` 與計算欄位 `NumberOfUnitsBonus` 是不同欄位，不能混用。

## 已核對的固定篩選

以下數量是來源管理 UI 當下顯示的使用圖表數，不等於逐頁套用已核對。

| 條件 | 使用圖表數 |
| --- | ---: |
| 包含 Energy Type 等於油車 | 16 |
| 包含 Energy Type 等於電車 | 25 |
| 包含 SubsidyPlan 包含基隆公益 | 17 |
| 包含 Sales Source 等於網路平台 | 6 |
| 包含 Sales Source 等於車行 | 18 |
| 排除 Model 為空值 | 59 |
| FUN_顏色：包含 Model 包含 EV060 | 1 |
| 70B_顏色：包含 Model 開頭是 EV070 | 1 |
| 76B_顏色：包含 Model 等於 EV076SZV | 1 |

「年齡及車型篩選」使用於 2 個圖表，已開啟唯讀核對四個 AND 子句：

1. 包含 Model 開頭是 `EV`。
2. 排除 age 等於 `0`。
3. 排除 age 小於 `20`。
4. 排除 sex 等於 `未填寫或格式錯誤`。

管理清單另有男女 20–29、30–39、40–49 六個篩選（各 2 子句），
FUN/RUN/76B/70B 性別篩選（各 2 子句），RUN_顏色（2 子句），待逐一核對。

## 待完成

- 其餘計算欄位、三個 Metrics、每頁固定篩選、圖表層公式／排序／彙總。
- 100 個圖表對照、18 頁資料與功能重建；不能以通用模板取代原內容。
- 年齡／公司性別／個資顯示的品質處理需與原口徑區分，不改寫正式帳務。
- 自助編輯器與原表相容測試、UI 驗證、CI、正式部署與健康檢查。

## 佣金彙總的圖表層查核

頁面 `p_tkr5sfw3wd`（電動車 - 佣金明細表）：

- 維度：「領牌年月」、「車行」。維度別名對應尚未全部逐一開啟。
- 指標：「台數獎金」、「台數」、「總獎金」。
- 已開啟「台數」屬性，來源明確是 `Record Count`；匯總自動，比較計算／累計均無。
- 固定篩選：電動車篩選器、車行篩選器、排除空白資料。
- 日期範圍維度 LicenseDate；預設自動 All available dates。
- 分頁每頁 25；不顯示摘要列；排序 LicenseDate 日期遞減。
- 交叉篩選開啟；在新分頁中開啟連結開啟。
- 注意：台數獎金公式自身只數 EV 型號，`Record Count` 是圖表篩選後所有記錄，兩者分母可能不同。

## 編輯頁面清冊與舊規格差異

`specs/021-datastudio-report/01-datastudio-extraction.md` 與 `04-chart-details.md`
是歷史稽核來源，不是目前部署指示。兩份有 22／21 頁相互矛盾，且部分篩選標為推測；
此次以實際 UI 核對後的本文件補正，不重啟已退役 Odoo／Metabase。

在 18 個可見頁面以外，管理頁面另列：

1. 銷售機種統計：已開啟「控管瀏覽權限」，確認「一律向處於檢視模式的使用者隱藏頁面」為選取值。以取消退出，未修改。
2. 通路銷售統計：存在於管理清單，個別權限尚待核對。
3. 「基隆公益青年統計」的複本：存在於管理清單，個別權限尚待核對。
4. 基隆公益青年 客群X車型分析：存在於管理清單，個別權限尚待核對。

重建不能因舊規格漏頁而刪除內容，也不能把原隱藏頁當作公開頁發布。
額外頁面先作 admin 稽核／未發布候選，依核對結果保持可見性。
