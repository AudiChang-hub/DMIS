# 系統開發主 Checklist（Master Checklist）

> 這是整套系統的驗收基準。  
> 每完成一個子項，勾選 `[x]`；模組全部完成後標記標題為 ✅。  
> 開發順序：spec 文件 → 模型 → 視圖 → ACL → 測試 → 升級驗證。

> 2026-03-27 現況快照：
> - 舊 `dms_product`、`dms_pricelist` 已依 `014-module-removal` 完成清理與收尾
> - 新 `dms_product` 已依 `015-dms-product-rebuild` 重建，成為正式產品入口
> - `dms_visit`、`dms_finance`、`dms_report`、`dms_report_rule`、`dms_report_virtual`、`user_management` 均已有程式碼與已安裝模組
> - 下列 checklist 保留歷史開發軌跡，但目前架構應以 `015-dms-product-rebuild` 後版本為準

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

### dms_product（產品管理，015 重建）
- [x] 模型：`dms.product.template`
- [x] 模型：`dms.product` 作為 SKU 相容層（`template_id / internal_code / production_year`）
- [x] 模型：`dms.price.version` / `dms.price.line`
- [x] 模型：`dms.installment.rule*` / `dms.fee.type`
- [x] 視圖：產品模板 / 產品項 / SKU / 價目版本 / 價格基準 / 分期規則模板 / 費用類型 / 規則掛接
- [x] ACL：新 canonical 模型全員讀寫
- [x] manifest：application=True，depends=[dms_core, dms_sale]
- [x] 頂層選單：menu_dms_product_root（正式產品管理入口）

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

### ✅ dms_pricelist（歷史模組，已移除）
> Spec 目錄：`specs/005-dms-pricelist/`

- [x] **Spec**
  - [x] 00-charter.md
  - [x] 01-spec.md
  - [x] 04-tasks.md
  - [x] 05-acceptance.md

- [x] **模型：車款售價**（設計已調整）
  - [x] `dms.vehicle.price`（product_id / cash_price / valid_year_month / is_promotion / active / note）
  - [x] ~~dealer_id 已移除~~：售價不綁車行
  - [x] `dms.installment.plan`（O2m：price_id / installment_periods / installment_monthly / finance_company / active）

- [x] **模型：精品**（設計已合併）
  - [x] `dms.accessory`（name / model_number / unit_price / install_fee / bundle_name / valid_from / valid_to / active / note）
  - [x] ~~dms.accessory.price 已合併至 dms.accessory~~（accessory_price.py 保留空檔）

- [x] **模型：牌險費率（電車專用）**（設計已調整）
  - [x] `dms.ev.fee.schedule`（product_id domain=electric / fee_vehicle_registration / fee_inspection / fee_plate / fee_stamp / fee_insurance / fee_guild_cert / fee_document / fee_other / fee_total computed / valid_from / valid_to / active / note）
  - [x] `dms.fee.schedule`（仍存在，一般費率表）

- [x] **模型：傭金規則**
  - [x] `dms.commission.rule`（dealer_id / product_id / installment_periods / commission_amount / commission_rate / valid_from / valid_to / active / note）

- [x] **視圖**：各模型有 tree（所有欄位 optional）/ form / search （啟用中/已歸檔）
- [x] **ACL**：各模型全員讀寫
- [x] 舊頂層選單與模組登記已清理

- [x] **驗證**
  - [x] `--stop-after-init -u dms_pricelist` 無 ERROR（239 queries）2026-03-04
  - [x] `/web/login` HTTP 200
  - [x] DB 資料表確認：dms_installment_plan / dms_ev_fee_schedule / dms_vehicle_price 均存在

---

## 🔲 Phase 2（持續驗證中）：P2 — 核心業務數位化

### ✅ dms_sale（銷售訂單）
> Spec 目錄：`specs/006-dms-sale/`

- [x] **Spec**（已建立，與實作同步）

