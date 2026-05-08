# 規格（01-spec）— Metabase 車行月銷量與累計趨勢

## 目標

- 在現有 Metabase「P20 通路銷售統計」dashboard 新增車行月銷量與累計銷量分析，不另開新 Odoo 選單。
- 使用者可在同一頁透過下拉式篩選器選取 `領牌年月`、`能源類型` 與 `車行名稱`，查看指定條件下各月份的銷售狀況與累計銷量。

## 版位

- 掛載目標：Metabase dashboard `P20 通路銷售統計`
- Dashboard public UUID：沿用既有 `7afe6e64-0df8-4dc3-a660-7b1d3c66e266`
- 不新增 Odoo `ir.actions.client` 或選單。

## 圖表定義

### P20-1 車行月銷量（長條圖）

- 類型：水平堆疊長條圖（Metabase `row`）
- 維度：`領牌月份（月）`、`車行名稱`
- 指標：`COUNT(*)`
- 固定條件：`state = 'confirmed'`、`license_date IS NOT NULL`、`model IS NOT NULL`、`dealer IS NOT NULL`
- 用途：查看每個月各車行的當月銷量
- 顯示規則：維持適合 dashboard 首屏閱讀的緊湊版位，不再為了展開全部 dealer 而大幅拉高卡片高度；完整 dealer 清單以 `P20-3` 表格為準

### P20-2 車行累計銷量（折線圖）

- 類型：折線圖（Metabase `line`）
- 資料來源：`ds_sales_report`
- 維度：`領牌月份`
- 指標：`累計銷量 = SUM(月銷量) OVER (ORDER BY license_month)`
- 固定條件：`state = 'confirmed'`、`license_date IS NOT NULL`、`model IS NOT NULL`、`dealer IS NOT NULL`、`dealer <> ''`
- 用途：查看目前篩選條件下所選車行集合的總累計銷量走勢；當只選單一車行時，即為該車行累計銷量

### P20-3 車行月銷量明細（表格）

- 類型：表格（Metabase `table`）
- 維度：以矩陣方式顯示，每列三組 `領牌年月 / 車行名稱 + 月銷量`
- 指標：`COUNT(*)`
- 固定條件：`state = 'confirmed'`、`license_date IS NOT NULL`、`model IS NOT NULL`、`dealer IS NOT NULL`
- 用途：補足 P20-1 在窄版畫面下可能無法一次展開全部車行名稱的限制，提供完整 dealer 明細清單
- 顯示規則：需以矩陣方式由左到右填入資料，同一列顯示三組資料；超出者自動落到下一列，並於銷量欄使用非藍色 heatmap 區分高低。
- 排序規則：需先依 `領牌年月` 遞減分塊，再於同月份內依月銷量遞減排列，不可在同一列中跨月份跳接。
- 欄頭規則：畫面欄頭只顯示通用名稱 `年月 / 車行` 與 `月銷量`，不得暴露內部用的 `A/B/C` 後綴。

## 篩選器

### 領牌年月

- 類型：Metabase dashboard 下拉式篩選器（`string/=`）
- 對應欄位：`ds_sales_report.license_ym`
- 套用對象：P20-1、P20-2、P20-3
- 預設值：腳本套用時計算的最近半年（含當前月份）
- 行為：使用者手動指定月份後，以手動選值覆蓋預設值

### 車行名稱

- 類型：Metabase dashboard 下拉式篩選器（`string/=`）
- 對應欄位：`ds_sales_report.dealer`
- 套用對象：P20-1、P20-2、P20-3

### 銷售來源

- 保留既有 dashboard 篩選器 `銷售來源`
- 對應欄位：`ds_sales_report.sales_source`
- 套用對象：P20-1、P20-2、P20-3
- 預設值：`車行`

### 能源類型

- 類型：Metabase dashboard 下拉式篩選器（`string/=`）
- 對應欄位：`ds_sales_report.energy_type`
- 套用對象：P20-1、P20-2、P20-3
- 值域：`電車`、`油車`
- 行為：使用者可依能源類型切換，只查看電車或油車資料

## 實作方式

- 以 `scripts/` 下的可重複執行腳本透過 Metabase REST API 更新 dashboard 與 card。
- 腳本須支援 dry-run 與 `--apply` 模式。
- 腳本需具備冪等性：重複執行不得新增重複 card 或重複 dashcard。
- 腳本需同步寫入 dashboard 預設篩選值，讓 public dashboard 首次載入即可套用預設條件。