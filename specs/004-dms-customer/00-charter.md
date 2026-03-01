# Charter：dms_customer 客戶管理模組

## 背景
車行作業中，客戶資料（身分證、戶籍地址、民國生日、舊車資訊）分散在紙本與 Excel，且同一客戶資料在訂購單、報件單、Excel 中重複謄寫多次。

## 目標
- 集中管理客戶基本資料（繼承 Odoo 標準 `res.partner`）
- 擴充車行所需欄位：身分證字號、戶籍地址、生日（自動換算民國）
- 為每位客戶記錄舊車資訊（車牌、車主、車控帳號）
- 提供獨立「客戶管理」App，並可供 `dms_sale` 引用

## 範疇
- 新增 Odoo 模組 `dms_customer`
- 繼承擴充 `res.partner`（新增 `is_dms_customer` flag 及車行欄位）
- 新增 `dms.old.vehicle` 子模型

## 不在範疇
- 客戶信用評等
- 與政府戶籍系統 API 介接
