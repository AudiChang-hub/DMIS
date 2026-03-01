# 系統開發主 Checklist（Master Checklist）

> 這是整套系統的驗收基準。  
> 每完成一個子項，勾選 `[x]`；模組全部完成後標記標題為 ✅。  
> 開發順序：spec 文件 → 模型 → 視圖 → ACL → 測試 → 升級驗證。

---

## ✅ Phase 0：基礎架構

### dms_core（DMS 車行管理）
- [x] 模型：dms.dealer（含所有欄位、copy()、onchange、constrains）
- [x] 模型：dms.brand
- [x] 模型：dms.store_type
- [x] 視圖：dealer tree/form/search + 4 頁籤 + Server Action 複製
- [x] 視圖：brand tree/form/action/menu
- [x] 視圖：store_type tree/form/action/menu
- [x] ACL：dealer/brand/store_type 全員讀寫
- [x] JS：dealer 列表 15 欄硬限制（patch + OWL rerender）
- [x] 種子資料：seed.xml
- [x] manifest：application=True，name="DMS 車行管理"
- [x] 頂層選單：menu_dms_root（name="車行管理"）

### dms_product（產品管理）
- [x] 模型：dms.product（基本資料、油車/電車/車身規格，全 Char）
- [x] 視圖：product tree（8 show + 22 hide）+ form（4 頁籤，動力依 energy_type 切換）
- [x] 視圖：search（名稱/型號/品牌）+ 油/電/啟用篩選
- [x] ACL：dms.product 全員讀寫
- [x] JS：product 列表 15 欄硬限制
- [x] manifest：application=True，depends=[dms_core, web]
- [x] 頂層選單：menu_dms_product_root（獨立 App，不掛 dms_core 下）

---

## ✅ Phase 1：P1 — 資訊透明化

### ✅ dms_customer（客戶管理）
> Spec 目錄：`specs/004-dms-customer/`

- [x] **Spec**
  - [x] 00-charter.md
  - [x] 01-spec.md（欄位定義、繼承 res.partner 策略）
  - [x] 04-tasks.md
  - [x] 05-acceptance.md

- [x] **模型**
  - [x] `dms.customer`（繼承/擴充 res.partner）
    - [x] `id_number`（身分證字號，Char）
    - [x] `dms_birthday`（生日，Date）
    - [x] `dms_birthday_roc`（民國生日，Computed Char）
    - [x] `address_registered`（戶籍地址，Text）
    - [x] `old_vehicle_ids`（One2many → dms.old.vehicle）
  - [x] `dms.old.vehicle`
    - [x] `partner_id`（Many2one → res.partner）
    - [x] `plate_number`（車牌號碼）
    - [x] `vehicle_owner`（舊車車主）
    - [x] `control_account`（車控帳號）

- [x] **視圖**
  - [x] customer tree（姓名/電話/身分證/民國生日/戶籍地址）
  - [x] customer form（繼承 partner form，新增 DMS 客戶資料 & 舊車資訊頁籤）
  - [x] search（姓名/身分證/電話）+ 「DMS 客戶」篩選
  - [x] 頂層選單：menu_dms_customer_root（獨立 App）

- [x] **ACL**：dms.old.vehicle 全員讀寫

- [x] **驗證**
  - [x] --stop-after-init `-i dms_customer` 無錯誤（139 queries）
  - [x] /web/login HTTP 200

---

### ✅ dms_pricelist（價目管理）
> Spec 目錄：`specs/005-dms-pricelist/`

- [x] **Spec**
  - [x] 00-charter.md
  - [x] 01-spec.md
  - [x] 04-tasks.md
  - [x] 05-acceptance.md

- [x] **模型：車款售價**
  - [x] `dms.vehicle.price`（product_id / dealer_id / cash_price / installment_periods / installment_monthly / finance_company / valid_year_month / is_promotion / active / note）

- [x] **模型：精品**
  - [x] `dms.accessory`（name / model_number / active / price_ids O2m）
  - [x] `dms.accessory.price`（accessory_id / unit_price / install_fee / bundle_name / valid_from / valid_to / active）

- [x] **模型：牌險費率**
  - [x] `dms.fee.schedule`（product_id / fee_registration / fee_compulsory_insurance / fee_agency / valid_from / valid_to / active / note）

- [x] **模型：傭金規則**
  - [x] `dms.commission.rule`（dealer_id / product_id / installment_periods / commission_amount / commission_rate / valid_from / valid_to / active / note）

- [x] **視圖**：5 個模型各有 tree（所有欄位 optional）/ form / search（啟用中/已歸檔）
- [x] **ACL**：5 個模型全員讀寫
- [x] 頂層選單：menu_dms_pricelist_root（獨立 App，下掛 5 子選單）

- [x] **驗證**
  - [x] `--stop-after-init -i dms_pricelist` 無 ERROR（293 queries）
  - [x] `/web/login` HTTP 200
  - [ ] 牌險費率依車款查詢正確

---

## 🔲 Phase 2：P2 — 核心業務數位化

### dms_sale（銷售訂單）
> Spec 目錄：`specs/006-dms-sale/`

