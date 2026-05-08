# DataStudio 逐頁圖表稽核紀錄

本文件逐頁記錄 SUZUKI 銷售統計 DataStudio 報表中每張圖表的完整屬性設定。

來源：實際在 DataStudio 編輯模式，點選每張圖表、讀取「屬性」面板得到。

欄位含義：
- **類型**：圖表類型（長條圖、圓餅圖、表格、分數卡、時間序列等）
- **維度 / 細目維度 / 指標**：主維度、breakdown、指標與聚合
- **篩選器**：套用的全域/區域篩選器（含「排除空白資料」等）
- **排序**：排序欄位與方向（主/次）
- **日期範圍**：預設日期範圍設定
- **互動**：啟用的圖表互動（交叉篩選、變更排序、縮放）

元件 ID 格式 `cd-XXX` 為 DataStudio 報表內部 componentId，可用於對照來源 JSON。

---

## P1 總車輛銷售（`p_oe0r8mk2wd`）

### 群組層（Group）
- **資料來源**：預設 (PostgreSQL - grafana_US_Sales)
- **Apply filter controls to page**：啟用
- **群組篩選器**：無（空白）
- **日期範圍維度**：未設定

### #1 下拉式選單 `cd-6q3zxtk2wd` — 銷售來源
- 圖表類型：下拉式選單（filter control）
- 控制欄位：Sales Source
- 指標：Record Count
- 日期範圍維度：LicenseDate；預設：自動（All available dates）
- 排序：Sales Source 遞減；顯示前 N 名：5000

### #2 下拉式選單 `cd-qcypsrk2wd` — 領牌年月（⚠ 欄位綁 Sales Source）
- 圖表類型：下拉式選單（filter control）
- 控制欄位：Sales Source  **← 顯示標籤為「領牌年月」但欄位實際是 Sales Source，疑似設定錯誤**
- 指標：Record Count
- 日期範圍維度：LicenseDate；預設：自動
- 排序：Sales Source 遞減；顯示前 N 名：5000

> ⚠ 註：頁面上顯示「領牌年月」按鈕，但屬性面板的「控制欄位」是 Sales Source。建議在 Metabase 重現時改為日期下拉。

### #3 長條圖 `cd-me0r8mk2wd` — 領牌車輛（堆疊長條圖 by Sales Source）
- **資料來源**：PostgreSQL - grafana_US_Sales
- **維度 (Y軸)**：領牌年、領牌年月（下鑽；預設層級：領牌年月）
- **細目維度**：Sales Source
- **指標 (X軸)**：Record Count
- **篩選器**：排除空白資料
- **日期範圍維度**：LicenseDate；預設：自動
- **排序**：LicenseDate (日期) 遞減；次要 Sales Source 遞減
- **圖表互動**：交叉篩選、變更排序、縮放

### #4 長條圖 `cd-t3ieiq8bxd` — 銷售機種統計 by MotorType
- **維度 (Y軸)**：年、LicenseDate (日期)（下鑽；預設層級：LicenseDate (日期)）
- **細目維度**：MotorType
- **指標 (X軸)**：Record Count
- **篩選器**：排除空白資料
- **日期範圍維度**：（未設定）
- **排序**：LicenseDate (日期) 遞減；次要 Record Count 遞減
- **圖表互動**：交叉篩選、變更排序、縮放

### #5 圓餅圖 `cd-z85jvt8bxd` — 銷售來源分布
- **維度**：Sales Source
- **指標**：Record Count
- **篩選器**：排除空白資料
- **日期範圍維度**：LicenseDate；預設：自動
- **排序**：Record Count 遞減
- **圖表互動**：交叉篩選、變更排序

### #6 圓餅圖 `cd-9z5whv8bxd` — MotorType 分布
- **維度**：MotorType
- **指標**：Record Count
- **篩選器**：排除空白資料
- **日期範圍維度**：LicenseDate；預設：自動
- **排序**：Record Count 遞減
- **圖表互動**：交叉篩選、變更排序

