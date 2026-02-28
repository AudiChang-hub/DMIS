# Charter：dms_product 獨立產品管理模組

## 背景
原本產品管理實作於 `dms_core`；為維持模組職責分離，現拆分為獨立模組 `dms_product`。

## 驅動力
- 關注點分離：`dms_core` 負責車行/品牌/類型基礎設定；產品資料由 `dms_product` 負責。
- 獨立安裝/停用：未來可視需求選裝。

## 範疇
- 新增 Odoo 模組 `dms_product`（`addons/dms_product/`）。
- 遷移 `dms.product` 模型、視圖、ACL、前端 JS 限制。
- 依賴 `dms_core`（使用 `dms.brand`）、`web`。
- 不修改 Odoo 核心；不修改 `dms_core` 的業務邏輯。

## 不在範疇
- 產品報表
- 多公司支援
