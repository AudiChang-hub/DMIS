# 模組地圖（Module Map）

## 總覽

```
base（Odoo 核心）
 └── dms_customer          P1 客戶管理

dms_core（車行管理）
 └── dms_product（車款規格）
      └── dms_pricelist     P1 價目管理
           └── dms_sale ◄── dms_customer   P2 銷售訂單
                └── dms_finance             P3 財務結算
                     └── dms_report         P4 BI 報表
```

## 模組清單

| 模組名稱 | 顯示名稱 | 優先 | 依賴 | 解決痛點 |
|---|---|---|---|---|
| `dms_core` | DMS 車行管理 | ✅ 已完成 | base, web | 車行、品牌、車行類型基礎資料 |
| `dms_product` | 產品管理 | ✅ 已完成 | dms_core, web | 車款規格（油/電、各 Char 欄位） |
| `dms_customer` | 客戶管理 | P1 | base | 客戶資料去重，取代 Excel 車主欄 |
| `dms_pricelist` | 價目管理 | P1 | dms_core, dms_product | 車款售價、精品售價、牌險費率、傭金規則 |
| `dms_sale` | 銷售訂單 | P2 | dms_core, dms_product, dms_pricelist, dms_customer | 訂單主檔、報件單 PDF、取代紙本 |
| `dms_finance` | 財務結算 | P3 | dms_sale | 收支明細、單筆淨利，取代 Excel 92 欄 |
| `dms_report` | 銷售 BI | P4 | dms_finance | Pivot/Graph 報表，發揮歷史資料價值 |

## 各模組核心模型

### dms_customer
- `dms.customer`（繼承 res.partner）：身分證字號、生日（國/民曆）、戶籍地址
- `dms.old.vehicle`：舊車資訊（車主、車控帳號、車牌）

### dms_pricelist
- `dms.vehicle.price`：車款售價（現金/分期/期數/有效月份/當月活動）
- `dms.accessory`：精品品項（名稱、型號）
- `dms.accessory.price`：精品單價、安裝費、套裝組合
- `dms.fee.schedule`：牌險費率（領牌費、強制險、代辦費，依車款）
- `dms.commission.rule`：車行傭金規則（依車行/車款/期數）

### dms_sale
- `dms.sale.order`：訂單主檔（來源：店面客戶 / 車行 B2B）
- `dms.sale.order.line`：車款 + 精品明細
- `dms.registration.form`：報件單（自動帶入，可列印 PDF）

#### dms.sale.order 關鍵欄位對應 Excel
| Excel 欄位 | 系統欄位 | 來源 |
|---|---|---|
| 車種型號 | product_id | dms_product |
| 車主名稱（重複2欄） | customer_id.name（1欄） | dms_customer |
| 身分證字號 | customer_id.id_number | dms_customer |
| 生日/民國生日 | customer_id.birthday（自動換算） | dms_customer |
| 戶籍地址 | customer_id.address_registered | dms_customer |
| 收款價 | amount_total | 手動/自動帶入 |
| 分期公司、期數 | finance_company, installment_period | 手動 |
| 車行 | dealer_id | dms_core |
| 車行收款、傭金 | dealer_amount, commission | dms_pricelist 帶出 |
| 領牌費/強制險/代辦費 | fee_registration, fee_insurance, fee_agency | dms_pricelist 帶出 |

### dms_finance
- `dms.sale.ledger`：每筆訂單財務分錄（自動從 dms.sale.order 產生）
- 收入分類：車款、牌險、代辦費、選號、中古車、報廢車、刷卡分期手續費、各項獎金補貼
- 支出分類：成本、信用卡/分期手續費、領牌稅、強制險、選號、中古車、贈品、車行傭金、各項獎金
- 結算：`net_profit`（單筆淨利，Computed）

### dms_report
- `dms.report.sales`：銷售分析 Pivot/Graph（依車行/品牌/車款/月份）
- `dms.report.profit`：利潤分析（各車款/車行單筆淨利分佈）
- `dms.report.accessory`：精品銷售組合、安裝費貢獻
- `dms.report.commission`：車行傭金趨勢
