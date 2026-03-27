# 02 — Clarify：新一代產品管理模組重建（015-dms-product-rebuild）

## 1. 目前 repo 真實狀態

### 1.1 已讀規範與 spec

已完整閱讀並納入本輪約束：

- `docs/CONSTITUTION.md`
- `.github/copilot-instructions.md`
- `README.md`
- `.github/prompts/dms-specify.prompt.md`
- `.github/prompts/dms-feature.prompt.md`
- `specs/001-dms-core/**`
- `specs/002-store-management/**`
- `specs/003-dms-product/**`（歷史）
- `specs/005-dms-pricelist/**`（歷史）
- `specs/006-dms-sale/**`
- `specs/011-dms-visit/**`
- `specs/012-user-management/01-spec.md`
- `specs/014-module-removal/**`

### 1.2 目前 branch / 環境

- 目前 branch：`feat/015-dms-product-rebuild`
- 基底 commit：`d36e651`
- `docker compose ps` 顯示 `db` / `odoo` / `cloudflared` 皆在運行

### 1.3 目前已安裝模組

資料庫 `dmis_dev` 目前已安裝：

- `dms_core`
- `dms_customer`
- `dms_sale`
- `dms_product`
- `dms_visit`
- `dms_finance`
- `dms_report`
- `dms_report_rule`
- `dms_report_virtual`
- `user_management`

舊模組 `dms_pricelist` / `dms_catalog` 目前未安裝，舊頂層「價目管理 / 產品目錄」選單已清除；新的 `dms_product` 已安裝並接手正式「產品管理」App 入口。

### 1.4 現行產品相關模型實況

目前產品領域已分成兩層：

canonical / 正式入口由 `dms_product` 提供：

- `dms.product.template`
- `dms.price.version`
- `dms.price.line`
- `dms.installment.rule`
- `dms.installment.rule.line`
- `dms.fee.type`
- `dms.installment.rule.fee`
- `dms.installment.rule.binding`

legacy 相容與交易沿用部分仍由 `dms_sale` / `dms_product` 共同承接：

- `dms.product`
- `dms.product.color`
- `dms.vehicle.price`
- `dms.installment.plan`
- `dms.accessory`
- `dms.commission.rule`
- `dms.ev.fee.schedule`

其中：

- `dms.product` 已收斂為 SKU 相容模型，新增 `template_id / internal_code / production_year`
- `dms_product` 已提供新的頂層產品管理選單與 canonical 視圖
- `dms_sale` 沒有自己的測試檔，因此查價回歸需由 `dms_product` 測試覆蓋
- `dms_visit` 已先改成文字式送出物品輸入，降低對 `dms.product` 的耦合

### 1.5 目前資料量

實際資料表筆數：

- `dms_product`：2
- `dms_vehicle_price`：0
- `dms_installment_plan`：0
- `dms_commission_rule`：0
- `dms_ev_fee_schedule`：0
- `dms_accessory`：0
- `dms_visit`：0
- `dms_sale_order`：0

現有兩筆產品資料：

1. `SUI / UQ125DA / 2026 / 鈦灰 / oil / 台鈴 Suzuki`
2. `Saluto / UC125DA / 2026 / 蒙地拿紅 / oil / 台鈴 Suzuki`

---

## 2. 被刪除的舊模組與目前風險

### 2.1 舊模組已移除，但產品領域尚未真正重建

`014` 完成的是「先收掉舊模組，維持現有流程不壞」，不是產品領域的最終設計。因此目前風險是：

- `dms_sale` 同時背負交易與產品主資料，bounded context 不清楚
- 產品結構仍是舊扁平模型，無法支撐你這次要求的模板 / SKU / 價目版本 / 分期規則 / 費用規則
- 現行產品 UI 仍有圖片導向痕跡，不符合本輪以內部查找效率為優先的要求

### 2.2 舊依賴不能直接切斷

目前直接引用 `dms.product` 的地方至少包含：

- `dms_sale.models.sale_order`
- `dms_visit.models.visit_item`
- `dms_finance` 測試
- `dms_visit` 測試

因此本輪若直接把 `dms.product` 移除或硬改型，會立刻影響：

- 銷售訂單建單
- 拜訪送出物品
- 財務測試
- 拜訪測試

結論：

- `dms_sale` / `dms_finance` 本輪必須保留 `dms.product` 相容層
- `dms_visit` 則可採分階段脫鉤，不再作為 `dms.product` migration 的阻塞點

---

## 3. 新產品模組的資料分層決策

### D1：新模組名稱採 `dms_product`

決策：本輪重新建立 `addons/dms_product/`，作為新一代產品管理模組。

理由：

- 命名最直接，符合 repo 既有風格
- 對使用者來說語意清楚，便於成為未來唯一入口
- 雖然舊版 `dms_product` 已在 `014` 移除，但本輪是新一代重建，不是回滾舊模組

### D2：本輪先讓 `dms.product` 承接 SKU 層

決策：不在本輪引入新的 `dms.product.sku` 以切斷既有流程，而是讓既有 `dms.product` 經過欄位擴充後作為 SKU 層。

理由：

- `dms_sale` / `dms_visit` / `dms_finance` 已直接依賴 `dms.product`
- 這樣可在不重寫現有交易流程下，逐步把主資料收斂到正確結構
- 新結構仍可明確擁有模板層（`dms.product.template`）與價目 / 規則 / 費用層

影響：