### #7 表格 `cd-p0mc1zp2wd` — 明細表
- **維度**：領牌年月、車行名稱、車型、VINorEN、能源、車色、車主姓名、補助方案、收款
- **指標**：收款價
- **篩選器**：排除空白資料
- **日期範圍維度**：LicenseDate；預設：自動
- **列數分頁**：每頁 10 列
- **排序**：SortLicenseDate 遞減（排序欄位不顯示於表格）
- **圖表互動**：交叉篩選、在新分頁中開啟連結

---

## P2 銷售機種統計（`p_67eq9sz9wd`）

**Metabase 補強說明**：除保留原始 DataStudio 對應的「銷售機種月趨勢 by MotorType」與明細表外，Metabase 版本額外新增一張「銷售車型月趨勢 by Model」長條圖，供使用者直接按車型查看分布；原兩張圖的查詢與配置不得被覆寫。

### #1 下拉式選單 `cd-eszuu0z9wd` — 領牌年月
- 控制欄位：領牌年月
- 指標：Record Count（顯示為密集數字）
- 日期範圍維度：LicenseDate；預設：自動
- 排序：LicenseDate (日期) 遞減；顯示前 N 名：5000

### #2 長條圖 `cd-47eq9sz9wd` — 銷售機種月趨勢 by MotorType
- **維度 (X軸)**：LicenseDate (日期)
- **細目維度**：MotorType
- **指標 (Y軸)**：Record Count
- **篩選器**：無
- **排序**：LicenseDate 遞減；次要 Record Count 遞減
- **圖表互動**：交叉篩選、變更排序、縮放

### #3 表格 `cd-iwkbzuz9wd` — 車種月報表
- **維度**：領牌年月、車種型號（Model）、車種類型（MotorType）
- **指標**：總台數（= Record Count 或計數欄位，顯示名稱為「總台數」）
- **篩選器**：無
- **日期範圍維度**：LicenseDate；預設：自動
- **列數分頁**：每頁 20 列
- **排序**：#1 LicenseDate 遞減；#2 MotorType 遞減；#3 Model 遞減
- **圖表互動**：交叉篩選、在新分頁中開啟連結

### #4 Metabase 補強圖表 — 銷售車型月趨勢 by Model
- **維度 (X軸)**：LicenseDate (日期)
- **細目維度**：Model
- **指標 (Y軸)**：Record Count
- **篩選器**：維持與 #2 相同的已成立資料條件，不額外加其他限制
- **Dashboard 篩選器**：必須沿用 P2 同頁既有的「領牌年月」與「銷售來源」filter mappings，不得成為獨立不連動圖表
- **要求**：此圖為新增補強圖，不得改動 #2 與 #3 的查詢、名稱、排序與既有版位；應以新增獨立 card 方式附加於 P2 dashboard

---

## P3 電動車銷售統計（`p_v7fndtm3wd`）

**共同套用篩選器**：電動車篩選器 + 排除空白資料（除下拉選單外）

### #1 下拉式選單 `cd-t7fndtm3wd` — 銷售來源
- 控制欄位：Sales Source；指標：Record Count；排序：Sales Source 遞減；顯示前 5000

### #2 下拉式選單 `cd-s7fndtm3wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count；排序：LicenseDate 遞減；顯示前 5000

### #3 長條圖 `cd-r7fndtm3wd` — 電動車領牌趨勢 by Sales Source
- 維度 (Y)：領牌年、領牌年月（下鑽；預設：領牌年月）
- 細目維度：Sales Source
- 指標 (X)：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 日期範圍：LicenseDate；自動
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #4 表格 `cd-u7fndtm3wd` — 電動車明細
- 維度：領牌日期、車行、類型、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖
- 指標：收款價
- 篩選器：電動車篩選器、排除空白資料
- 日期範圍：LicenseDate；自動
- 列數分頁：每頁 10
- 排序：#1 SortLicenseDate 遞減（不顯示）；#2 Sales Source 遞減
- 互動：交叉篩選、在新分頁中開啟連結

