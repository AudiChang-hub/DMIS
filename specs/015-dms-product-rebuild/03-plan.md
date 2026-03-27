# 03 — Plan：新一代產品管理模組重建（015-dms-product-rebuild）

## 1. 影響分析

### 1.1 新增

- `addons/dms_product/**`
- `specs/015-dms-product-rebuild/**`

### 1.2 最小必要修改

- `addons/dms_sale/models/sale_order.py`
- `addons/dms_visit/models/visit_item.py`
- `addons/dms_visit/views/visit_views.xml`
- `addons/dms_visit/tests/test_visit.py`
- `scripts/cleanup_dms_catalog_metadata.py`
- `README.md`
- `SETUP.md`
- `docs/USER_MANUAL.md`
- `docs/erd.md`
 - `docs/CHANGELOG.md`
- `specs/000-roadmap/01-module-map.md`
- `specs/000-roadmap/02-master-checklist.md`
- `specs/006-dms-sale/**`
- `specs/011-dms-visit/**`
- `specs/014-module-removal/**`（改為歷史脈絡說明）

### 1.3 明確不修改

- `addons/dms_core/**`
- Odoo 核心

---

## 2. 新模組命名與角色

### 2.1 模組名稱

- 技術名稱：`dms_product`
- 顯示名稱：`DMS 產品管理`

### 2.2 模組角色

- 提供新的產品主資料與產品管理入口
- 提供 canonical 價格版本 / 規則 / 費用結構
- 提供對既有 `dms_sale` / `dms_visit` 的相容橋接

---

## 3. 模型設計計畫

### 3.1 新增 canonical 模型

- `dms.product.template`
- `dms.price.version`
- `dms.price.line`
- `dms.installment.rule`
- `dms.installment.rule.line`
- `dms.fee.type`
- `dms.installment.rule.fee`
- `dms.installment.rule.binding`

### 3.2 擴充相容模型

以 `_inherit = 'dms.product'` 擴充：

- `template_id`
- `internal_code`
- `production_year`
- 相容同步方法 / helper 方法
- SKU 代碼生成規則改為「型號 + 出廠年份」，若衝突則補序號尾碼
- `production_year` 改為文字欄位，並在相容同步時自動去除逗點格式

---

## 4. 視圖設計計畫

### 4.1 新模組選單

新增頂層 `產品管理` App，底下提供：

- 產品模板
- 產品項 / SKU
- 價目版本
- 價格基準
- 分期規則模板
- 費用類型
- 規則掛接

### 4.2 UI 原則

- List-first
- 主要使用 tree + form + search
- 產品表單不以圖片作主視覺
- 必要時保留 legacy 圖片欄位，但放在次要分頁

---

## 5. 相容層策略

### 5.1 `dms.product` 相容策略

- 保留技術模型名稱 `dms.product`
- 由新模組擴充成 SKU 層
- 確保 `dms_visit` 與 `dms_finance` 既有測試仍可建立產品

### 5.2 `dms_sale` 相容策略

- 新價格結構存在時，優先以 `dms.price.line` 生效邏輯查價
- 若查無資料，fallback 舊 `dms.vehicle.price`
- 不改動既有訂單欄位結構

### 5.3 `dms_visit` 脫鉤策略

- 將 `dms.visit.item` 從 Many2one → `dms.product` 的強耦合，調整為可獨立輸入送出物品名稱
- 視資料相容需求，保留 `product_id` 作歷史欄位，但改為非必填
- 同步調整 view、測試與驗收條件
- 本輪不把 `dms_visit` 接到新產品 canonical 模型，避免過早耦合

### 5.3 舊入口策略

候選方案：

1. 隱藏 `dms_sale` 舊產品 / 價目選單，改由 `dms_product` 作唯一入口
2. 保留舊 action 作相容 fallback，但 UI 導向新模組

建議：

- 一般使用者只看新 `dms_product` 入口
- 必要相容 action 保留，但不作正式使用入口

---

## 6. migration 步驟

1. 先清理重建 `dms_product` 前殘留的孤兒 `base.module_dms_product` XML ID
2. 安裝新 `dms_product` 模組
2. 建立 `post_init_hook` 或等價 migration 程式：
   - 建 template
   - 回填 `dms.product.template_id`
   - 將舊式自動生成碼更新為「型號 + 出廠年份」格式
   - 回填 `production_year`
   - 將 `production_year` 正規化為純年份文字，例如 `2,026` → `2026`
3. 若 legacy price / installment 有資料，再搬到 `dms.price.version` / `dms.price.line` / `dms.installment.rule*`
4. 調整 `dms_visit`，讓送出物品先脫鉤為獨立輸入
5. 升級 `dms_sale`，使查價邏輯支援新 canonical 模型
6. 驗證既有銷售 / 拜訪 / 財務流程

---

## 7. 測試策略

### 7.1 新模組測試

至少新增 Odoo 測試覆蓋：

- 模板建立
- SKU 建立
- 同模板不同顏色 / 出廠年份
- 價目版本與價格基準
- 生效日查價
- 分期規則模板、明細、費用
- SKU × 價目版本 × 規則掛接
- migration / compatibility

### 7.2 回歸測試

至少驗證：

- `dms_core`
- `dms_visit`
- `dms_finance`
- `user_management`
- `dms_sale` 建單與查價

---

## 8. 回歸驗證策略

指令至少包含：

```bash
make up
docker compose ps
python3 scripts/cleanup_dms_catalog_metadata.py --database dmis_dev --user odoo
docker exec dmis-odoo-1 odoo --stop-after-init -d dmis_dev -i dms_product --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo
docker exec dmis-odoo-1 odoo --http-port=8070 --test-enable --stop-after-init -d dmis_dev -u dms_core,user_management,dms_sale,dms_visit,dms_product --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo
make smoke
```

> 若環境沒有 `make`，需以 `docker compose up -d` 與 `bash scripts/smoke_odoo.sh` 執行等效流程。
>
> 因本輪會修改 `addons/**` Python / XML，完成後必須自動 `docker compose restart odoo` 再驗證。

---

## 9. 回滾風險與應對方式

### 9.1 主要風險

- migration 對 legacy 產品欄位映射不正確
- 新價格查詢邏輯影響 `dms_sale` 建單
- 菜單切換後造成使用者找不到既有入口

### 9.2 應對

- 所有 migration 以可重複執行與不刪除舊資料為前提
- 查價邏輯保留 legacy fallback
- 以 spec 與使用手冊明確標示新入口
- 升級前後執行 smoke 與回歸測試
