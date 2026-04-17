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

_P2–P22 待翻頁後填入。_