### #5 長條圖 `cd-ba5neyo9yd` — 電動車領牌月趨勢 by Model
- 維度 (Y)：LicenseDate (日期)
- 細目維度：Model
- 指標 (X)：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #6 圓餅圖 `cd-cm9ea9p9yd` — 電動車 Model 分布
- 維度：Model；指標：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 排序：Record Count 遞減
- 互動：交叉篩選、變更排序

---

## P4 基隆公益青年（`p_wrl9qpo2wd`）

**共同套用篩選器**：基隆公益青年篩選 + 排除空白資料

### #1 下拉式選單 `cd-url9qpo2wd` — 品牌類別
- 控制欄位：品牌類別（BrandType）；指標：Record Count
- 篩選器：基隆公益青年篩選
- 排序：Record Count 遞減；顯示前 5000

### #2 下拉式選單 `cd-vrl9qpo2wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count
- 排序：LicenseDate 遞減；顯示前 5000

### #3 長條圖 `cd-trl9qpo2wd` — 基隆公益青年趨勢 by BrandType
- 維度 (Y)：年、LicenseDate (日期)（下鑽；預設：LicenseDate）
- 細目維度：BrandType
- 指標：Record Count
- 篩選器：基隆公益青年篩選、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #4 表格 `cd-6o8uouo2wd` — 基隆公益青年明細
- 維度：領牌日期、品牌、車行名稱、車型、VINorEN、車主名稱、補助方案、補助申請日、訖
- 指標：獎勵金
- 篩選器：基隆公益青年篩選、排除空白資料
- 日期範圍：LicenseDate；自動
- 列數分頁：每頁 10
- 排序：#1 SortLicenseDate 遞減（不顯示）
- 互動：交叉篩選、在新分頁中開啟連結

### #5 表格 `cd-958df1jbyd` — 基隆公益青年明細（複本，內容完全相同）
- 設定與 #4 完全一致。疑似重複/備用用途。

---

## P3 電動車銷售統計（`p_v7fndtm3wd`）

**共同套用篩選器**：電動車篩選器 + 排除空白資料（除下拉選單外）

### #1 下拉式選單 `cd-t7fndtm3wd` — 銷售來源
- 控制欄位：Sales Source；指標：Record Count；排序：Sales Source 遞減；顯示前 5000

### #2 下拉式選單 `cd-s7fndtm3wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count；排序：LicenseDate 遞減；顯示前 5000

### #3 長條圖 `cd-r7fndtm3wd` — 電動車領牌趨勢 by Sales Source
- 維度 (Y)：領牌年、領牌年月（下鑽；預設：領牌年月）
- 細目維度：Sales Source
- 指標 (X)：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 日期範圍：LicenseDate；自動
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #4 表格 `cd-u7fndtm3wd` — 電動車明細
- 維度：領牌日期、車行、類型、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖
- 指標：收款價
- 篩選器：電動車篩選器、排除空白資料
- 日期範圍：LicenseDate；自動
- 列數分頁：每頁 10
- 排序：#1 SortLicenseDate 遞減（不顯示）；#2 Sales Source 遞減
- 互動：交叉篩選、在新分頁中開啟連結

### #5 長條圖 `cd-ba5neyo9yd` — 電動車領牌月趨勢 by Model
- 維度 (Y)：LicenseDate (日期)
- 細目維度：Model
- 指標 (X)：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #6 圓餅圖 `cd-cm9ea9p9yd` — 電動車 Model 分布
- 維度：Model；指標：Record Count
- 篩選器：電動車篩選器、排除空白資料
- 排序：Record Count 遞減
- 互動：交叉篩選、變更排序

---

## P5 電動車 - 網路平台銷售統計（`p_oyi9bhn3wd`）

**共同篩選器**：電動車篩選器 + 網路平台篩選器 + 排除空白資料

### #1 下拉式選單 `cd-u6h9bhn3wd` — 平台名稱
- 控制欄位：平台名稱（Dealer_NotNull）
- 篩選器：網路平台篩選器、電動車篩選器
- 排序：Dealer_NotNull 遞減；顯示前 5000

