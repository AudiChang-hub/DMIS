# Charter：dms_sale 銷售管理模組

## 背景

車行每筆銷售需同時填寫紙本訂購單，並謄寫至 92 欄 Excel。資料在多個
來源間重複，容易出錯，且無歷史查詢能力。

## 目標

- 以電子訂單取代紙本，減少重複謄寫
- 從價目管理自動帶入售價、牌險費率、傭金
- 支援兩種交易類型：**店面客戶**（B2C）vs **車行**（B2B）
- 為 `dms_finance`、`dms_report` 提供結構化資料來源

## 範疇

- 新增模組 `dms_sale`
- 2 個模型：`dms.sale.order`（訂單主檔）、`dms.sale.order.line`（精品明細）
- 獨立 App「DMS 銷售管理」
- 自動帶入邏輯：現金售價（dms.vehicle.price）、電車牌險費（dms.ev.fee.schedule）、傭金（dms.commission.rule）

## 不在範疇

- 公文 PDF 報件單（後續迭代負責）
- 庫存管理（進出庫）
- 多公司架構

## 依賴

| 模組 | 原因 |
|---|---|
| `dms_core` | 引用 `dms.dealer` |
| `dms_customer` | 引用客戶資料（res.partner 擴充欄位） |

> 2026-03-27 更新：原 `dms_product` / `dms_pricelist` 已於 `014-module-removal` 整併進 `dms_sale`。因此 `dms_sale` 現在同時承接 `dms.product`、`dms.product.color`、`dms.vehicle.price`、`dms.installment.plan`、`dms.accessory`、`dms.ev.fee.schedule`、`dms.commission.rule`、`dms.kanban.product.config` 等模型。
