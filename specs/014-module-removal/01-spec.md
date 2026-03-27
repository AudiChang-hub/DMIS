# 規格（01-spec）— 014-module-removal

## 一、現況依賴分析

### 被移除模組提供的模型

#### `dms_product` 提供
| 模型 | 被引用方 | 用途 |
|---|---|---|
| `dms.product` | `dms_sale`, `dms_visit`, `dms_pricelist` | 車款主檔 |
| `dms.product.color` | `dms_sale` | 車款顏色 |
| `dms.kanban.product.config` | 僅自用 | Kanban 欄位顯示設定 |

#### `dms_pricelist` 提供
| 模型 | 被引用方 | 用途 |
|---|---|---|
| `dms.accessory` | `dms_sale` | 精品（訂單精品明細） |
| `dms.vehicle.price` | `dms_sale` | 車款售價（自動帶入現金售價） |
| `dms.installment.plan` | `dms_pricelist` 自用 | 分期方案 |
| `dms.ev.fee.schedule` | `dms_sale` | 電車牌險費率 |
| `dms.commission.rule` | `dms_sale` | 傭金規則 |
| `dms.accessory.price` | 僅自用 | 精品價格記錄 |

#### `dms_catalog` 提供
| 模型 | 被引用方 |
|---|---|
| `dms.catalog.product.template` | 無其他模組使用 |
| `dms.catalog.product.sku` | 無其他模組使用 |
| `dms.catalog.price.version` | 無其他模組使用 |
| `dms.catalog.installment.rule` | 無其他模組使用 |
| `dms.catalog.accessory` | 無其他模組使用 |
| `dms.catalog.commission.rule` | 無其他模組使用 |
| `dms.catalog.ev.fee.schedule` | 無其他模組使用 |
| `dms.catalog.fee.type` | 無其他模組使用 |
| `dms.kanban.catalog.config` | 無其他模組使用 |

---

## 二、目標狀態（移除後）

### 移除後存活的模型（遷移至 `dms_sale`）

下列模型從被刪除模組遷移進 `dms_sale`，原有技術名稱與欄位**完全不變**（零資料遷移問題）：

| 原所在模組 | 模型名稱 | 遷移目的地 |
|---|---|---|
| `dms_product` | `dms.product` | `dms_sale/models/product.py` |
| `dms_product` | `dms.product.color` | `dms_sale/models/product_color.py` |
| `dms_product` | `dms.kanban.product.config` | `dms_sale/models/kanban_config.py` |
| `dms_pricelist` | `dms.accessory` | `dms_sale/models/accessory.py` |
| `dms_pricelist` | `dms.vehicle.price` | `dms_sale/models/vehicle_price.py` |
| `dms_pricelist` | `dms.installment.plan` | `dms_sale/models/installment_plan.py` |
| `dms_pricelist` | `dms.ev.fee.schedule` | `dms_sale/models/ev_fee_schedule.py` |
| `dms_pricelist` | `dms.commission.rule` | `dms_sale/models/commission_rule.py` |
| `dms_pricelist` | `dms.accessory.price` | `dms_sale/models/accessory_price.py` |

### 直接刪除的模型（僅 dms_catalog 使用）
全部 `dms.catalog.*` 模型隨 `dms_catalog/` 資料夾一併刪除。

---

## 三、模組依賴變更

### `dms_sale`（修改）
- **移除** depends: `dms_product`, `dms_pricelist`
- **保留** depends: `dms_core`, `dms_customer`
- **新增** models: 全部遷移進來的模型檔案
- **新增** views: 產品管理、價目管理視圖（從 dms_product/dms_pricelist 搬入）
- **新增** security: 從兩個模組合併 ir.model.access.csv
- **新增** static assets: 從 dms_product 搬入 CSS/JS

### `dms_visit`（修改）
- **移除** depends: `dms_product`
- **新增** depends: `dms_sale`
- `visit_item.product_id` 仍指向 `dms.product`（此模型已移至 dms_sale，無需修改欄位定義）

### `dms_pricelist`（刪除）
完整資料夾移除。

### `dms_product`（刪除）
完整資料夾移除。

### `dms_catalog`（刪除）
完整資料夾移除。

---

## 四、視圖整合規劃

移入 `dms_sale` 的產品/價目視圖，整合至銷售模組的選單：

```
銷售管理 (dms_sale)
├── 訂單管理
│   └── 銷售訂單
├── 產品資料
│   ├── 車款管理
│   └── 顏色管理
├── 價目資料
│   ├── 車款售價
│   ├── 電車牌險費率
│   ├── 精品管理
│   └── 傭金規則
```

---

## 五、安全性（ACL）

- 現有 `dms_product` 與 `dms_pricelist` 的 ACL 記錄整併至 `dms_sale/security/ir.model.access.csv`
- 不新增也不移除任何群組
- 現有使用者的操作權限不受影響

---

## 六、Static Assets 遷移

| 原路徑 | 新路徑 |
|---|---|
| `dms_product/static/src/css/product_kanban.css` | `dms_sale/static/src/css/product_kanban.css` |
| `dms_product/static/src/js/dms_product_column_limit.js` | `dms_sale/static/src/js/dms_product_column_limit.js` |
| `dms_product/static/src/js/product_image_lightbox.js` | `dms_sale/static/src/js/product_image_lightbox.js` |

---

## 七、不受影響的模組確認

| 模組 | 狀態 | 依賴變更 |
|---|---|---|
| `dms_core` | ✅ 不動 | 無 |
| `dms_customer` | ✅ 不動 | 無 |
| `dms_finance` | ✅ 不動 | 無 |
| `dms_report` | ✅ 不動 | 無 |
| `dms_report_rule` | ✅ 不動 | 無 |
| `dms_report_virtual` | ✅ 不動 | 無 |
| `user_management` | ✅ 不動 | 無 |
| `dms_sale` | 🔧 修改 | 移除 dms_product/dms_pricelist 依賴，接收模型 |
| `dms_visit` | 🔧 修改 | 移除 dms_product 依賴，改依賴 dms_sale |

---

## 八、移除後的資料庫收尾

### 8.1 清理 `dms_catalog` 殘留 metadata

當 `dms_catalog` 已從程式碼移除、資料庫中的模組狀態為 `uninstalled` 時，若仍殘留其 `ir.model` / `ir.model.data` / `ir.model.fields` 等註冊資料，Odoo 在 registry 載入時會出現「Model ... cannot be loaded」警告。

本輪需清理下列 **catalog-only** 模型的殘留註冊資料：

- `dms.product.template`
- `dms.product.sku`
- `dms.price.version`
- `dms.price.line`
- `dms.installment.rule`
- `dms.installment.rule.line`
- `dms.fee.type`
- `dms.installment.rule.fee`

### 8.2 不刪除現行 `dms_sale` 仍使用的模型

下列模型雖曾在 `dms_catalog` 出現過，但目前已由 `dms_sale` 接手，**不得**因清理腳本而刪除：

- `dms.accessory`
- `dms.commission.rule`
- `dms.ev.fee.schedule`
- `dms.kanban.product.config`

---

## 九、文件同步要求

本輪完成後，下列文件必須同步更新為目前架構：

- `README.md`
- `SETUP.md`
- `docs/USER_MANUAL.md`
- `docs/erd.md`
- `specs/000-roadmap/01-module-map.md`
- `specs/000-roadmap/02-master-checklist.md`
- `specs/006-dms-sale/**`
- `specs/011-dms-visit/**`

原 `013-dms-catalog` 規格需標註為「已被 014 取代，不再作為實作依據」。
