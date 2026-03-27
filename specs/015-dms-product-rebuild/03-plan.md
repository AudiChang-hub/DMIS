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
- `color_ids`（One2many → `dms.product.color`，作為顏色清單）
- 相容同步方法 / helper 方法
- 產品項代碼生成規則維持「型號 + 出廠年份」
- `production_year` 改為文字欄位，並在相容同步時自動去除逗點格式
- 既有 `color` / `color_code` 欄位轉為 legacy 相容欄位，不再作為產品項拆分主依據

---

## 4. 視圖設計計畫

### 4.1 新模組選單

新增頂層 `產品管理` App，底下提供：

- 產品模板
- 價目版本
- 價格基準
- 分期規則模板
- 費用類型
- 規則掛接

### 4.2 UI 原則

- List-first
- 主要使用 tree + form + search
- 產品項僅在產品模板表單的頁籤中以 inline tree 維護，不提供獨立 menu
- 產品顏色在產品模板表單的獨立頁籤中維護，欄位至少包含 `產品項 / 顏色名稱 / 啟用`
- 產品項頁籤以 `active_test=False` 顯示停用資料，並保留 `active` 勾選供重新啟用
- 產品項頁籤加入列級「複製」按鈕，直接複製同模板下的年份產品項，讓使用者只需微調年份等差異欄位
- `dms.product.copy()` 需顯式清空 `internal_code` 預設值，並在複製完成後重新生成唯一代碼，避免 inline tree 複製時沿用舊碼
- 列級複製完成後回傳 `ir.actions.client` 的 `reload`，避免以 `act_window` 重開同一張模板表單造成 breadcrumb 疊加
- 產品項頁籤中的刪除動作需真正刪除產品項，因此 `dms.product.template_id` 需改為 `ondelete='cascade'`，避免 Odoo 只做解除關聯而導致 FK 錯誤
- `dms.product.template.sku_ids` 關聯本身也需帶 `active_test=False`，避免頁籤與計數不一致
- `sku_count` 改為僅統計啟用中的產品項，符合使用者對模板主列表數量的直覺
- 補一個綁定到產品模板的 server action「複製」，避免 form 初始 edit 模式下看不到內建 Duplicate，並於模型 `copy()` 時一併複製產品項
- 補一個綁定到價目版本的 server action「複製」，避免 form 初始 edit 模式下看不到內建 Duplicate，並於模型 `copy()` 時一併複製價格基準
- `dms.price.version.copy()` 需自動重生不重複版本名稱，並將複製出的版本狀態重設為 `draft`
- `dms.product.name_get()` 與 `_name_search()` 需以 `internal_code / 出廠年份 / 模板` 為主，不再把顏色作為產品項識別主鍵
- 價目版本需補一個批次加入產品項精靈，支援多選產品項後一次建立多筆價格基準列
- 批次加入精靈需提供共用 `cash_price / list_price` 欄位，建立時直接帶入每筆新增價格列
- 產品表單不以圖片作主視覺
- 必要時保留 legacy 圖片欄位，但放在次要分頁

---

## 5. 相容層策略

### 5.1 `dms.product` 相容策略

- 保留技術模型名稱 `dms.product`
- 由新模組擴充成產品項層（模板 + 出廠年份）
- 確保 `dms_visit` 與 `dms_finance` 既有測試仍可建立產品

### 5.2 `dms.product.color` 相容策略

- 延用既有技術模型名稱 `dms.product.color`
- 作為銷售顏色下拉與產品管理顏色清單的正式模型
- 舊資料若原本散落在 `dms.product.color` / `dms.product.color_code` 或被拆成多筆產品項，需統一收斂到這個模型
### 5.3 `dms_sale` 相容策略

- 新價格結構存在時，優先以 `dms.price.line` 生效邏輯查價
- 若查無資料，fallback 舊 `dms.vehicle.price`
- 不改動既有訂單欄位結構
- `sale_order.color_id` 持續使用 `dms.product.color`
- 顏色 domain 需跟著收斂後的產品項運作
### 5.4 `dms_visit` 脫鉤策略

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
   - 將同模板同年份但不同顏色的多筆 `dms.product` 收斂為單一 canonical 產品項
   - 將各顏色轉寫為 `dms.product.color`
   - 將價格、規則、銷售等參照改掛回 canonical 產品項
3. 若 legacy price / installment 有資料，再搬到 `dms.price.version` / `dms.price.line` / `dms.installment.rule*`
4. 調整 `dms_visit`，讓送出物品先脫鉤為獨立輸入
5. 升級 `dms_sale`，使查價邏輯支援新 canonical 模型
6. 驗證既有銷售 / 拜訪 / 財務流程

---

## 7. 測試策略

### 7.1 新模組測試

至少新增 Odoo 測試覆蓋：

- 模板建立
- 產品項建立
- 同模板不同年份
- 同產品項可維護多筆顏色
- 價目版本與價格基準
- 生效日查價
- 分期規則模板、明細、費用
- 產品項 × 價目版本 × 規則掛接
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