### #2 下拉式選單 `cd-t6h9bhn3wd` — 領牌年月
- 控制欄位：領牌年月；排序：LicenseDate 遞減；顯示前 5000

### #3 長條圖 `cd-s6h9bhn3wd` — 電動車網路平台月趨勢 by 平台名稱
- 維度 (Y)：領牌年、領牌年月（下鑽）
- 細目維度：平台名稱
- 指標：Record Count
- 篩選器：電動車篩選器、網路平台篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減
- 互動：交叉篩選、變更排序、縮放

### #4 表格 `cd-nyi9bhn3wd` — 電動車網路平台明細
- 維度：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖
- 指標：收款價
- 篩選器：電動車篩選器、網路平台篩選器、排除空白資料
- 列數分頁：每頁 10
- 排序：#1 SortLicenseDate 遞減（不顯示）

---

## P6 電動車 - 車行銷售統計（`p_x9z82fo3wd`）

**共同篩選器**：電動車篩選器 + 車行篩選器 + 排除空白資料

### #1 下拉式選單 `cd-v9z82fo3wd` — 車行名稱
- 控制欄位：車行名稱（Dealer_NotNull）
- 篩選器：電動車篩選器、車行篩選器
- 排序：Dealer_NotNull 遞減；顯示前 5000

### #2 下拉式選單 `cd-2hz82fo3wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減；顯示前 5000

### #3 長條圖 `cd-1hz82fo3wd` — 車行電動車銷售 by 領牌年月
- 維度 (Y)：車行名稱
- 細目維度：LicenseDate (年月)
- 指標：Record Count
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 排序：Record Count 遞減；次要 LicenseDate(年月) 遞減

### #4 表格 `cd-w9z82fo3wd` — 車行電動車明細
- 維度：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券/匯款、公司贈品、訖、備註
- 指標：收款價
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 列數分頁：每頁 10；排序 #1 SortLicenseDate 遞減（不顯示）

---

## P7 電動車 - 佣金明細（`p_tkr5sfw3wd`）

**共同篩選器**：電動車篩選器 + 車行篩選器 + 排除空白資料（表格）

### #1 文字說明 `cd-uhmjrex3wd` — 頁面標題/說明文字
### #2 下拉式選單 `cd-rkr5sfw3wd` — 車行名稱
- 控制欄位：車行名稱；指標：BasicBonus（獎勵金）
- 篩選器：車行篩選器、電動車篩選器
- 排序：BasicBonus 遞減；顯示前 5000

### #3 下拉式選單 `cd-pkr5sfw3wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count
- 排序：LicenseDate 遞減；顯示前 5000

### #4 群組 `cd-xf0maers2d`
- 套用「預設 (PostgreSQL - grafana_US_Sales)」
- Apply filter controls to page：啟用

### #5 表格 `cd-qkr5sfw3wd` — 佣金彙總
- 維度：領牌年月、車行
- 指標：台數獎金、台數、總獎金
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 列數分頁：每頁 25；排序 LicenseDate 遞減

### #6 表格 `cd-skr5sfw3wd` — 佣金明細
- 維度：領牌日期、車行、車型、車色、車主、牌照號碼、訖
- 指標：收款價
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 列數分頁：每頁 25；排序 LicenseDate 遞減

---

## P8 電動車 - 台數統計（`p_9sqwajw3wd`）

**共同篩選器**：電動車篩選器 + 車行篩選器 + 排除空白資料

### #1 文字說明 `cd-qihr1fx3wd`
### #2 下拉式選單 `cd-7sqwajw3wd` — 車行名稱
- 控制欄位：車行名稱；指標：BasicBonus；篩選器：車行篩選器、電動車篩選器

### #3 下拉式選單 `cd-5sqwajw3wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count

### #4 表格 `cd-6sqwajw3wd` — 車行台數彙總
- 維度：車行；指標：台數（Record Count）
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 Record Count 遞減

### #5 表格 `cd-l84zmpw3wd` — 電動車明細
- 維度：領牌日期、車行、車主、車型、顏色、車牌
- 指標：獎勵金
- 篩選器：電動車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 LicenseDate 遞減

