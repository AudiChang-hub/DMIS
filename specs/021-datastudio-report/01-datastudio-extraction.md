# DataStudio 報表完整擷取結果

> **來源報表**：`https://datastudio.google.com/reporting/cdb5d959-40f4-40c7-b809-98da76ef4498`
> **報表標題**：SUZUKI銷售統計
> **資料來源**：PostgreSQL - grafana_US_Sales（嵌入式，別名 ds0）
> **欄位總數**：109（106 維度 + 3 指標）
> **計算欄位 (fx)**：17（15 維度 + 2 指標）
> **頁面數**：22

---

## 一、計算欄位 (fx) 公式 — 全 17 筆

### 1. age（維度，數字）
```sql
YEAR(CURRENT_DATE()) - YEAR(Birthday)
```

### 2. AgeGroup（維度，文字）
```sql
CASE
  WHEN age < 20 THEN "20歲以下"
  WHEN age BETWEEN 20 AND 29 THEN "20-29歲"
  WHEN age BETWEEN 30 AND 39 THEN "30-39歲"
  WHEN age BETWEEN 40 AND 49 THEN "40-49歲"
  WHEN age BETWEEN 50 AND 59 THEN "50-59歲"
  ELSE "60歲以上"
END
```

### 3. BasicBonus（維度，數字）
```sql
IFNULL(FriendlyBonusOut, 0) + IFNULL(FirstSaleBonus, 0) + IFNULL(DealerCommOut, 0)
```

### 4. BrandType（維度，文字）
```sql
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

### 5. Dealer_NotNull（維度，文字）
```sql
CASE
  WHEN Dealer IS NULL OR TRIM(Dealer) = '' THEN '馭盛'
  ELSE UPPER(TRIM(REGEXP_REPLACE(Dealer, '\\s+', '')))
END
```

### 6. Energy Type（維度，文字）
```sql
CASE
  WHEN STARTS_WITH(Model, "EV") THEN "電車"
  WHEN CONTAINS_TEXT(LOWER(Model), "gogoro") THEN "電車"
  WHEN REGEXP_MATCH(Model, "BOBE|VIVAMIX|VIVABASIC|TSV57|SHINE|S2ABS|Pulse|JEGO|EZ1|EZZY|VIVAXLSF|Ur2") THEN "電車"
  ELSE "油車"
END
```

### 7. ModelColor（維度，文字）
```sql
CONCAT(Model, "_", CarColor)
```

### 8. MotorType（維度，文字）
```sql
CASE
  WHEN REGEXP_MATCH(Model, r"^EV0(62|60L|76|70V|76S|76SZV)|Gogoro|Pulse|S2 ABS") THEN "白牌電車"
  WHEN REGEXP_MATCH(Model, r"JEGO|VIVA|EZ1|EZZY|Ur2") THEN "綠牌電車"
  WHEN REGEXP_MATCH(Model, r"BOBE|SHINE|TSV57") THEN "微型電車"
  WHEN REGEXP_MATCH(Model, r"UQ|UC|UG|UT|UT125XZ") THEN "速克達"
  WHEN REGEXP_MATCH(Model, r"DRZ-4SM|GSX|DS|DS250") THEN "擋車"
  ELSE "其他"
END
```

### 9. NumberOfUnitsBonus（指標，數字）
```sql
CASE
  WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 5
    THEN 500 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
  WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 3
    THEN 200 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
  ELSE 0
END
```

### 10. TotalBonus（指標，數字）
```sql
SUM(BasicBonus)
+
CASE
  WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 5
    THEN 500 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
  WHEN COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END) >= 3
    THEN 200 * COUNT(CASE WHEN STARTS_WITH(Model, 'EV') THEN Model END)
  ELSE 0
