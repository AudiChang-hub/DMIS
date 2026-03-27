# 模組地圖（Module Map）

## 總覽

```
base（Odoo 核心）
 └── dms_customer          P1 客戶管理

dms_core（車行管理）
 └── dms_sale ◄── dms_customer   P2 銷售 / 產品 / 價目整合
      ├── dms_visit              拜訪管理
      └── dms_finance            P3 財務結算
           └── dms_report        P4 BI 報表
                └── dms_report_rule
                     └── dms_report_virtual

user_management（使用者管理）獨立提供菜單白名單與權限同步
```

## 模組清單

| 模組名稱 | 顯示名稱 | 優先 | 依賴 | 解決痛點 |
|---|---|---|---|---|
| `dms_core` | DMS 車行管理 | ✅ 已完成 | base, web | 車行、品牌、車行類型基礎資料 |
| `dms_customer` | 客戶管理 | P1 | base | 客戶資料去重，取代 Excel 車主欄 |
| `dms_sale` | 銷售管理 | P2 | dms_core, dms_customer | 訂單主檔、產品資料、價目資料、取代紙本/Excel |
| `dms_visit` | 拜訪紀錄 | P2 | dms_core, dms_sale | 車行拜訪紀錄、行事曆、送出物品與排程 |
| `dms_finance` | 財務結算 | P3 | dms_sale | 收支明細、單筆淨利，取代 Excel 92 欄 |
| `dms_report` | 銷售 BI | P4 | dms_finance | Pivot/Graph 報表，發揮歷史資料價值 |
| `dms_report_rule` | 報表規則設定 | P4 | dms_report | 動態定義報表規則與預覽 |
| `dms_report_virtual` | 報表虛擬欄位 | P4 | dms_report_rule | 無須改碼即可做分群欄位 |
| `user_management` | 使用者管理 | Admin | base, web | 菜單白名單、原生群組同步、操作稽核 |

## 各模組核心模型

### dms_customer
- `dms.customer`（繼承 res.partner）：身分證字號、生日（國/民曆）、戶籍地址
- `dms.old.vehicle`：舊車資訊（車主、車控帳號、車牌）

### dms_sale（含原產品 / 價目模型）
- `dms.product`：車款主檔
- `dms.product.color`：車款顏色
- `dms.vehicle.price`：車款售價（現金/分期/期數/有效月份/當月活動）
- `dms.accessory`：精品品項（名稱、型號）
- `dms.installment.plan`：分期方案
- `dms.ev.fee.schedule`：電車牌險費率
- `dms.commission.rule`：車行傭金規則（依車行/車款/期數）
- `dms.sale.order`：訂單主檔（來源：店面客戶 / 車行 B2B）
- `dms.sale.order.line`：精品明細

#### dms.sale.order 關鍵欄位對應 Excel
| Excel 欄位 | 系統欄位 | 來源 |
|---|---|---|
| 車種型號 | product_id | dms_sale（內含 dms.product） |
| 車主名稱 | customer_name / customer_id.name | dms_sale / dms_customer |
| 身分證字號 | id_number | dms_sale / dms_customer |
| 生日/民國生日 | birthday_roc | dms_sale / dms_customer |
| 戶籍地址 | address_registered | dms_sale / dms_customer |
| 收款價 | amount_total | 手動/自動帶入 |
| 分期公司、期數 | finance_company, installment_periods | 手動 |
| 車行 | dealer_id | dms_core |
| 車行收款、傭金 | dealer_amount, commission | dms_sale（commission_rule）帶出 |
| 領牌費/強制險/代辦費 | fee_vehicle_registration 等欄位 | dms_sale（ev_fee_schedule）帶出或手填 |

### dms_finance
- `dms.sale.finance`：每筆訂單財務結算主檔
- `dms.sale.finance.income`：收入明細
- `dms.sale.finance.expense`：支出明細
- 結算：`net_profit`（單筆淨利，Computed）

### dms_report
- 以 Odoo 原生 Pivot / Graph 視圖分析 `dms.sale.order` 與 `dms.sale.finance`

### dms_report_rule
- `dms.report.rule`：動態報表規則，定義 model / dimension / measure / chart type / domain

### dms_report_virtual
- `dms.report.virtual.field`：虛擬欄位主檔
- `dms.report.virtual.field.rule`：虛擬欄位規則