---

## P9 汽油車銷售統計（`p_vi50zol3wd`）

**共同篩選器**：汽油車篩選器 + 排除空白資料

### #1 下拉式選單 `cd-ti50zol3wd` — 銷售來源
- 控制欄位：銷售來源（Sales Source）；指標：Record Count
- 排序 Sales Source 遞減；顯示前 5000

### #2 下拉式選單 `cd-si50zol3wd` — 領牌年月
- 控制欄位：領牌年月；指標：Record Count；排序 LicenseDate 遞減；顯示前 5000

### #3 群組 `cd-bqz0zers2d`
- 預設 (PostgreSQL - grafana_US_Sales)；Apply filter controls to page 啟用

### #4 長條圖 `cd-ri50zol3wd` — 汽油車領牌月趨勢 by Sales Source
- 維度 (Y)：領牌年、領牌年月（下鑽）
- 細目維度：Sales Source
- 指標：Record Count
- 篩選器：汽油車篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減

### #5 表格 `cd-ui50zol3wd` — 汽油車明細
- 維度：領牌日期、車行、類型、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖
- 指標：收款價
- 篩選器：汽油車篩選器、排除空白資料
- 每頁 10；排序 #1 SortLicenseDate 遞減（不顯示）、#2 Sales Source 遞減

### #6 長條圖 `cd-511eacq9yd` — 汽油車月趨勢 by Model
- 維度 (Y)：LicenseDate (日期)；細目維度：Model
- 指標：Record Count
- 篩選器：汽油車篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減

### #7 圓餅圖 `cd-o720nfq9yd` — 汽油車 Model 分布
- 維度：Model；指標：Record Count
- 篩選器：汽油車篩選器、排除空白資料

---

## P10 汽油車 - 網路平台銷售統計（`p_fatrpvn3wd`）

**共同篩選器**：汽油車篩選器 + 網路平台篩選器 + 排除空白資料

### #1 下拉式選單 `cd-datrpvn3wd` — 平台名稱
- 控制欄位：平台名稱；篩選器：網路平台篩選器、汽油車篩選器；排序 Dealer_NotNull 遞減

### #2 下拉式選單 `cd-catrpvn3wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #3 群組 `cd-847e2ers2d`
- 預設 (PostgreSQL)；Apply filter controls to page 啟用

### #4 長條圖 `cd-batrpvn3wd` — 汽油車網路平台月趨勢 by 平台名稱
- 維度 (Y)：領牌年、領牌年月（下鑽）；細目：平台名稱；指標：Record Count
- 篩選器：網路平台篩選器、汽油車篩選器、排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減

### #5 表格 `cd-eatrpvn3wd` — 汽油車網路平台明細
- 維度：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券/匯款、平台贈品、公司贈品、訖
- 指標：收款價
- 篩選器：網路平台篩選器、汽油車篩選器、排除空白資料
- 每頁 10；排序 #1 SortLicenseDate 遞減

---

## P11 汽油車 - 車行銷售統計（`p_qr8kpyn3wd`）

**共同篩選器**：汽油車篩選器 + 車行篩選器 + 排除空白資料

### #1 下拉式選單 `cd-or8kpyn3wd` — 車行名稱
- 控制欄位：車行名稱；篩選器：汽油車篩選器、車行篩選器；排序 Dealer_NotNull 遞減

### #2 下拉式選單 `cd-nr8kpyn3wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #3 群組 `cd-y6kt4ers2d`
- 預設 (PostgreSQL)；Apply filter controls to page 啟用

### #4 長條圖 `cd-mr8kpyn3wd` — 車行汽油車銷售 by 領牌年月
- 維度 (Y)：車行名稱；細目：LicenseDate (年月)；指標：Record Count
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 排序 Record Count 遞減；次要 LicenseDate(年月) 遞減

### #5 表格 `cd-pr8kpyn3wd` — 汽油車明細（車行）
- 維度：領牌日期、車行、車型、VINorEN、車色、車主姓名、公司禮券/匯款、公司贈品、訖
- 指標：收款價
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 每頁 10；排序 #1 SortLicenseDate 遞減

