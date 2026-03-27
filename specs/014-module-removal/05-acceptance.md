# 驗收條件（05-acceptance）— 014-module-removal

## 環境 / 啟動
- [ ] `docker compose up -d` 一鍵啟動，無 ERROR 訊息
- [ ] `make smoke` 在 180 秒內通過（HTTP 200/302/303）
- [ ] `docker compose ps` 顯示 odoo 容器 `Up (healthy)` 狀態

## 模組清單驗收
- [ ] Odoo Settings → Apps 中，`dms_product`, `dms_pricelist`, `dms_catalog` 不再列出
- [ ] `dms_sale` 顯示為已安裝，版本提升（或 manifest 更新日期更新）
- [ ] `dms_visit` 顯示為已安裝，依賴滿足

## 資料完整性
- [ ] 既有 `dms.product` 記錄全數保留（資料表不變，row 數一致）
- [ ] 既有 `dms.accessory` 記錄全數保留
- [ ] 既有 `dms.vehicle.price` 記錄全數保留
- [ ] 既有 `dms.sale.order` 記錄全數保留，`product_id`、`color_id`、`order_line_ids` 正常顯示

## 功能驗收 — 車行管理（絕對不可回退）
- [ ] 可建立新車行（dms.dealer）
- [ ] 車行表單 4 個分頁正常顯示
- [ ] 搜尋功能正常（code/name/phone）
- [ ] `make smoke` 對應測試通過

## 功能驗收 — 使用者管理（絕對不可回退）
- [ ] 可建立/編輯使用者
- [ ] 角色/群組指派正常
- [ ] `user_management` 測試全數通過

## 功能驗收 — 銷售管理
- [ ] 可建立銷售訂單
- [ ] 車款選單（`dms.product`）正常顯示
- [ ] 顏色下拉清單（`dms.product.color`）隨車款正確過濾
- [ ] 精品明細可新增（`dms.accessory`）
- [ ] 選車款後自動帶入車款售價（`dms.vehicle.price`）
- [ ] 電車自動帶入牌險費（`dms.ev.fee.schedule`）
- [ ] 傭金自動計算（`dms.commission.rule`）

## 功能驗收 — 產品與價目（現在在 dms_sale 選單下）
- [ ] 「銷售管理 → 產品資料 → 車款管理」選單可進入 tree/form
- [ ] 「銷售管理 → 價目資料 → 車款售價」選單可進入
- [ ] 「銷售管理 → 價目資料 → 精品管理」選單可進入
- [ ] 「銷售管理 → 價目資料 → 傭金規則」選單可進入

## 功能驗收 — 拜訪管理
- [ ] 可建立拜訪紀錄
- [ ] 送出物品可選擇產品（`dms.product`）
- [ ] 拜訪排程自動建立正常

## 已移除確認
- [ ] `addons/dms_product/` 資料夾不存在
- [ ] `addons/dms_pricelist/` 資料夾不存在
- [ ] `addons/dms_catalog/` 資料夾不存在

## Tests
- [ ] `dms_core/tests/` 全部通過
- [ ] `dms_visit/tests/` 全部通過
- [ ] `user_management/tests/` 全部通過
- [ ] `dms_sale` 無 Python 語法錯誤（模組可正常載入）

## 驗收指令（可重現）
```bash
make up
docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --stop-after-init
make smoke
docker compose exec odoo python -m pytest addons/dms_core/tests/ -v 2>/dev/null || \
  docker compose exec odoo odoo -d dmis_dev --test-enable --test-tags dms_core --stop-after-init
```
