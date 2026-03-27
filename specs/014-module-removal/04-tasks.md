# 任務清單（04-tasks）— 014-module-removal

## Phase 0：前置確認

- [x] 掃描 `dms_report/**/*.py`, `dms_report_virtual/**/*.py`, `dms_finance/**/*.py` 是否有引用 `dms.product` / `dms.accessory` / `dms.vehicle.price` / `dms.ev.fee.schedule` / `dms.commission.rule`
- [ ] 確認 docker 容器狀態正常 (`docker compose ps`)
- [ ] 執行資料庫備份

---

## Phase 1-A：模型遷移

- [x] 新增 `addons/dms_sale/models/product.py`（來源：dms_product/models/product.py）
- [x] 新增 `addons/dms_sale/models/product_color.py`（來源：dms_product/models/product_color.py）
- [x] 新增 `addons/dms_sale/models/kanban_config.py`（來源：dms_product/models/kanban_config.py）
- [x] 新增 `addons/dms_sale/models/accessory.py`（來源：dms_pricelist/models/accessory.py）
- [x] 新增 `addons/dms_sale/models/accessory_price.py`（來源：dms_pricelist/models/accessory_price.py，內容已廢棄，跳過）
- [x] 新增 `addons/dms_sale/models/vehicle_price.py`（來源：dms_pricelist/models/vehicle_price.py）
- [x] 新增 `addons/dms_sale/models/installment_plan.py`（來源：dms_pricelist/models/installment_plan.py）
- [x] 新增 `addons/dms_sale/models/ev_fee_schedule.py`（來源：dms_pricelist/models/fee_schedule.py）
- [x] 新增 `addons/dms_sale/models/commission_rule.py`（來源：dms_pricelist/models/commission_rule.py）

## Phase 1-B：更新 __init__.py

- [x] 更新 `addons/dms_sale/models/__init__.py`，新增 9 個模型的 import

## Phase 1-C：視圖複製

- [x] 新增 `addons/dms_sale/views/product_views.xml`
- [x] 新增 `addons/dms_sale/views/product_kanban_config_views.xml`
- [x] 新增 `addons/dms_sale/views/accessory_views.xml`
- [x] 新增 `addons/dms_sale/views/vehicle_price_views.xml`
- [x] 新增 `addons/dms_sale/views/fee_schedule_views.xml`
- [x] 新增 `addons/dms_sale/views/commission_rule_views.xml`

## Phase 1-D：整合選單

- [x] 新增 `addons/dms_sale/views/product_pricelist_menu.xml`（含產品資料與價目資料子選單）

## Phase 1-E：Static Assets

- [x] 新增 `addons/dms_sale/static/src/css/product_kanban.css`（來源：dms_product）
- [x] 新增 `addons/dms_sale/static/src/js/dms_product_column_limit.js`（來源：dms_product）
- [x] 新增 `addons/dms_sale/static/src/js/product_image_lightbox.js`（來源：dms_product）

## Phase 1-F：合併 ACL

- [x] 將 `dms_product/security/ir.model.access.csv` 內容合併至 `dms_sale/security/ir.model.access.csv`
- [x] 將 `dms_pricelist/security/ir.model.access.csv` 內容合併至 `dms_sale/security/ir.model.access.csv`

## Phase 1-G：更新 dms_sale/__manifest__.py

- [x] `depends` 移除 `dms_product`, `dms_pricelist`
- [x] `data` 新增所有遷移視圖的 XML 路徑
- [x] `assets` 新增 CSS/JS 路徑

---

## Phase 2：更新 dms_visit 依賴

- [x] 修改 `addons/dms_visit/__manifest__.py`：`depends` 中 `dms_product` 替換為 `dms_sale`

---

## Phase 3：刪除三個模組

- [x] 刪除 `addons/dms_catalog/`（整個資料夾）
- [x] 刪除 `addons/dms_pricelist/`（整個資料夾）
- [x] 刪除 `addons/dms_product/`（整個資料夾）

---

## Phase 4：升級驗證

- [ ] `docker compose restart odoo`
- [x] `docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init`
- [ ] `docker compose up -d odoo`
- [x] `bash scripts/smoke_odoo.sh` / `make smoke` 通過

---

## Phase 5：資料庫收尾

- [x] 新增維運腳本以清理 `dms_catalog` 的 catalog-only 殘留 metadata 與模組登記
- [x] 執行清理腳本
- [x] 刪除 `ir_module_module` 中的 `dms_catalog` 模組登記
- [x] 重新執行 `docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init`
- [x] 確認不再出現 `dms.product.template` / `dms.product.sku` / `dms.price.version` / `dms.price.line` / `dms.installment.rule*` / `dms.fee.type` 的 registry warning

---

## Phase 6：文件同步

- [x] 更新 `README.md`
- [x] 更新 `SETUP.md`
- [x] 更新 `docs/USER_MANUAL.md`
- [x] 更新 `docs/erd.md`
- [x] 更新 `specs/000-roadmap/01-module-map.md`
- [x] 更新 `specs/000-roadmap/02-master-checklist.md`
- [x] 更新 `specs/006-dms-sale/00-charter.md`
- [x] 更新 `specs/006-dms-sale/01-spec.md`
- [x] 更新 `specs/006-dms-sale/04-tasks.md`
- [x] 更新 `specs/011-dms-visit/00-charter.md`
- [x] 更新 `specs/011-dms-visit/01-spec.md`
- [x] 刪除 `specs/013-dms-catalog/` 整個目錄

---

## Phase 7：功能驗收

- [ ] 車行管理（dms_core）— 建立、編輯、搜尋車行
- [ ] 使用者管理（user_management）— 使用者建立與角色指派
- [ ] 銷售訂單（dms_sale）— 建立訂單、選擇車款、新增精品明細
- [ ] 拜訪紀錄（dms_visit）— 建立拜訪、選擇送出物品
- [ ] 產品管理（現在在 dms_sale 下）— 建立新車款
- [ ] 價目管理（現在在 dms_sale 下）— 查看車款售價
