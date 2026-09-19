## Changelog

<!-- ═══════════════════════════════════════════════════
     目前版本速查（每次 upgrade 後自動以 git commit 維護）
     ═══════════════════════════════════════════════════ -->

## 目前模組版本（2026-04-30）

| 模組 | 版本 | 說明 |
|---|---|---|
| `dms_core` | `16.0.1.2.0` | 車行/品牌/車行類型；系統資訊頁面更新 |
| `dms_customer` | `16.0.1.1.0` | 客戶主檔 |
| `dms_sale` | `16.0.2.1.0` | 銷售訂單；OrderProcessor 同步、Excel 匯入、舊車/電車頁籤、結案流程 |
| `dms_product` | `16.0.2.3.0` | 產品頁面 wizard、價格表優化、產品及零件管理選單合併 |
| `dms_parts` | `16.0.2.1.0` | EPC 零件目錄、PDF 自動建立分區與零件清單 |
| `dms_commission` | `16.0.1.1.0` | 車行傭金合約（Plan A）、台數現金/實物獎勵、結案流程 |
| `dms_visit` | `16.0.1.1.0` | 拜訪紀錄 |
| `dms_finance` | `16.0.1.1.0` | 財務結算 |
| `dms_report` | `16.0.1.0.0` | 銷售 BI 報表 |
| `dms_report_rule` | `16.0.1.0.0` | 報表動態規則 |
| `dms_report_virtual` | `16.0.1.1.0` | 報表虛擬欄位；金額欄位改整數位 |
| `dms_report_ds` | `16.0.1.2.0` | Metabase 嵌入、motor_type/sales_*/brand_type 規則動態化、未命中診斷 wizard |
| `user_management` | `16.0.1.1.0` | 隱藏討論/財務結算/庫存等根選單與原始數據查詢 |

---

## 2026-04-30

### dms_commission（16.0.1.0.0 → 16.0.1.1.0）
- feat: 合併 `dms_parts` 至產品及零件管理選單
- feat: 新增車行傭金合約（Plan A），以升級版車行覆蓋規則取代舊合約
- feat: 台數現金獎勵規則 + 台數實物獎勵規則（volume.gift），支援品牌維度與特定/通用優先邏輯
- feat: 訂單 state 加入 `closed`（結案）與撤銷結案工作流；複製訂單回到草稿
- feat: 激勵觸發規則列表新增適用車行/限定車種欄位
- fix: 修正 `dealer.rule.incentive.line` AttributeError、`dealer.rule.display_name`、備註顯示等版面問題

### dms_sale（16.0.2.0.0 → 16.0.2.1.0）
- feat: 新增 Excel 銷貨資料匯入 Wizard，支援大小寫不敏感、包含比對、括號附註剝除 fallback
- feat: OrderProcessor → DMIS 訂單自動匯入；result.json 新格式 + 空檔 fallback 讀 xlsx
- feat: 列表新增「重新同步」批次動作；`dms.sync.log` UI 重試按鈕
- feat: 新增舊車資訊頁籤、電車資訊頁籤（密碼遮罩 + 解鎖 wizard）
- feat: 新增交易類型「網路平台」依車行類型自動帶入
- feat: 新增「車款銷售分析」選單與 Pivot/Graph 視圖、`product_brand_id` 欄位
- feat: Search View 新增領牌日期/訂單日期區間篩選器

### dms_product（16.0.2.2.0 → 16.0.2.3.0）
- feat: 新增「產品頁面」獨立 menu/action；產品頁面/價格表 tree 新增「開啟詳細資料」按鈕
- feat: 新增改為 Wizard 彈窗、禁止 inline 新增；wizard 新增型號欄位、備註欄位上下排列支援換行
- style: 價格表標題不截斷、資料列換行、欄寬最佳化；車色/顧客贈品/附加費用說明改完整顯示
- fix: 價格表品牌下拉被遮擋；EV0 開頭車型品牌改為台鈴；pricelist_sticky MutationObserver 修復

### dms_report_ds（16.0.1.1.0 → 16.0.1.2.0）
- feat: 銷售分析改用 Metabase iframe 嵌入（Cloudflare tunnel + Odoo 反向代理）
- feat: motor_type / sales_source / sales_type / brand_type 規則重構為動態資料表（UI 可維護）
- feat: 新增 motor_type / brand_type 未命中診斷 wizard
- feat: 報表新增「重設」按鈕重載 iframe；啟用 Dashboard `titled=true`
- fix: 修正 EV 開頭車型品牌（宏佳騰→台鈴、e-moving→eReady）；Metabase Lato 字體 404 修復

### dms_parts（16.0.2.0.0 → 16.0.2.1.0）
- feat: 實作 EPC 零件目錄（#021）；PDF 自動建立分區與零件清單
- feat: wizard 新增分區頁縮圖預覽、CSV 樣板下載按鈕
- fix: PDF 解析多項缺陷修正（換行幽靈列、頁底頁碼過濾、第 6 頁外觀件停用）
- fix: CSV 樣板改中文表頭 + UTF-8 BOM 以避免 Excel 亂碼

### dms_core（16.0.1.1.0 → 16.0.1.2.0）
- feat: 系統版本資訊頁面新增 `dms_commission`、`dms_parts`、`dms_report_ds` 至模組清單
- feat: 系統版本資訊頁面更新版本歷程，彙整 04-02 之後 9 模組約 240 筆 commit
- fix: 品牌、車行類型選單限管理員可見
- fix: brand tree 圖片用 `options size` 取代非法 `width` 屬性

### user_management（16.0.1.0.0 → 16.0.1.1.0）
- feat: 隱藏討論/財務結算/庫存三個根選單
- feat: 額外隱藏銷售分析下的「原始數據查詢」選單

