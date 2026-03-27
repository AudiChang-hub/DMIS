# 00 — Charter：新一代產品管理模組重建（015-dms-product-rebuild）

## 背景

`014-module-removal` 已將舊版 `dms_product`、`dms_pricelist`、`dms_catalog` 自 repo 移除，並把舊有 `dms.product`、`dms.vehicle.price` 等模型暫時整併進 `dms_sale`，以先維持銷售與拜訪流程可運作。

目前真實現況是：

- 產品/價目資料仍為舊版扁平結構，主要模型仍是 `dms.product`、`dms.vehicle.price`、`dms.installment.plan`
- `dms_sale` 的產品畫面仍以舊產品主檔為中心，且 form 仍保留圖片頁籤
- `dms_visit`、`dms_finance` 及既有測試仍直接或間接依賴 `dms.product`
- DB 目前只有 2 筆 `dms.product`，但 `dms_vehicle_price` / `dms_installment_plan` / `dms_commission_rule` / `dms_ev_fee_schedule` 皆為 0 筆

本輪需求不是回頭復原舊模組，而是建立一個新的、可長期維護的「產品管理模組」，作為未來唯一的產品入口，並在不破壞既有銷售、拜訪、財務與車行管理功能的前提下，逐步收攏產品領域。

## 目標

1. 建立新的 `dms_product` 模組，作為未來唯一的產品管理入口。
2. 產品資料改為分層設計：
   - 產品模板層
   - 可販售產品項 / SKU 層
   - 價目版本與價格基準
   - 分期規則模板、規則明細、費用類型與費用明細
3. 價格查詢改為「只維護生效日，由系統抓取查詢日以前最近生效版本」。
4. 分期規則與費用規則採可擴充資料結構，不再以固定 type 欄位硬編碼。
5. 提供 migration / compatibility 機制，確保 `dms_sale`、`dms_visit`、`dms_finance`、`user_management` 與 `dms_core` 不被本輪重建破壞。
6. 對 `dms_visit` 採分階段策略：本輪先讓拜訪送出物品暫時與產品主檔斷開，待新產品管理模組穩定後再接回。

## 不在本輪範圍

- 不直接修改 Odoo 核心
- 不重寫 `dms_sale` / `dms_visit` / `dms_finance` 的完整流程
- 不修改 `dms_core` 既有模型、視圖、安全規則與資料
- 不以圖片作為新產品模組主功能
- 不粗暴刪除既有資料表或既有產品資料

## 核心原則

1. Spec-first：先完成 `015` 規格，再進入程式實作。
2. 所有新增或修改 `addons/**` 的變更，必須同步更新 `specs/**`。
3. 優先保護既有使用者流程與車行管理模組。
4. 若需相容層，必須明確設計、明確測試、明確記錄。
5. 任何需要重啟 Odoo 的變更，修改後必須自動重啟並補做驗證。
