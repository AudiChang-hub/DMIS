# 開發任務（04-tasks）— dms_sale

## Spec
- [x] 00-charter.md ✅
- [x] 01-spec.md ✅
- [x] 04-tasks.md ✅
- [x] 05-acceptance.md ✅

## 模型
- [ ] `dms.sale.order`（sale_order.py）—含序號、onchange、狀態機
- [ ] `dms.sale.order.line`（sale_order_line.py）—含 subtotal compute

## 資料
- [ ] `data/sequence.xml`（ir.sequence：SO%(year)s%(month)s{4碼}）

## 視圖
- [ ] `views/sale_order_views.xml`（tree/form 5tab/search/action/menu）
- [ ] `views/product_views.xml`（整併自原 `dms_product`）
- [ ] `views/product_kanban_config_views.xml`（整併自原 `dms_product`）
- [ ] `views/accessory_views.xml`（整併自原 `dms_pricelist`）
- [ ] `views/vehicle_price_views.xml`（整併自原 `dms_pricelist`）
- [ ] `views/fee_schedule_views.xml`（整併自原 `dms_pricelist`）
- [ ] `views/commission_rule_views.xml`（整併自原 `dms_pricelist`）
- [ ] `views/product_pricelist_menu.xml`（產品資料 / 價目資料整合選單）

## 安全性
- [ ] `security/ir.model.access.csv`（2 個模型全員讀寫）

## 模組骨架
- [ ] `__init__.py`
- [ ] `__manifest__.py`（depends: dms_core, dms_customer）
- [ ] `models/__init__.py`

## 安裝驗證
- [ ] `--stop-after-init -i dms_sale` 無 ERROR
- [ ] 重啟後 `/web/login` HTTP 200
- [ ] 「DMS 銷售管理」頂層選單與「銷售訂單」子選單顯示正常
- [ ] 新增訂單時序號自動產生（SO2026MMNNNN）
- [ ] 選電車後牌險費自動帶入
- [ ] 選分期公司帶出傭金

## 2026-05 匯入補正
- [x] `order_sync` 缺少 docx 時仍可由 xlsx 補讀車型、顏色、車行等欄位
- [x] `是否有分期=18期` 不再誤寫 `finance_company` 導致建立失敗
- [x] 重新同步相同資料夾時，僅重建 OrderProcessor 暫存資料，不得更新 `dms.sale.order`
- [x] Excel 匯入遇到 A1 這類模板 family/model 名稱時，仍可命中對應的 `dms.product`
- [x] `dms.sync.log` 保存 raw JSON、fallback 與標準化欄位快照
- [x] Excel 匯入不再依賴 `order_processor` 訂單做跨來源合併