### dms_customer（16.0.1.0.0 → 16.0.1.1.0）
- fix: 改名車銷管理/價格表，新增車輛銷售子項，隱藏銷售管理/客戶管理頂層

### dms_report_virtual（16.0.1.0.0 → 16.0.1.1.0）
- fix: 金額欄位統一為整數位（台灣貨幣無小數）

### 文件
- chore: 新增《DMIS 後續優化與擴充規劃 v1》Word 與 specs/000-roadmap/04-future-enhancements.md
- chore: 重新產出《DMIS 專案進度報告 v5》（59 張新截圖）

---

## 目前模組版本（2026-04-02）

| 模組 | 版本 | 說明 |
|---|---|---|
| `dms_core` | `16.0.1.0.0` | 車行/品牌/車行類型 |
| `dms_customer` | `16.0.1.0.0` | 客戶主檔 |
| `dms_sale` | `16.0.2.0.0` | 銷售訂單 |
| `dms_product` | `16.0.2.0.7` | 產品模板/SKU/分期/日誌 |
| `dms_visit` | `16.0.1.1.0` | 拜訪紀錄 |
| `dms_finance` | `16.0.1.1.0` | 財務結算 |
| `dms_report` | `16.0.1.0.0` | 銷售 BI 報表 |
| `dms_report_rule` | `16.0.1.0.0` | 報表動態規則 |
| `dms_report_virtual` | `16.0.1.0.0` | 報表虛擬欄位 |
| `user_management` | `16.0.1.0.0` | 使用者/選單管理 |

---

## 2026-04-02

- fix(dms_sale): 訂單顏色欄位禁止直接新建（no_create: True）— spec 018 收尾
- feat(dms_product): 產品頁面列表新增備註欄位（optional show）
- fix(dms_product): 產品頁面 SKU 列表改用「開啟」按鈕，儲存後立即更新金額
- chore: 清除 dms_sale / dms_product 所有過渡期遺留選單代碼（共 13 個無用選單）
- fix(dms_product): 異動說明欄位改 store=False+inverse，儲存後自動清空（根本修正）
- fix(dms_product): 修正對話框儲存後疊加新視窗的問題
- feat(dms_product): 對話框儲存後停留不關閉視窗（action_save_and_stay）
- fix(dms_product): 修正 create()/write() 異動說明未清空且 log 未建立
- fix(dms_product): 月付金改用年金現值公式 PMT = PV × r / (1-(1+r)^-n)
- fix(dms_product): 年利率改為百分比輸入（1=1%），加 migration 16.0.2.0.5
- feat(dms_product): 分期方案異動日誌完整追蹤（periods/price_base/interest_rate/setup_fee/opening_fee）
- feat(dms_product): 活動特殊價變動記入價格日誌（old/new_promo_price）
- feat(dms_product): 產品項詳細資料改為單一 4-Tab 對話框（定價/分期/顏色/日誌）

---

## 2026-03-27

2026-03-27 - refactor(015): 移除重複的價格基準獨立選單

2026-03-27 - refactor(015): 收斂產品項下拉顯示為代碼與車種

2026-03-27 - fix(015): 修正產品顏色刪除後可售顏色摘要未同步

2026-03-27 - refactor(015): 收斂產品顏色維護畫面，移除多餘頁籤與欄位

2026-03-27 - feat(015): 在產品項列加入維護顏色入口，改為逐列新增顏色

2026-03-27 - refactor(015): 將產品項收斂為年份層並拆出顏色清單

2026-03-27 - feat(015): 價目版本支援複製並帶出價格基準

2026-03-27 - feat(016): 新增拜訪行事曆批次建立拜訪流程

2026-03-27 - feat(015): 讓批次加入產品項可同步套用統一價格

2026-03-27 - feat(015): 補上價目版本批次加入產品項與 SKU 辨識資訊

2026-03-27 - fix(015): 修正產品項複製後 breadcrumb 重複堆疊

2026-03-27 - fix(015): 修正產品項複製沿用內部代碼造成的誤判重複

2026-03-27 - feat(015): 補上產品項頁籤列級複製動作

2026-03-27 - fix(015): 修正產品模板頁籤刪除產品項的 FK 錯誤

2026-03-27 - feat(015): 補上產品模板可見的複製動作

2026-03-27 - fix(015): 模板 SKU 數量改為僅統計啟用產品項

2026-03-27 - fix(015): 停用產品項後仍保留於模板頁籤，支援重新啟用

2026-03-27 - feat(015): SKU 使用入口收斂為產品模板頁籤，移除獨立選單頁

2026-03-27 - fix(015): 出廠年份改為文字欄位，避免顯示千分位格式

2026-03-27 - docs(015): SKU 代碼規則調整為「型號 + 出廠年份」，並對齊自動回填邏輯

2026-03-27 - feat(015): 重建 dms_product 產品管理模組，加入模板 / SKU / 價格版本 / 分期規則 / 費用規則，並完成 dms_visit 送出物品脫鉤與 dms_sale 查價相容

2026-03-27 - docs(process): 新增「需重啟 Odoo 的變更必須自動重啟並驗證」規則

2026-03-27 - chore(maintenance): 清理 dms_product / dms_pricelist 舊頂層選單與殘留 xmlid

2026-03-27 - chore(spec): 刪除 013-dms-catalog 舊規格並清理 dms_catalog 模組登記

2026-03-27 - docs(spec): 同步 014 整併後架構，補齊 dms_sale 整併說明、部署文件與使用手冊

2026-03-27 - chore(maintenance): 新增 dms_catalog 殘留 metadata 清理與驗證收尾

2026-02-25 - 功能：新增車行（Dealer）主檔 MVP（含欄位、畫面、規格與 README）

（此條目作為 squash-style 合併紀錄，對應 PR #2）
