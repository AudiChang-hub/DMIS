# 實作計畫（03-plan）— 014-module-removal

## 執行順序（重要：依序執行，每步驟確認通過再繼續）

---

### Phase 0：前置確認

1. **確認 dms_report / dms_report_virtual / dms_finance 未直接引用被移除模型**
   - 掃描所有 Python 檔案是否有 `dms.product`, `dms.accessory`, `dms.vehicle.price`, `dms.commission.rule`, `dms.ev.fee.schedule` 相關字串

2. **確認資料庫目前狀態**（若環境已運行）
   - `docker compose ps` 確認容器狀態
   - 先備份：`docker compose exec db pg_dump -U odoo dmis_dev > backup_before_removal.sql`

---

### Phase 1：dms_sale 接收模型與視圖

**目標**：在刪除 dms_product / dms_pricelist 之前，先將它們的模型與視圖搬入 dms_sale。

#### 1-A：建立模型檔案（複製後清理）

在 `addons/dms_sale/models/` 新增以下檔案（內容從來源模組複製）：

| 新檔案 | 來源 |
|---|---|
| `product.py` | `dms_product/models/product.py` |
| `product_color.py` | `dms_product/models/product_color.py` |
| `kanban_config.py` | `dms_product/models/kanban_config.py` |
| `accessory.py` | `dms_pricelist/models/accessory.py` |
| `accessory_price.py` | `dms_pricelist/models/accessory_price.py` |
| `vehicle_price.py` | `dms_pricelist/models/vehicle_price.py` |
| `installment_plan.py` | `dms_pricelist/models/installment_plan.py` |
| `ev_fee_schedule.py` | `dms_pricelist/models/fee_schedule.py` |
| `commission_rule.py` | `dms_pricelist/models/commission_rule.py` |

#### 1-B：更新 `dms_sale/models/__init__.py`

新增所有遷移模型的 import。

#### 1-C：搬入視圖檔案

在 `addons/dms_sale/views/` 新增以下視圖（來自 dms_product / dms_pricelist）：

| 新視圖檔案 | 來源 |
|---|---|
| `product_views.xml` | `dms_product/views/product_views.xml` |
| `product_kanban_config_views.xml` | `dms_product/views/kanban_config_views.xml` |
| `accessory_views.xml` | `dms_pricelist/views/accessory_views.xml` |
| `vehicle_price_views.xml` | `dms_pricelist/views/vehicle_price_views.xml` |
| `fee_schedule_views.xml` | `dms_pricelist/views/fee_schedule_views.xml` |
| `commission_rule_views.xml` | `dms_pricelist/views/commission_rule_views.xml` |

#### 1-D：建立新選單（整合至 dms_sale 選單結構）

新增 `addons/dms_sale/views/product_pricelist_menu.xml`，含：
- 「產品資料 / 車款管理」
- 「產品資料 / 顏色管理」
- 「價目資料 / 車款售價」
- 「價目資料 / 電車牌險費率」
- 「價目資料 / 精品管理」
- 「價目資料 / 傭金規則」

#### 1-E：搬入 Static Assets

複製至 `addons/dms_sale/static/src/`：
- `css/product_kanban.css`（從 dms_product）
- `js/dms_product_column_limit.js`（從 dms_product）
- `js/product_image_lightbox.js`（從 dms_product）

#### 1-F：合併 ACL

將 `dms_product/security/ir.model.access.csv` 與 `dms_pricelist/security/ir.model.access.csv` 的記錄追加至 `dms_sale/security/ir.model.access.csv`。

#### 1-G：更新 `dms_sale/__manifest__.py`

- `depends`：移除 `dms_product`, `dms_pricelist`（這兩個模組的模型已內嵌進來）
- `data`：新增所有遷移視圖 XML 檔案
- `assets`：新增 CSS/JS 路徑

---

### Phase 2：更新 dms_visit 依賴

**目標**：將 `dms_visit.__manifest__.py` 的 `depends` 中 `dms_product` 換成 `dms_sale`。

- 修改 `addons/dms_visit/__manifest__.py`：`'depends': ['dms_core', 'dms_sale']`
- 不修改 `visit_item.py`（`dms.product` 的 Many2one 仍有效，因模型已遷移）

---

### Phase 3：刪除三個模組資料夾

**執行前確認**：Phase 1 與 Phase 2 已完成，容器可正常啟動。

1. 刪除 `addons/dms_catalog/`
2. 刪除 `addons/dms_pricelist/`
3. 刪除 `addons/dms_product/`

---

### Phase 4：容器重啟與模組升級

```bash
# 重啟容器讓 Python registry 重新載入
docker compose restart odoo

# 升級 dms_sale（接收新模型）
docker compose exec odoo odoo -d dmis_dev -u dms_sale --stop-after-init

# 升級 dms_visit（更新依賴）
docker compose exec odoo odoo -d dmis_dev -u dms_visit --stop-after-init

# 啟動並驗證
docker compose up -d odoo
make smoke
```

---

### Phase 5：測試驗收

- 執行 `make smoke`
- 確認 dms_core 車行管理完整可用
- 確認 user_management 使用者管理完整可用
- 確認 dms_sale 銷售訂單（含產品選擇、精品明細）可用
- 確認 dms_visit 拜訪紀錄（含送出物品）可用
- 執行既有單元測試

---

### Phase 6：資料庫 metadata 與文件同步

1. 執行維運腳本，清理 `dms_catalog` 的 catalog-only 殘留 metadata，以及 `dms_product` / `dms_pricelist` / `dms_catalog` 的舊 menu / action / view / ACL xmlid 與 `ir_module_module` 模組登記
2. 再次執行：

```bash
docker compose exec odoo odoo -d dmis_dev -u dms_sale,dms_visit --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo --stop-after-init
```

確認不再出現 `dms.product.template`、`dms.product.sku`、`dms.price.version`、`dms.price.line`、`dms.installment.rule`、`dms.installment.rule.line`、`dms.fee.type`、`dms.installment.rule.fee` 的 registry warning，且資料庫不再殘留「產品管理 / 價目管理 / 產品目錄」舊頂層選單。

3. 同步更新下列文件：
   - `README.md`
   - `SETUP.md`
   - `docs/USER_MANUAL.md`
   - `docs/erd.md`
   - `specs/000-roadmap/01-module-map.md`
   - `specs/000-roadmap/02-master-checklist.md`
   - `specs/006-dms-sale/**`
   - `specs/011-dms-visit/**`
   - 刪除 `specs/013-dms-catalog/` 整個目錄

---

## 回滾方案

若任何 Phase 失敗：
1. 從備份還原資料庫：`psql -U odoo dmis_dev < backup_before_removal.sql`
2. 從 Git 還原程式碼：`git checkout -- addons/`
3. 重啟容器後驗證