END
```

### 11. Region（維度，文字）
```sql
REGEXP_EXTRACT(Region_Clean, r"(.{2,5}(區|鄉|鎮|市))")
```

### 12. Region_Clean（維度，文字）
```sql
REGEXP_REPLACE(Address, r"^[0-9][0-9][0-9]", "")
```

### 13. Region_District（維度，文字）
```sql
REGEXP_EXTRACT(Address, r"(台北市|新北市|桃園市|台中市|台南市|高雄市|基隆市|新竹市|嘉義市|宜蘭縣|彰化縣|南投縣|雲林縣|屏東縣|花蓮縣|台東縣|澎湖縣|金門縣|連江縣).{1,6}(區|鄉|鎮|市)")
```

### 14. Sales Source（維度，文字）
```sql
CASE
  WHEN Dealer IS NULL OR Dealer = "" OR Dealer = "中古車" THEN "馭盛"
  WHEN REGEXP_MATCH(Dealer, "yahoo|百利市|momo|PC|Friday|燦坤|小樹購|蝦皮|YAHOO|Yahoo") THEN "網路平台"
  WHEN REGEXP_MATCH(Dealer, "文傑") THEN "店內員工"
  ELSE "車行"
END
```

### 15. SalesType（維度，文字）
```sql
CASE
  WHEN Dealer IS NULL OR Dealer = '' OR REGEXP_MATCH(Dealer, '文傑') THEN '本店'
  WHEN REGEXP_MATCH(LOWER(Dealer), '(pc|momo|yahoo|燦坤|小樹購|百利市|friday|蝦皮)') THEN '網路平台'
  ELSE '車行'
END
```

### 16. sex（維度，文字）
```sql
CASE
  WHEN SUBSTR(ID_No, 2, 1) IN ("1", "8") THEN "男性"
  WHEN SUBSTR(ID_No, 2, 1) IN ("2", "9") THEN "女性"
  ELSE "未填寫或格式錯誤"
END
```

### 17. SortLicenseDate（維度，日期）
```sql
CASE
  WHEN LicenseDate IS NULL THEN DATE(9999, 12, 31)
  ELSE LicenseDate