- [ ] **Spec**
  - [ ] 00-charter.md（含訂單類型區分：店面 vs 車行）
  - [ ] 01-spec.md（完整欄位對照 Excel 清理結果）
  - [ ] 02-clarify.md（台鈴/山葉差異處理方式）
  - [ ] 04-tasks.md
  - [ ] 05-acceptance.md

- [ ] **模型：dms.sale.order**
  - [ ] 基本識別：序號（自動）、訂單日期、來源類型（店面/車行）
  - [ ] 客戶資訊：customer_id → dms.customer（帶出身分證/地址/電話）
  - [ ] 車輛：product_id、顏色、引擎號碼/車身號碼
  - [ ] 金流：收款價、成本、付款方式（現金/信用卡/分期）
  - [ ] 分期：finance_company、installment_period、installment_price
  - [ ] 牌險（從 dms_pricelist 帶出）：領牌費、強制險、代辦費、選號費
  - [ ] 車牌：plate_number、領牌日期
  - [ ] 車行（B2B）：dealer_id、dealer_amount、commission（從規則帶出）
  - [ ] 其他：安全帽、公司禮卷/匯款、贈品、備註、特殊方案

- [ ] **模型：dms.sale.order.line**（精品明細）
  - [ ] accessory_id、unit_price、install_fee、quantity

- [ ] **模型：dms.registration.form**（報件單）
  - [ ] 關聯 sale.order，自動帶入所有欄位
  - [ ] QWeb 列印範本（PDF）

- [ ] **視圖**
  - [ ] 訂單 tree（序號/客戶/車款/收款價/領牌日期/狀態）
  - [ ] 訂單 form（多頁籤：基本/車輛/金流/精品/報件/備註）
  - [ ] 報件單列印按鈕
  - [ ] search + filter（店面/車行/月份/品牌）

- [ ] **ACL**：dms.sale.order / line / registration 全員讀寫

- [ ] **驗證**
  - [ ] 選車款後自動帶入車款售價
  - [ ] 選車行後自動帶入傭金
  - [ ] 牌險費率自動帶入
  - [ ] 可列印報件單 PDF
  - [ ] 店面訂單與車行訂單欄位顯示差異正確

---

## 🔲 Phase 3：P3 — 財務結算

### dms_finance（財務結算）
> Spec 目錄：`specs/007-dms-finance/`

- [ ] **Spec**
  - [ ] 00-charter.md
  - [ ] 01-spec.md（收入/支出分類定義，對應 Excel 欄位）
  - [ ] 04-tasks.md
  - [ ] 05-acceptance.md

- [ ] **模型：dms.sale.ledger**
  - [ ] 收入欄位（15 項）：車款收入、領牌稅金收入、強制險收入、代辦費收入、選號收入、中古車收入、報廢車收入、刷卡手續費收入、分期手續費收入、山葉獎金、友善車行獎金、其他收入、實銷獎勵金、促銷補助金、分期補貼息、強制險傭金、信用卡傭金
  - [ ] 支出欄位（11 項）：成本、信用卡手續費支出、分期手續費支出、領牌稅金支出、強制險支出、選號支出、中古車支出、贈品及運費支出、車行傭金支出、友善車行獎金支出、首賣/台數獎金支出
  - [ ] 結算：`net_profit`（Computed = 所有收入 - 所有支出）
  - [ ] 其他：補助方案、補助金額、銀行、匯款帳戶、申請日

- [ ] **視圖**
  - [ ] 每筆訂單財務分錄 tree/form
  - [ ] 從 sale.order 嵌入 Smart Button 進入財務分錄

- [ ] **驗證**
  - [ ] 建立訂單後自動產生财務分錄
  - [ ] 修改收支項目後 net_profit 自動更新
  - [ ] 單筆淨利顯示正確

---

## 🔲 Phase 4：P4 — BI 報表

### dms_report（銷售 BI）
> Spec 目錄：`specs/008-dms-report/`

- [ ] **Spec**（同上格式）

- [ ] **報表**
  - [ ] `dms.report.sales`：銷售分析 Pivot/Graph（車行/品牌/車款/月份/銷售員）
  - [ ] `dms.report.profit`：利潤分析（各車款/車行單筆淨利）
  - [ ] `dms.report.accessory`：精品銷售組合、安裝費貢獻
  - [ ] `dms.report.commission`：車行傭金趨勢

- [ ] **驗證**
  - [ ] Pivot 可依月份/品牌/車款自由切換分組
  - [ ] Graph 折線/柱狀切換正常
  - [ ] 資料與 dms_finance 一致

---

## 整體系統驗收（所有 Phase 完成後）

- [ ] 從賞車到訂單完成，全程不需手寫紙本（報件單由系統印出）
- [ ] 同一筆客戶資料僅需登打一次，訂單自動帶出
- [ ] 傭金、牌險費率由系統帶出，不需憑記憶
- [ ] Excel 92 欄資料可由系統對應欄位完整替代
- [ ] BI 報表可依月份/車行/品牌/車款切換檢視
- [ ] 所有模組升級無錯誤，/web/login HTTP 200
