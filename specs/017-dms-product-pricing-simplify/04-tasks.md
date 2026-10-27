# 04 — Tasks：產品定價簡化（017-dms-product-pricing-simplify）

## Phase 1：Spec 確立

- [x] 建立 `specs/017-dms-product-pricing-simplify/` 完整規格文件（00~05）

## Phase 2：`dms_product` 模型擴充

- [ ] `addons/dms_product/models/product_compat.py`（`dms.product` 繼承）
  - [ ] 新增 `cash_price`, `list_price`, `promo_price`, `promo_note` 欄位
  - [ ] 新增 `installment_rule_ids`（M2M → `dms.installment.rule`）
  - [ ] 新增 `price_log_ids`（O2M → `dms.product.price.log`）
  - [ ] 新增 `effective_price`（computed depends `cash_price`, `promo_price`）
  - [ ] 覆寫 `write()`，當 `cash_price` 或 `list_price` 變更時自動寫入 `dms.product.price.log`
- [ ] 新建 `addons/dms_product/models/product_price_log.py`（`dms.product.price.log`）
- [ ] 更新 `addons/dms_product/models/__init__.py`
- [ ] `addons/dms_product/__manifest__.py`：版本號改為 `16.0.2.0.0`

## Phase 3：視圖

- [ ] `addons/dms_product/views/product_views.xml`：在 `dms.product` 表單新增「定價與分期」Tab
  - 目前售價區（cash_price, list_price, effective_price 唯讀）
  - 活動特殊價區（promo_price, promo_note，含無活動提示）
  - 適用分期規則（installment_rule_ids many2many tree）
  - 價格異動日誌（price_log_ids one2many 唯讀）
- [ ] `addons/dms_product/views/menu_views.xml`：移除「價目版本」和「規則掛接」選單
- [ ] 更新 `addons/dms_product/__manifest__.py` 的 `data` 清單（加入 price_log_views.xml）
- [ ] 新建 `addons/dms_product/views/price_log_views.xml`（price_log 清單視圖，供從產品頁 embedded 用）

## Phase 4：安全設定

- [ ] `addons/dms_product/security/ir.model.access.csv`
  - 新增 `dms.product.price.log` 只允許 create/read（系統寫入），不允許 write/unlink
  - 新增 M2M 中繼表的存取（透過 `dms.product` 已有的 ACL 即可，通常不需單獨設定）

## Phase 5：`dms_sale` 查價邏輯修改

- [ ] `addons/dms_sale/models/sale_order.py`：`_onchange_product_id` 改為優先讀 `product_id.effective_price`
  - fallback logic 保留（相容舊 `dms.vehicle.price`）
  - 移除 `dms.price.line` 的依賴呼叫

## Phase 6：Migration Script

- [ ] 建立 `addons/dms_product/migrations/16.0.2.0.0/` 目錄
- [ ] 建立 `addons/dms_product/migrations/16.0.2.0.0/__init__.py`（空）
- [ ] 建立 `addons/dms_product/migrations/16.0.2.0.0/post_migrate.py`
  - 讀取 `dms.price.line` → 取每個 product 最新有效版本的 cash_price/list_price → 寫入 `dms.product`
  - 讀取 `dms.installment.rule.binding` → 建立 M2M 關係記錄
  - 對每個 product 寫入一筆初始 `dms.product.price.log`（`note='由 dms.price.version 遷移'`）

## Phase 7：廢棄舊模型（保留空殼）

- [ ] `addons/dms_product/models/price_version.py`：加入廢棄警告 note，但不刪除
- [ ] `addons/dms_product/models/price_line.py`：同上
- [ ] `addons/dms_product/models/installment_rule_binding.py`：同上
- [ ] 移除以上三個 model 的 view XML 和 Action（或將 group 設為 `base.group_no_one`）

## Phase 8：測試

- [ ] 更新 `addons/dms_product/tests/` 中現有測試，移除對 `dms.price.line.get_effective_line()` 的依賴
- [ ] 新增測試：
  - [ ] `test_product_cash_price_log`：修改 cash_price 後 price_log 被自動寫入
  - [ ] `test_effective_price_with_promo`：promo_price > 0 時 effective_price = promo_price
  - [ ] `test_effective_price_no_promo`：promo_price = 0 時 effective_price = cash_price
  - [ ] `test_onchange_product_id_reads_direct_price`：onchange 直接讀 product.effective_price
  - [ ] `test_migration_price_line_to_product`：migration function 能正確轉移 price.line 資料

## Phase 9：收尾

- [ ] 執行 `docker compose restart odoo` 並確認服務正常
- [ ] 執行 `make smoke`
- [ ] 執行所有相關模組測試（`dms_product`, `dms_sale`）
- [ ] 更新 `docs/CHANGELOG.md`
- [ ] Commit & Push