---

## P12 汽油車 - 佣金明細（`p_btvz55m2wd`）

**共同篩選器**：汽油車篩選器 + 車行篩選器 + 排除空白資料

### #1 文字說明 `cd-ffqf7fx3wd`
### #2 下拉式選單 `cd-2wyqubo2wd` — 車行名稱
- 控制欄位：車行名稱；指標：BasicBonus；篩選器：車行篩選器、汽油車篩選器；排序 BasicBonus 遞減

### #3 下拉式選單 `cd-ji4bgan2wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #4 群組 `cd-0pd96ers2d`
- Apply filter controls to page 啟用

### #5 表格 `cd-ii64wqn2wd` — 汽油車佣金彙總
- 維度：領牌年月、車行；指標：台數獎金、台數、總獎金
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 LicenseDate 遞減

### #6 表格 `cd-58zb0ko3wd` — 汽油車佣金明細
- 維度：領牌日期、車行、車型、車色、車主、牌照號碼、訖
- 指標：收款價
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 LicenseDate 遞減

---

## P13 汽油車 - 台數統計（`p_lrht80w3wd`）

**共同篩選器**：汽油車篩選器 + 車行篩選器 + 排除空白資料

### #1 文字說明 `cd-o24wagx3wd`
### #2 下拉式選單 `cd-jrht80w3wd` — 車行名稱
- 控制欄位：車行名稱；指標：BasicBonus；篩選器：車行篩選器、汽油車篩選器；排序 BasicBonus 遞減

### #3 下拉式選單 `cd-hrht80w3wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #4 群組 `cd-gf4m9ers2d`
### #5 表格 `cd-irht80w3wd` — 車行台數彙總
- 維度：車行；指標：台數（Record Count）
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 Record Count 遞減

### #6 表格 `cd-krht80w3wd` — 汽油車明細
- 維度：領牌日期、車行、車主、車型、顏色、車牌
- 指標：獎勵金
- 篩選器：汽油車篩選器、車行篩選器、排除空白資料
- 每頁 25；排序 LicenseDate 遞減

---

## P14 基隆公益青年 - 地區分析（`p_icif4px7wd`）

**共同篩選器**：基隆公益青年篩選（長條圖另加排除空白資料）

### #1 下拉式選單 `cd-xfrbgrx7wd` — 領牌日期
- 控制欄位：領牌日期；指標：Record Count；排序 LicenseDate 遞減

### #2 群組 `cd-g2w1bfrs2d`
### #3 長條圖 `cd-lf9pmyx7wd` — Region × 領牌月趨勢
- 維度 (X)：Region；細目：LicenseDate (年月)
- 指標：Record Count
- 篩選器：基隆公益青年篩選、排除空白資料
- 排序 Record Count 遞減；次要 LicenseDate(年月) 遞減

### #4 表格 `cd-9wr8hd09wd` — 基隆公益青年車型明細
- 維度：領牌年月、車主、車型、車色
- 指標：台數（Record Count）
- 篩選器：基隆公益青年篩選
- 每頁 20；排序 #1 LicenseDate 遞減、#2 Model 遞減

---

## P15 基隆公益青年 - 區域×車型（`p_dr7mnpw7wd`）

**共同篩選器**：基隆公益青年篩選 + 電動車篩選器（+ 排除空白資料於圖表）

### #1 下拉式選單 `cd-cr7mnpw7wd` — 領牌年月
- 控制欄位：領牌年月；篩選器：基隆公益青年篩選、電動車篩選器；排序 LicenseDate 遞減

### #2 長條圖 `cd-ar7mnpw7wd` — Region × Model
- 維度 (Y)：Region；細目：Model；指標：Record Count
- 篩選器：基隆公益青年篩選、電動車篩選器、排除空白資料
- 排序 Record Count 遞減；次要 Record Count 遞減