- `dms.product` 將成為「可販售產品項 / SKU」的相容模型
- 新模組需提供 migration，把舊 `dms.product` 補齊 `template_id`、`internal_code`、`production_year`
- `internal_code` 的自動生成規則需兼顧可讀性，因此本輪改採「型號 + 出廠年份」為主格式；若同型號同年份有多筆 SKU，再補序號尾碼維持唯一性
- `production_year` 需改為文字欄位，避免 Odoo 將年份格式化為 `2,026`

### D3：價格與規則走新模型，`dms_sale` 只做最小必要 lookup 調整

決策：建立新的 `dms.price.version`、`dms.price.line`、`dms.installment.rule*`、`dms.fee.type`，並讓 `dms_sale` 在查價時優先讀新結構，若無資料再 fallback 舊 `dms.vehicle.price`。

理由：

- 可保留既有銷售流程
- 同時讓新產品模組成為未來唯一正確資料來源
- 避免本輪重寫整個 `dms_sale`

### D4：圖片欄位保留但退出主畫面核心

決策：若 `image_1920` 因既有 `dms.product` 結構仍存在，將保留為相容欄位，但新產品模組主畫面與主流程不以圖片為核心。

### D5：`dms_visit` 送出物品先與產品主檔脫鉤

決策：拜訪清單中的送出物品，本輪先不與 `dms.product` 綁定，待新產品管理模組完成後再接回。

理由：

- 這是目前最容易卡住產品重建的跨模組依賴之一
- `dms_visit` 真正的業務需求是「記錄送出什麼」，本輪可先用較鬆耦合的方式維持可用
- 先斷開可降低新產品結構重建時對 `dms_visit` 的牽制

執行原則：

- `dms.visit.item` 至少需保留 `item_name`、`quantity`、`note`
- 若保留 `product_id` 作歷史相容，該欄位應改為非必填，且不作主要輸入
- 後續待新產品模組穩定後，再以新 spec 把 `dms_visit` 接回 `dms.product`（SKU）

---

## 4. 舊依賴如何相容

### 4.1 銷售管理

- `dms.sale.order.product_id` 維持 Many2one → `dms.product`
- 新增價格查詢 helper，優先讀取 `dms.price.line` 的生效版本
- 若尚無新價格資料，fallback 讀取舊 `dms.vehicle.price`

### 4.2 拜訪管理

- 本輪 `dms.visit.item` 先與 `dms.product` 脫鉤
- 送出物品改為可獨立輸入，不讓 `dms_visit` 持續卡住產品 migration
- 後續再用新 spec 接回 canonical SKU

### 4.3 財務與報表

- `dms_finance` 不直接依賴新 canonical 模型，僅依銷售單
- 本輪不重寫 `dms_report*`

---

## 5. 不影響車行管理與既有使用者的保護原則

### 5.1 車行管理保護原則

- 不修改 `addons/dms_core/**`
- 不改 `dms_core` 任何 ACL / record rule / menu / view
- 車行、品牌、拜訪清單、拜訪行事曆必須做回歸驗證

### 5.2 既有使用者保護原則

- 舊產品資料不得失聯
- 銷售單與拜訪的產品選取不得失效
- 不可因建立新模組導致現有模組安裝 / 升級 / 開啟畫面失敗
- 若需要改變使用入口，需提供新的正式入口並留下最小相容處理

---

## 6. migration / 相容策略

### 6.1 產品 migration

對既有 `dms.product`：

- 建立對應 `dms.product.template`
- 回填 `template_id`
- 將系統自動生成的舊式 `SKU-00001` 代碼回填為「型號 + 出廠年份」可讀格式
- 回填 `production_year`（來源：舊 `year`）
- 若舊值因顯示或匯入帶有逗點，需正規化為純年份文字，例如 `2,026` → `2026`

### 6.2 價格 migration

若 legacy `dms.vehicle.price` 有資料：

- 依 `valid_year_month` 建立 `dms.price.version`
- 建立對應 `dms.price.line`
- `list_price` 預設以 `cash_price` 初始化，並在文件中標記為過渡值

### 6.3 分期 migration

若 legacy `dms.installment.plan` 有資料：

- 建立對應 `dms.installment.rule`
- 每筆 plan 轉為一筆 `dms.installment.rule.line`
- `price_basis` 預設為 `cash`
- legacy 不存在的費用資料不自動生成費用明細

---

## 7. Open Questions

本輪已無阻塞實作的 Open Question；以下事項已在實作前後確認並落地：

1. legacy `name` → `機種（family_name）`
2. legacy `model` → `型號（model_name）`
3. `型式（type_name）` 在 legacy migration 先留空
4. legacy `valid_year_month` 轉 `effective_date` 時採該月 1 日
5. 舊 `dms_sale` 產品 / 價目選單已隱藏，正式入口改由 `dms_product` 接手

## 8. Assumptions

1. 本輪既有正式產品資料量仍低，允許以 `post_init_hook` 進行一次性 backfill，而不另外建立獨立 migration framework。
2. `dms_visit` 的送出物品本輪以文字輸入為主，不要求立即與 canonical SKU 重新耦合。
3. `dms_sale` 既有 `dms.vehicle.price`、`dms.installment.plan` 等模型先保留作 fallback / 歷史資料來源，不在本輪粗暴刪除。
4. 自動生成的 SKU 代碼需以可讀性優先，預設採 `型號-出廠年份`，同碼碰撞時補 `-02`、`-03`。
5. 出廠年份雖然表達的是年份，但本輪以文字欄位保存，避免前端或報表將其格式化成千分位。

---
