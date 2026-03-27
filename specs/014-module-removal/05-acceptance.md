# 驗收條件（05-acceptance）— 014-module-removal

## 環境 / 啟動
- [ ] `docker compose up -d` 一鍵啟動，無 ERROR 訊息
- [x] `make smoke` / `bash scripts/smoke_odoo.sh` 在 180 秒內通過（HTTP 200/302/303）
- [ ] `docker compose ps` 顯示 odoo 容器 `Up (healthy)` 狀態

## 模組清單驗收
- [ ] Odoo Settings → Apps 中，`dms_product`, `dms_pricelist`, `dms_catalog` 不再列出
- [x] `dms_sale` 顯示為已安裝，版本提升（或 manifest 更新日期更新）
- [x] `dms_visit` 顯示為已安裝，依賴滿足

## Metadata 驗收
- [x] `docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init` 無 `dms_catalog` catalog-only 模型 warning
- [x] `ir_model` 中不存在 `dms.product.template`、`dms.product.sku`、`dms.price.version`、`dms.price.line`、`dms.installment.rule`、`dms.installment.rule.line`、`dms.fee.type`、`dms.installment.rule.fee`
- [x] `ir_module_module` 中不存在 `dms_catalog`、`dms_product`、`dms_pricelist`
- [x] `ir_model_data` 中不存在 `dms_catalog`、`dms_product`、`dms_pricelist`
- [x] 專案內提供可重複執行的 cleanup 腳本

## 資料完整性
- [x] 既有 `dms.product` 記錄全數保留（資料表不變，row 數一致）
- [x] 既有 `dms.accessory` 記錄全數保留
- [x] 既有 `dms.vehicle.price` 記錄全數保留
- [x] 既有 `dms.sale.order` 記錄全數保留

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
- [x] 不再出現舊頂層「產品管理」/「價目管理」/「產品目錄」選單
- [ ] 「銷售管理 → 產品資料 → 車款管理」選單可進入 tree/form
- [ ] 「銷售管理 → 價目資料 → 車款售價」選單可進入
- [ ] 「銷售管理 → 價目資料 → 精品管理」選單可進入
- [ ] 「銷售管理 → 價目資料 → 傭金規則」選單可進入

## 功能驗收 — 拜訪管理
- [ ] 可建立拜訪紀錄
- [ ] 送出物品可選擇產品（`dms.product`）
- [ ] 拜訪排程自動建立正常

## 已移除確認
- [x] `addons/dms_product/` 資料夾不存在
- [x] `addons/dms_pricelist/` 資料夾不存在
- [x] `addons/dms_catalog/` 資料夾不存在

## 文件同步確認
- [x] `README.md` 已改為 `dms_sale` 整併架構
- [x] `SETUP.md` 的模組安裝步驟與依賴圖已改為目前實作
- [x] `docs/USER_MANUAL.md` 不再指示使用獨立的 `dms_product` / `dms_pricelist` App
- [x] `docs/erd.md` 已標明 `dms.product` / `dms.vehicle.price` 等模型現由 `dms_sale` 持有
- [x] `specs/006-dms-sale/**` 與 `specs/011-dms-visit/**` 的依賴描述已對齊現況
- [x] `specs/013-dms-catalog/` 已自 repo 移除

## Tests
- [x] `dms_core/tests/` 全部通過
- [x] `dms_visit/tests/` 全部通過
- [x] `user_management/tests/` 全部通過
- [x] `dms_sale` 無 Python 語法錯誤（模組可正常載入）

## 驗收指令（可重現）
```bash
make up
docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init
make smoke
docker compose exec odoo odoo -d dmis_dev -u dms_core,dms_visit,user_management,dms_finance,dms_report_rule,dms_report_virtual --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --http-port=8070 --test-enable --stop-after-init
python3 scripts/cleanup_dms_catalog_metadata.py
```