### #3 表格 `cd-br7mnpw7wd` — 區域×車型(色) 明細
- 維度：領牌年月、區域、車型(色)
- 指標：台數
- 篩選器：電動車篩選器、基隆公益青年篩選、排除空白資料
- 每頁 100；排序 #1 LicenseDate 遞減、#2 ModelColor 遞減

---

## P16 車型×性別（`p_rv185au7wd`）

頁面標題：`SUZUKI銷售統計 › 車型X性別`

### #1 下拉式選單 `cd-81m1ksu7wd` — 領牌年月
- 控制欄位：領牌年月；無其他篩選器；排序 LicenseDate 遞減

### #2 圓餅圖 `cd-qnot2pw7wd` — FUN 性別
- 維度：sex；指標：Record Count
- 篩選器：FUN_性別、排除空白資料

### #3 圓餅圖 `cd-sphb7rw7wd` — RUN 性別
- 維度：sex；指標：Record Count
- 篩選器：RUN_性別、排除空白資料

### #4 群組 `cd-mf609frs2d`
### #5 圓餅圖 `cd-d5uzsyw7wd` — 70B 性別
- 維度：sex；指標：Record Count
- 篩選器：70B_性別、排除空白資料

### #6 圓餅圖 `cd-4mvazww7wd` — 76B 性別
- 維度：sex；指標：Record Count
- 篩選器：76B_性別、排除空白資料

---

## P17 車型×顏色（`p_ppopd2w7wd`）

頁面標題：`SUZUKI銷售統計 › 車型X顏色`

### #1 下拉式選單 `cd-npopd2w7wd` — 領牌年月
- 控制欄位：領牌年月；篩選器：電動車篩選器；排序 LicenseDate 遞減

### #2 長條圖 `cd-opopd2w7wd` — FUN 顏色
- 維度 (X)：CarColor；細目：CarColor；指標：Record Count
- 篩選器：FUN_顏色、排除空白資料

### #3 長條圖 `cd-xf0tnfx7wd` — RUN 顏色
- 篩選器：RUN_顏色、排除空白資料；其餘同 #2

### #4 長條圖 `cd-j6iejhx7wd` — 70B 顏色
- 篩選器：70B_顏色、排除空白資料

### #5 長條圖 `cd-rjotfv09wd` — 76B 顏色
- 篩選器：76B_顏色、排除空白資料

### #6 群組 `cd-3gw8cgrs2d`

---

## P18 性別×車型顏色（`p_auqkqjx7wd`）

頁面標題：`SUZUKI銷售統計 › 性別X車型顏色`

### #1 下拉式選單 `cd-e2pkqjx7wd` — 領牌年月
- 控制欄位：領牌年月；篩選器：電動車篩選器

### #2 長條圖 `cd-7tqkqjx7wd` — FUN 顏色×性別
- 維度 (X)：CarColor；細目：sex；指標：Record Count
- 篩選器：FUN_性別、排除空白資料

### #3 長條圖 `cd-8tqkqjx7wd` — RUN 顏色×性別
- 篩選器：RUN_性別、排除空白資料

### #4 長條圖 `cd-9tqkqjx7wd` — 70B 顏色×性別
- 篩選器：70B_性別、排除空白資料；次要排序 sex 遞減

### #5 長條圖 `cd-otig0y09wd` — 76B 顏色×性別
- 篩選器：76B_性別、排除空白資料；次要排序 sex 遞減

### #6 表格 `cd-o652r68bxd` — 車色×車主×性別明細
- 維度：CarColor、OwnerName、sex、ID_No
- 指標：Record Count
- 篩選器：排除空白資料
- 每頁 100；排序 Record Count 遞減

---

## P19 通路銷售統計（`p_ycxmmgm2wd`）

頁面標題：`SUZUKI銷售統計 › 通路銷售統計`

### #1 下拉式選單 `cd-05irc3m2wd` — 能源類別
- 控制欄位：能源類別；排序 Record Count 遞減

### #2 下拉式選單 `cd-dxwwosm2wd` — 通路類型
- 控制欄位：通路類型；排序 Record Count 遞減