END
```

---

## 二、非計算欄位（92 筆原始 DB 欄位）

| 欄位名稱 | 類型 | 欄位名稱 | 類型 |
|-----------|------|-----------|------|
| Address | 文字 | AgencyFeeIn | 數字 |
| ApplyDate | 文字 | Bank | 文字 |
| BankAccount | 文字 | BatteryAcct | 文字 |
| BatteryPass | 文字 | BatteryPlan | 文字 |
| BatteryStart | 文字 | Birthday | 日期 |
| BoIE_Invoice | 文字 | BoIE_Status | 文字 |
| CarColor | 文字 | Cash | 數字 |
| City_Status | 文字 | CMVLIComm | 數字 |
| CMVLIIn | 數字 | CMVLIOut | 數字 |
| CompanyGift | 文字 | Control_Account | 文字 |
| Control_Password | 日期和時間 | Cost | 數字 |
| CreditCard | 數字 | CreditCardFeeOut | 數字 |
| CreditComm | 數字 | Dealer | 文字 |
| DealerCommOut | 數字 | DealerReceipt | 文字 |
| Displacement | 文字 | Email | 文字 |
| FeeIn | 數字 | Final_Invoice | 文字 |
| FirstSaleBonus | 數字 | FriendlyBonusIn | 數字 |
| FriendlyBonusOut | 數字 | GiftCard | 文字 |
| GiftShipOut | 數字 | Helmet | 文字 |
| ID_No | 文字 | InstallCo | 文字 |
| InstallFeeOut | 數字 | InstallInfo | 文字 |
| InstallInterestSub | 數字 | Installments | 數字 |
| LicenseDate | 日期 | LicensePlate | 文字 |
| LicenseTaxIn | 數字 | LicenseTaxOut | 數字 |
| LicenseYM | 文字 | MfgDate | 文字 |
| Model | 文字 | MoENV_Status | 文字 |
| Month | 文字 | NetProfit | 數字 |
| Notes | 文字 | OldAddress | 文字 |
| OldEngineNo | 文字 | OldMake | 文字 |
| OldOwner | 文字 | OldOwnerID | 文字 |
| OldPhone | 日期和時間 | OldPlateNo | 文字 |
| OrderStatus | 文字 | OtherIn | 數字 |
| OtherMisc | 文字 | OwnerName | 文字 |
| OwnerName2 | 文字 | Phone | 日期和時間 |
| PlateSelectIn | 數字 | PlateSelectOut | 數字 |
| PlatformGift | 文字 | Premium | 文字 |
| PromoSubsidy | 數字 | ReceiptPrice | 數字 |
| RecycleDate | 文字 | ROC_Birthday | 日期和時間 |
| SalesDate | 日期和時間 | SalesIncentive | 數字 |
| ScrapAgencyIn | 數字 | ScrapCarIn | 數字 |
| ScrapDate | 文字 | ServicePhone | 文字 |
| SubsidyAmt | 數字 | SubsidyPlan | 文字 |
| SysID | 文字 | UsedCarIn | 數字 |
| UsedCarOut | 數字 | VINorEN | 文字 |
| VolumeBonus | 數字 | Warranty | 文字 |
| YamahaBonusIn | 數字 | Record Count | 數字（指標） |

---

## 三、篩選器定義

| 篩選器名稱 | 推測條件 | 使用頁面 |
|-----------|---------|---------|
| 電動車篩選器 | Energy Type = "電車" | P3, P5, P6, P7, P8, P15, P16 |
| 汽油車篩選器 | Energy Type = "油車" | P9, P10, P11, P12, P13 |
| 車行篩選器 | SalesType = "車行" 或 Sales Source = "車行" | P6, P7, P8, P11, P12, P13 |
| 網路平台篩選器 | SalesType = "網路平台" 或 Sales Source = "網路平台" | P5, P10 |
| 基隆公益青年篩選 | 特定經銷商/區域條件（基隆公益青年計畫） | P4, P14, P15, P22 |
| 年齡及車型篩選 | 排除特定年齡或車型 | P16 |
| 排除空白資料 | 排除維度為空的記錄 | 多數圖表 |
| 20-29歲男性 | age BETWEEN 20 AND 29 且 sex = "男性" | P22 |
| 30-39歲男性 | age BETWEEN 30 AND 39 且 sex = "男性" | P22 |
| 40-49歲男性 | age BETWEEN 40 AND 49 且 sex = "男性" | P22 |
| 20-29女性 | age BETWEEN 20 AND 29 且 sex = "女性" | P22 |
| 30-39歲女性 | age BETWEEN 30 AND 39 且 sex = "女性" | P22 |
| 40-49歲女性 | age BETWEEN 40 AND 49 且 sex = "女性" | P22 |
| FUN_性別 | Model 包含 FUN 系列車型 | P19 |
| RUN_性別 | Model 包含 RUN 系列車型 | P17 |
| 70B_性別 | Model 包含 EV070V/70B 系列 | P17 |
| 76B_性別 | Model 包含 EV076 系列 | P17 |
| RUN_顏色 | Model 包含 RUN 系列（用於顏色分析） | P18 |
| 70B_顏色 | Model 包含 70B 系列（用於顏色分析） | P18 |

> **備註**：篩選器定義因 DataStudio 編輯器的 overlay 干擾，無法開啟各篩選器的定義面板。上表「推測條件」欄位為根據篩選器名稱與使用情境推測，實際條件需手動從 DataStudio 編輯介面確認。

---

## 四、頁面與圖表結構（全 22 頁）

### 互動功能說明

所有頁面啟用以下互動：

1. **交叉篩選（Cross-filtering）**：點選圖表元素 → 同頁其他圖表自動篩選
2. **下鑽查詢（Drill-down）**：長條圖支援年→年月→日逐層展開
3. **縮放（Zoom）**：長條圖支援拖曳/滾輪縮放
4. **變更排序（Change Sort）**：檢視模式可動態調整排序
5. **分頁（Pagination）**：表格支援分頁瀏覽
6. **篩選器控制項**：部分頁面頂部有下拉選單，選擇後整頁即時篩選

---

### P1 — 總車輛銷售

**篩選器控制項**：銷售來源 ▼、領牌年月 ▼

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|---------|------|--------|-----|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | Sales Source | Record Count | 排除空白 | LicenseDate ↓ | 交叉篩選, 變更排序, 縮放 |
| 2 | 圓餅圖 | Sales Source | — | Record Count | — | Record Count ↓ | 交叉篩選, 變更排序 |
| 3 | 長條圖（水平堆疊） | LicenseDate 年（下鑽） | MotorType | Record Count | — | LicenseDate ↓ | 交叉篩選, 變更排序, 縮放 |
| 4 | 圓餅圖 | MotorType | — | Record Count | — | Record Count ↓ | 交叉篩選, 變更排序 |
| 5 | 表格（10 列/頁） | 領牌年月, 車行名稱, 車型, VINorEN, 能源, 車色, 車主姓名, 補助方案, 收款 | — | 收款價 | — | SortLicenseDate ↓ | 交叉篩選 |

**日期範圍維度**：LicenseDate

---

### P2 — 銷售機種統計

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 排序 | 互動 |
|---|---------|------|---------|------|-----|------|
| 1 | 長條圖（垂直堆疊） | LicenseDate（日期）下鑽 | MotorType | Record Count | LicenseDate ↓ | 交叉篩選, 變更排序, 縮放 |
| 2 | 表格（20 列/頁） | 領牌年月, 車種型號, 車種類型 | — | 總台數 | LicenseDate ↓, MotorType ↓, Model ↓ | 交叉篩選 |

---

### P3 — 電動車銷售統計

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | Sales Source | Record Count | 電動車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |
| 2 | 長條圖（水平堆疊） | LicenseDate 日期（下鑽） | Model | Record Count | 電動車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |

---

### P4 — 基隆公益青年

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|---------|------|--------|-----|------|
| 1 | 長條圖（水平堆疊） | 年→LicenseDate（下鑽） | BrandType | Record Count | 基隆公益青年篩選, 排除空白 | LicenseDate ↓ | 交叉篩選, 變更排序, 縮放 |
| 2 | 表格（10 列/頁） | 領牌日期, 品牌, 車行名稱, 車型, VINorEN, 車主名稱, 補助方案, 補助申請日, 訖 | — | 獎勵金 | 基隆公益青年篩選, 排除空白 | SortLicenseDate ↓ | 交叉篩選 |

---

### P5 — 電動車 - 網路平台銷售統計

**篩選器控制項**：平台名稱 ▼、領牌年月 ▼

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | 平台名稱(Dealer) | Record Count | 電動車篩選器, 網路平台篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |
| 2 | 表格 | 領牌日期, 車行, 車型, VINorEN, 車色, 車主姓名, 公司禮券/匯款, 平台贈品, 公司贈品, 訖 | — | 收款價 | 電動車篩選器, 網路平台篩選器, 排除空白 | 交叉篩選 |

---

### P6 — 電動車 - 車行銷售統計

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|---------|------|--------|-----|------|
| 1 | 長條圖（水平堆疊） | 車行名稱(Dealer) | LicenseDate（年月） | Record Count | 電動車篩選器, 車行篩選器, 排除空白 | Record Count ↓ | 交叉篩選, 變更排序, 縮放 |
| 2 | 表格 | 領牌日期, 車行, 車型, VINorEN, 車色, 車主姓名, 公司禮券/匯款, 公司贈品, 訖 | — | 收款價 | 電動車篩選器, 車行篩選器, 排除空白 | 交叉篩選 |

---

### P7 — 電動車 - 佣金明細表

| # | 圖表類型 | 維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|------|--------|-----|------|
| 1 | 表格（25 列/頁） | 領牌日期, 車行, 車型, 車色, 車主, 牌照號碼, 訖 | 收款價 | 電動車篩選器, 車行篩選器, 排除空白 | LicenseDate ↓ | 交叉篩選 |

---

### P8 — 電動車 - 台數統計

| # | 圖表類型 | 維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|------|--------|-----|------|
| 1 | 表格（25 列/頁） | 領牌日期, 車行, 車主, 車型, 顏色, 車牌 | 獎勵金 | 電動車篩選器, 車行篩選器, 排除空白 | LicenseDate ↓ | 交叉篩選 |

---

### P9 — 油車銷售統計

**篩選器控制項**：銷售來源 ▼、領牌年月 ▼

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | Sales Source | Record Count | 汽油車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |
| 2 | 長條圖（水平堆疊） | LicenseDate 日期（下鑽） | Model | Record Count | 汽油車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |

> 結構與 P3（電動車銷售統計）對稱

---

### P10 — 油車 - 網路平台銷售統計

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | 平台名稱(Dealer) | Record Count | 網路平台篩選器, 汽油車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |

> 結構與 P5 對稱

---

### P11 — 油車 - 車行銷售統計

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|---------|------|--------|-----|------|
| 1 | 長條圖（水平堆疊） | 車行名稱(Dealer) | LicenseDate（年月） | Record Count | 汽油車篩選器, 車行篩選器, 排除空白 | Record Count ↓ | 交叉篩選, 變更排序, 縮放 |
| 2 | 表格（10 列/頁） | 領牌日期, 車行, 車型, VINorEN, 車色, 車主姓名, 公司禮券/匯款, 公司贈品, 訖 | — | 收款價 | 汽油車篩選器, 車行篩選器, 排除空白 | SortLicenseDate ↓ | 交叉篩選 |

---

### P12 — 油車 - 佣金明細表

| # | 圖表類型 | 維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|------|--------|-----|------|
| 1 | 表格（25 列/頁） | 領牌日期, 車行, 車型, 車色, 車主, 牌照號碼, 訖 | 收款價 | 汽油車篩選器, 車行篩選器, 排除空白 | LicenseDate ↓ | 交叉篩選 |

> 結構與 P7 對稱

---

### P13 — 油車 - 台數統計

| # | 圖表類型 | 維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|------|--------|-----|------|
| 1 | 表格（25 列/頁） | 領牌日期, 車行, 車主, 車型, 顏色, 車牌 | 獎勵金 | 汽油車篩選器, 車行篩選器, 排除空白 | LicenseDate ↓ | 交叉篩選 |

> 結構與 P8 對稱

---

### P14 — 基隆公益青年 地區X銷量

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|---------|------|--------|-----|------|
| 1 | 長條圖（垂直堆疊） | Region | LicenseDate（年月） | Record Count | 基隆公益青年篩選, 排除空白 | Record Count ↓ | 交叉篩選, 變更排序, 縮放 |

---

### P15 — 基隆公益青年 區域X車型

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 長條圖（水平堆疊） | Region | Model | Record Count | 基隆公益青年篩選, 電動車篩選器, 排除空白 | 交叉篩選, 變更排序, 縮放 |

---

### P16 — 性別X年齡

**篩選器控制項**：車型 ▼、領牌年月 ▼

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 篩選器 | 互動 |
|---|---------|------|---------|------|--------|------|
| 1 | 圓餅圖（總性別比） | sex | — | Record Count | 年齡及車型篩選, 排除空白 | 交叉篩選, 變更排序 |
| 2 | 長條圖（垂直堆疊） | AgeGroup | sex | Record Count | 電動車篩選器, 年齡及車型篩選, 排除空白 | 交叉篩選, 變更排序, 縮放 |

---

### P17 — 車型X性別

多個**圓餅圖**按車型分群排列（如「70皮帶-性別」「76皮帶-性別」等）。

| 圖表模式 | 維度 | 指標 | 篩選器（每圖不同） | 互動 |
|---------|------|------|-----------------|------|
| 圓餅圖 ×N | sex | Record Count | 各車型篩選器（70B_性別, 76B_性別, RUN_性別 等）, 排除空白 | 交叉篩選, 變更排序 |

---

### P18 — 車型X顏色

多個**長條圖**按車型分群排列（如「RUN-顏色」「70B-顏色」等）。

| 圖表模式 | 維度 | 細目維度 | 指標 | 篩選器（每圖不同） | 互動 |
|---------|------|---------|------|-----------------|------|
| 長條圖 ×N | CarColor | CarColor | Record Count | 各車型篩選器（RUN_顏色, 70B_顏色 等）, 排除空白 | 交叉篩選, 變更排序, 縮放 |

---

### P19 — 性別X車型顏色

多個**長條圖**按車型分群排列，展示各車型的顏色×性別分布。

| 圖表模式 | 維度 | 細目維度 | 指標 | 篩選器（每圖不同） | 互動 |
|---------|------|---------|------|-----------------|------|
| 長條圖 ×N | CarColor | sex | Record Count | 各車型篩選器（FUN_性別 等）, 排除空白 | 交叉篩選, 變更排序, 縮放 |

---

### P20 — 通路銷售統計

**篩選器控制項**：銷售來源 ▼、領牌年月 ▼

| # | 圖表類型 | 維度 | 細目維度 | 指標 | 排序 | 互動 |
|---|---------|------|---------|------|-----|------|
| 1 | 長條圖（水平堆疊） | 領牌年→領牌年月（下鑽） | Dealer_NotNull | Record Count | LicenseDate ↓ | 交叉篩選, 變更排序, 縮放 |

---

### P21 — 基隆公益青年統計（複本）

| # | 圖表類型 | 維度 | 指標 | 篩選器 | 排序 | 互動 |
|---|---------|------|------|--------|-----|------|
| 1 | 表格（100 列/頁） | 領牌日期, 車行名稱, 車型, 車主名稱, 補助方案, 補助申請日, 車行收款 | 獎勵金 | 排除空白 | BasicBonus ↓ | 交叉篩選 |

---

### P22 — 基隆公益青年 客群X車型分析

多個**圓餅圖**按年齡×性別分群排列。

| 圖表模式 | 維度 | 指標 | 篩選器（每圖不同） | 互動 |
|---------|------|------|-----------------|------|
| 圓餅圖 ×N | ModelColor | Record Count | 基隆公益青年篩選 + 各年齡性別篩選器 | 交叉篩選, 變更排序 |

年齡性別篩選器：20-29歲男性、30-39歲男性、40-49歲男性、20-29女性、30-39歲女性、40-49歲女性

---

## 五、頁面結構對稱性

| 電動車頁面 | 油車頁面 | 差異 |
|-----------|---------|------|
| P3 電動車銷售統計 | P9 油車銷售統計 | 僅篩選器不同 |
| P5 電動車 - 網路平台 | P10 油車 - 網路平台 | 僅篩選器不同 |
| P6 電動車 - 車行 | P11 油車 - 車行 | 僅篩選器不同 |
| P7 電動車 - 佣金明細 | P12 油車 - 佣金明細 | 僅篩選器不同 |
| P8 電動車 - 台數 | P13 油車 - 台數 | 僅篩選器不同 |

---

## 六、欄位別名對照（圖表顯示名稱 ↔ DB 欄位）

| 圖表顯示名稱 | 實際 DB 欄位 / 計算欄位 |
|-------------|----------------------|
| 領牌年月 | LicenseDate（格式化為年月）或 LicenseYM |
| 領牌年 | LicenseDate（格式化為年） |
| 領牌日期 | LicenseDate |
| 車行名稱 / 車行 | Dealer |
| 車型 / 車種型號 | Model |
| 車種類型 | MotorType (fx) |
| 能源 | Energy Type (fx) |
| 車色 / 顏色 | CarColor |
| 車主姓名 / 車主 / 車主名稱 | OwnerName |
| 補助方案 | SubsidyPlan |
| 收款 | DealerReceipt（推測） |
| 收款價 | ReceiptPrice |
| 總台數 | Record Count |
| 牌照號碼 / 車牌 | LicensePlate |
| 獎勵金 | BasicBonus (fx) 或 TotalBonus (fx) |
| 品牌 | BrandType (fx) |
| 補助申請日 | ApplyDate |
| 訖 | 不明（推測為結案狀態欄位） |
| 平台名稱 | Dealer（經篩選後顯示） |
| 公司禮券/匯款 | CompanyGift 或 GiftCard |
| 平台贈品 | PlatformGift |
| 公司贈品 | CompanyGift |
| 車行收款 | DealerReceipt |
