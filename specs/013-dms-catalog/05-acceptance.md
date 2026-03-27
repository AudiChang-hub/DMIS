# 013-dms-catalog — 驗收標準（05-acceptance）

## 功能驗收

### AC-1：模組安裝

- [ ] `dms_catalog` 可從 Odoo Apps 正常安裝，無 ParseError / ImportError
- [ ] 安裝後主選單出現「產品目錄」根選單
- [ ] 所有子選單可點選且正常載入視圖

### AC-2：產品型式管理

- [ ] 可新增 `dms.product.template` 紀錄（儷入車系、品牌、名稱、能源型式）
- [ ] 型式 Form 視圖**不顯示**圖片 avatar（OQ-4）
- [ ] 型式 List 視圖顯示 `series_id`（車系欄位）（OQ-1）
- [ ] Kanban 視圖正常顯示，配置欄位（`dms.kanban.product.config`）可控制顯示欄位（OQ-5）

### AC-3：SKU 管理

- [ ] 可在型式 Form 的 `sku_ids` 頁籤新增 SKU
- [ ] 重複 `(template_id, color_code, manufacture_year)` 組合時，系統拋出 Unique constraint 錯誤（非 500）
- [ ] SKU 可上傳專屬圖片

### AC-4：定價版本管理

- [ ] 可新增 `dms.price.version`，並在版本下新增 `dms.price.line`
- [ ] 每條 `dms.price.line` 可關聯一或多個 `dms.installment.rule`
- [ ] 重複 `(version_id, sku_id)` 時，系統拋出 Unique constraint 錯誤

### AC-5：分期規則管理

- [ ] 可新增 `dms.installment.rule`，含多條 `dms.installment.rule.line`（不同期數）
- [ ] 每條 rule.line 可掛載多個費用（`dms.installment.rule.fee`）
- [ ] 費用類型下拉選單顯示 `dms.fee.type` 主檔資料

### AC-6：費用類型主檔

- [ ] 安裝後預載「開辦費（OPEN）」與「設定費（SETUP）」
- [ ] 管理員可新增自訂費用類型

### AC-7：保留功能

- [ ] `dms.accessory` 視圖正常（List / Form）
- [ ] `dms.ev.fee.schedule` 視圖正常，電車限定 domain 有效
- [ ] `dms.commission.rule` 視圖正常

### AC-8：權限控制

- [ ] `catalog_manager` 群組可執行完整 CRUD
- [ ] `catalog_user` 群組僅可讀取型式、SKU、定價
- [ ] 未授權使用者無法存取任何 `dms.catalog.*` 模型

### AC-9：向下相容（Beta 前提）

- [ ] `dms_sale` 已安裝時，安裝 `dms_catalog` 不導致 `dms_sale` 拋出 missing dependency 錯誤
- [ ] 現有 `dms.product` 資料不因安裝 `dms_catalog` 而遺失

## 驗證指令

```bash
# 啟動環境
make up

# 確認容器狀態
docker compose ps

# 基本煙測
make smoke

# 安裝模組（於 Odoo shell 或 Admin UI）
# 或使用 RPC 安裝：
# python3 scripts/rpc_smoke.py
```

## 非功能驗收

- [ ] 所有視圖無 XML ParseError
- [ ] Server log 無 AccessError（info/debug 以外等級均無 ERROR）
- [ ] `make smoke` 全部 assertion 通過

### AC-10：非迄回測試（OQ-2 相否的驗證）

- [ ] 安裝 `dms_catalog` 後，`dms_sale` 功能正常，無 ERROR log
- [ ] 安裝 `dms_catalog` 後，`dms_visit` 功能正常，無 ERROR log
- [ ] `make smoke` 包含 `dms_sale` / `dms_visit` 的測試案例通過

### AC-11：Deprecated 模組標記（OQ-7 驗收）

- [ ] `addons/dms_product/__manifest__.py` 的 `description` 包含 `⚠️ DEPRECATED` 文字
- [ ] `addons/dms_pricelist/__manifest__.py` 的 `description` 包含 `⚠️ DEPRECATED` 文字
- [ ] 兩模組仍可安裝（頭小模組只有標記，未刺除）