### #3 下拉式選單 `cd-zpq1otm2wd` — 車行名稱
- 控制欄位：車行名稱；排序 Record Count 遞減

### #4 下拉式選單 `cd-n8oy70m2wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #5 長條圖 `cd-wcxmmgm2wd` — 通路月趨勢 by 車行
- 維度 (Y)：領牌年、領牌年月（下鑽）；細目：Dealer_NotNull
- 指標：Record Count
- 篩選器：排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減

---

## P20 基隆公益青年統計（複本）（`p_lf37xfq2wd`）

頁面標題：`SUZUKI銷售統計 › 「基隆公益青年統計」的複本`

### #1 下拉式選單 `cd-if37xfq2wd` — 品牌類別
- 控制欄位：品牌類別；篩選器：基隆公益青年篩選

### #2 下拉式選單 `cd-jf37xfq2wd` — 領牌年月
- 控制欄位：領牌年月；排序 LicenseDate 遞減

### #3 長條圖 `cd-hf37xfq2wd` — 月趨勢 by Sales Source
- 維度 (Y)：年、LicenseDate (日期)（下鑽）；細目：Sales Source
- 指標：Record Count
- 篩選器：排除空白資料
- 排序：LicenseDate 遞減；次要 Record Count 遞減

### #4 表格 `cd-kf37xfq2wd` — 明細
- 維度：領牌日期、車行名稱、車型、車主名稱、補助方案、補助申請日、車行收款
- 指標：獎勵金
- 篩選器：排除空白資料
- 每頁 100；排序 #1 BasicBonus 遞減

**⚠ 備註**：相較於 P4（基隆公益青年），此頁未套用 `基隆公益青年篩選` 至長條圖與表格。疑似為早期複本，已失去分群意義，建議停用或補上篩選器。

---

## P21 基隆公益青年 - 客群×車型分析（`p_qhbl0zq7wd`）

頁面標題：`SUZUKI銷售統計 › 基隆公益青年 客群X車型分析`

**共同篩選器**：基隆公益青年篩選 + 各年齡性別群組 + 排除空白資料

### #1 下拉式選單 `cd-k0ls0ss7wd` — 領牌年月
- 控制欄位：領牌年月；篩選器：基隆公益青年篩選、電動車篩選器

### #2 圓餅圖 `cd-yuaygsr7wd` — 20-29 歲男性 × ModelColor
- 維度：ModelColor；指標：Record Count；篩選器：基隆公益青年篩選、20_29歲男性、排除空白資料

### #3 圓餅圖 `cd-55pxd2r7wd` — 30-39 歲男性 × ModelColor
- 篩選器：基隆公益青年篩選、30-39歲男性、排除空白資料

### #4 群組 `cd-92bcogrs2d`

### #5 圓餅圖 `cd-suzy4is7wd` — 40-49 歲男性 × ModelColor
- 篩選器：基隆公益青年篩選、40-49歲男性、排除空白資料

### #6 圓餅圖 `cd-gsj4cms7wd` — 20-29 女性 × ModelColor
- 篩選器：基隆公益青年篩選、20-29女性、排除空白資料

### #7 圓餅圖 `cd-5snnups7wd` — 30-39 歲女性 × ModelColor
- 篩選器：基隆公益青年篩選、30-39歲女性、排除空白資料

### #8 圓餅圖 `cd-qlbl3qs7wd` — 40-49 歲女性 × ModelColor
- 篩選器：基隆公益青年篩選、40-49歲女性、排除空白資料

所有圓餅圖排序皆以 ModelColor 遞減。

---

## 備註：報表實際頁數 = 21（非原 spec 所記 22）

透過 下一頁 按鈕逐頁翻閱確認，最後一頁為 P21（基隆公益青年 客群X車型分析），再按 下一頁 URL 不變。
原 `03-audit-findings.md` 第 3 節列出 22 頁名稱，其中包含「通路銷售統計」與「基隆公益青年 客群X車型分析」實際總計為 21 頁（不計「頁 1」未使用插頁）；請於 spec 對齊修正。