- [x] **模型：dms.sale.order**
  - [x] 序號自動 `SO{YYYYMM}{4-digit}`，state machine 草稿→確認/取消
  - [x] `sale_type`：店面 / 車行(B2B)
  - [x] 客戶資訊：customer_id / related id_number / birthday_roc / address_registered
  - [x] 車輛：product_id / product_energy_type(related) / color / engine_number / frame_number / plate_number / registration_date
  - [x] 金流：cash_price / amount_total / cost / payment_method / finance_company / installment_periods / installment_monthly
  - [x] 車行：dealer_id / dealer_amount / commission
  - [x] 牌險費（9 欄）：fee_vehicle_registration / fee_inspection / fee_plate / fee_stamp / fee_plate_selection / fee_insurance / fee_guild_cert / fee_document / fee_other / fee_total（computed store）
  - [x] 精品 O2m：order_line_ids → dms.sale.order.line
  - [x] 其他：helmet_count / gift_voucher / gift_note / special_plan / note / active
  - [x] button_confirm / button_reset / button_cancel

- [x] **模型：dms.sale.order.line**（精品明細）
  - [x] accessory_id / unit_price / install_fee / quantity / subtotal（computed）
  - [x] onchange: accessory_id 帶入價格

- [x] **onchange**
  - [x] product_id → 優先從 `dms.price.line` 帶入 cash_price；無資料時 fallback `dms.vehicle.price`
  - [x] 電車 → 自動帶入牌險費
  - [x] dealer_id / product_id / installment_periods → 自動帶入 commission

- [x] **視圖**（5 頁籤 form）
  - [x] 客戶與車輛 / 金流 / 牌險費 / 精品 / 其他
  - [x] 電車/油車 advisory banner（attrs domain 格式）
  - [x] 分期欄位 attrs invisible（payment_method != installment）
  - [x] 車行欄位 attrs invisible（sale_type != dealer）
  - [x] search：姓名/身分證/車款/車牌/引擎/車身 + 店面/車行/狀態 filter + 月份分組

- [x] **ACL**：dms.sale.order / dms.sale.order.line 全員讀寫
- [x] **序號資料**：ir.sequence dms.sale.order

- [x] **驗證**
  - [x] `--stop-after-init -u dms_sale` 無 ERROR（108 queries）2026-03-04
  - [x] `/web/login` HTTP 200
  - [x] DB 資料表：dms_sale_order（43 欄）/ dms_sale_order_line 均存在
  - [x] Odoo 測試：選車款帶售價（新 canonical 優先 / legacy fallback）
  - [ ] 手動建單：電車帶牌險費、選車行帶傭金
  - [ ] 精品明細：新增精品行帶入價格、小計計算正確

---

## 🔲 Phase 3（已實作，待補齊驗證）：P3 — 財務結算

### dms_finance（財務結算）
> Spec 目錄：`specs/007-dms-finance/`

- [x] **Spec**
  - [x] 00-charter.md
  - [x] 01-spec.md（收入/支出分類定義，對應 Excel 欄位）
  - [x] 04-tasks.md
  - [x] 05-acceptance.md

- [x] **模型：dms.sale.finance**
  - [x] `dms.sale.finance`（主檔）
  - [x] `dms.sale.finance.income`（收入明細）
  - [x] `dms.sale.finance.expense`（支出明細）
  - [x] `dms.finance.category`（收入/支出分類）
  - [x] 結算：`net_profit`（Computed = 所有收入 - 所有支出）

- [x] **視圖**
  - [x] 每筆訂單財務分錄 tree/form
  - [x] 從 sale.order 嵌入 Smart Button 進入財務分錄

- [ ] **驗證**
  - [ ] 建立訂單後自動產生財務分錄
  - [x] 修改收支項目後 net_profit 自動更新
  - [ ] 單筆淨利顯示正確

---

## 🔲 Phase 4（已實作，待補齊驗證）：P4 — BI 報表

### dms_report（銷售 BI）
> Spec 目錄：`specs/008-dms-report/`

- [x] **Spec**（同上格式）

- [ ] **報表**
  - [x] 銷售與利潤相關 Pivot / Graph 視圖
  - [x] `dms_report_rule`：動態報表規則
  - [x] `dms_report_virtual`：虛擬欄位分群

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
