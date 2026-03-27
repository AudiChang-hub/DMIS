# 01 — Spec：新一代產品管理模組（015-dms-product-rebuild）

## 1. 模組定位

| 項目 | 值 |
|---|---|
| 技術名稱 | `dms_product` |
| 顯示名稱 | DMS 產品管理 |
| 性質 | 新世代產品主資料模組（非舊版 `dms_product` 邏輯回滾） |
| 角色 | 未來唯一的產品管理入口 |
| 本輪依賴 | `dms_core`, `dms_sale` |

> 本輪採「逐步收斂」策略：新模組負責新的產品主資料結構與使用者入口；`dms_sale` 透過相容層延續既有流程，`dms_visit` 則先暫時與產品主檔斷開，不在本輪重寫整體交易邏輯。

---

## 2. Canonical 資料模型

### 2.1 `dms.product.template`（產品模板）

用途：表達穩定規格層，不含車色與出廠年份。

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `brand_id` | Many2one → `dms.brand` | ✓ | 品牌 |
| `family_name` | Char | ✓ | 機種，例如 JET / MMBCU / Saluto |
| `type_name` | Char |  | 型式 |
| `model_name` | Char |  | 型號 |
| `energy_type` | Selection(oil/electric) | ✓ | 相容 `dms_sale` 既有流程所需 |
| `active` | Boolean |  | 啟用 |
| `note` | Text |  | 備註 |

規則：

- UI 文案必須明確區分「機種」不是大分類，而是產品家族 / 車系層級
- `family_name + type_name + model_name + brand_id` 應可作為模板辨識基礎
- `type_name` / `model_name` 允許在 legacy migration 初期為空，以避免舊資料失聯

### 2.2 `dms.product`（可販售產品項，相容延用既有技術模型）

用途：本輪將既有 `dms.product` 收斂為「模板 + 出廠年份」產品項，讓銷售、拜訪、財務可持續使用既有模型名稱而不斷線，同時不再把顏色拆成多筆產品項。

新增或重新定義的業務欄位至少包含：

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `template_id` | Many2one → `dms.product.template` | ✓ | 對應產品模板 |
| `internal_code` | Char | ✓ | 內部唯一代碼 |
| `production_year` | Char | ✓ | 出廠年份 |
| `active` | Boolean |  | 啟用 |

相容欄位：

- 保留既有 `brand_id`, `name`, `model`, `year`, `energy_type` 等 legacy 欄位
- 透過同步邏輯讓 legacy 欄位仍可支撐 `dms_sale` / `dms_finance` 現有流程

規則：

- `internal_code` 必須唯一
- `internal_code` 預設採「型號 + 出廠年份」生成，例如 `UC125DA-2026`
- 同一模板下，同一 `production_year` 只能有一筆啟用中的產品項
- 顏色不得再作為產品項拆分依據
- `production_year` 為年份文字欄位，畫面應直接顯示 `2026`，不得以 `2,026` 之類的位數逗點格式顯示
- 不得只靠中文名稱識別產品項

### 2.3 `dms.product.color`（產品項顏色）

用途：表達某個產品項可販售的顏色清單，供銷售單 `color_id` 下拉選擇使用。

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → `dms.product` | ✓ | 對應產品項 |
| `name` | Char | ✓ | 顏色名稱 |
| `sequence` | Integer |  | 排序 |
| `active` | Boolean |  | 啟用 |

規則：

- 同一產品項可有多筆顏色
- 顏色僅作為銷售選項，不參與價格與分期規則識別
- 同一產品項下，同名顏色不得重複
### 2.4 `dms.price.version`（價目版本）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 版本名稱 |
| `effective_date` | Date | ✓ | 生效日 |
| `state` | Selection(draft/effective/archive) | ✓ | 狀態 |
| `note` | Text |  | 備註 |

規則：

- 不要求使用者手動維護迄日
- 查詢價格時，抓取 `effective_date <= 查詢日` 且狀態可用的最新版本
- 價目版本需支援複製既有版本，並連同其 `價格基準` 一起複製為新版本
- 複製後的新版本名稱需自動重生為不重複值
- 複製後的新版本狀態需重設為 `draft`

### 2.5 `dms.price.line`（價格基準）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `version_id` | Many2one → `dms.price.version` | ✓ | 價目版本 |
| `product_id` | Many2one → `dms.product` | ✓ | 產品項（模板 + 出廠年份） |
| `cash_price` | Float(12,0) | ✓ | 現金價 |
| `list_price` | Float(12,0) | ✓ | 牌價 |
| `note` | Text |  | 備註 |

規則：

- 同一產品項在同一版本只能有一筆價格基準
- 價格查詢以版本生效日決定，不直接把價格塞回單一產品欄位
- 價目版本需支援批次加入多個產品項，一次建立多筆價格基準列
- 價目版本批次加入產品項時，需可先輸入統一的現金價與牌價，再套用到所有新建價格列
- 價目版本複製時，既有 `價格基準` 明細需完整複製到新版本

### 2.6 `dms.installment.rule`（分期規則模板）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 規則名稱 |
| `active` | Boolean |  | 啟用 |
| `note` | Text |  | 備註 |

### 2.7 `dms.installment.rule.line`（分期規則明細）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `rule_id` | Many2one → `dms.installment.rule` | ✓ | 規則模板 |
| `period_from` | Integer | ✓ | 起始期數 |
| `period_to` | Integer | ✓ | 結束期數 |
| `price_basis` | Selection(cash/list) | ✓ | 採用現金價或牌價 |
| `note` | Text |  | 備註 |

規則：

- 不得硬編碼 `type_1 / type_2 / type_3`
- 同一模板內期數區間不得重疊

### 2.8 `dms.fee.type`（費用類型）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `name` | Char | ✓ | 費用名稱 |
| `code` | Char | ✓ | 內部代碼 |
| `active` | Boolean |  | 啟用 |
| `note` | Text |  | 備註 |

預設資料至少包含：

- 開辦費
- 設定費

### 2.9 `dms.installment.rule.fee`（分期規則費用明細）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `rule_line_id` | Many2one → `dms.installment.rule.line` | ✓ | 對應規則明細 |
| `fee_type_id` | Many2one → `dms.fee.type` | ✓ | 費用類型 |
| `amount` | Float(12,0) | ✓ | 金額 |
| `charge_mode` | Selection(extra/included/company_absorb) | ✓ | 外加 / 內含 / 公司吸收 |
| `note` | Text |  | 備註 |

### 2.10 `dms.installment.rule.binding`（產品項 × 價目版本 × 分期規則 掛接）

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `product_id` | Many2one → `dms.product` | ✓ | 產品項 |
| `price_version_id` | Many2one → `dms.price.version` | ✓ | 價目版本 |
| `rule_id` | Many2one → `dms.installment.rule` | ✓ | 分期規則模板 |
| `active` | Boolean |  | 啟用 |
| `note` | Text |  | 備註 |

規則：

- 同一產品項在不同價目版本下，可掛不同規則模板
- 同一產品項 + 價目版本只能有一筆啟用中的掛接

---

## 3. 查價與規則查詢邏輯

### 3.1 生效價格

查詢輸入：

- 產品項（`dms.product`）
- 查詢日（預設訂單日 / 今日）

查詢規則：

1. 從 `dms.price.line` 找出 `product_id = 產品項`
2. 價目版本需滿足：
   - `state in ('effective', 'archive')` 或明確允許查歷史版本
   - `effective_date <= 查詢日`
3. 依 `effective_date desc, id desc` 取最新一筆

### 3.2 生效分期規則

1. 先找到產品項在查詢日對應的有效價目版本
2. 從 `dms.installment.rule.binding` 依 `product_id + price_version_id` 找掛接
3. 取對應 `dms.installment.rule` 及其 `rule_line_ids` / `fee_ids`

---

## 4. UI / 選單設計

### 4.1 頂層 App

新增頂層 App：`產品管理`

### 4.2 選單結構

```
產品管理
├── 產品模板
├── 價目版本
├── 價格基準
├── 分期規則模板
├── 費用類型
└── 規則掛接
```

UI 原則：

- 以 List 為主
- 產品項不提供獨立頂層或次層入口，僅於產品模板表單中的「產品項」頁籤維護
- 顏色不提供產品模板層級的獨立頁籤，統一透過產品項列級「維護顏色」入口維護
- 產品項頁籤需同時顯示啟用與停用資料，避免停用後無法重新啟用
- 產品項頁籤需提供列級「複製」動作，便於同模板下快速建立不同年份或相近版本產品項
- 產品項頁籤需提供列級「維護顏色」入口，讓使用者以逐列新增方式維護顏色，不必手動輸入頓號或其他分隔符
- 維護顏色彈窗僅保留顏色清單本身，不顯示顏色代碼、相容欄位與圖片頁籤
- 產品項列級複製時，系統需自動清空舊 `internal_code` 並重新生成唯一代碼，避免前台沿用舊值造成誤判重複
- 產品項列級複製完成後，應只重新整理當前模板畫面，不得重複推入相同 breadcrumb
- 產品項頁籤刪除列時，對於未被其他交易資料引用的產品項，應直接刪除該產品項，而非僅解除模板關聯
- 模板清單中的 `產品項數量` 僅計算啟用中的產品項，停用項不計入數量
- 產品模板需提供可見的「複製」動作，讓內部人員可快速複製既有模板與其產品項
- 價目版本需提供可見的「複製」動作，讓內部人員可快速複製既有版本與其價格基準
- 涉及產品項選取的下拉與已選值顯示，預設採 `內部代碼 / 車種`，避免名稱過長；搜尋能力仍需可用出廠年份查找
- 主要畫面不得依賴圖片
- 圖片若保留，僅作相容欄位或次要資訊
- 不得干擾既有車行管理 UI

---

## 5. 相容與 migration 規格

### 5.1 相容策略

本輪採雙層策略：

1. **Canonical 層**：新模組提供 `dms.product.template`、`dms.price.version`、`dms.price.line`、`dms.installment.rule*`、`dms.fee.type`
2. **Compatibility 層**：既有 `dms.product` 保留為交易系統相容用產品項模型，持續供 `dms_sale` / `dms_finance` 使用
3. **拜訪模組過渡策略**：`dms_visit` 本輪先不再把送出物品綁定 `dms.product`，改採臨時脫鉤設計；待新產品模組穩定後，再以後續 spec 把送出物品接回 canonical 產品項

### 5.2 `dms_sale` 最小必要調整

- 若新價格結構存在，`dms.sale.order` 應優先使用新價格生效邏輯
- 若新結構尚無資料，保留對舊 `dms.vehicle.price` 的 fallback
- 不重寫 `dms_sale` 整體流程

### 5.3 `dms_visit` 最小必要調整

- `dms.visit.item` 本輪改為不依賴 `dms.product`
- 送出物品至少需保留可操作欄位：`item_name`、`quantity`、`note`
- 若需保留 `product_id` 供歷史資料使用，應改為非必填且不作本輪主要輸入欄位
- 未來待新產品模組穩定後，再透過新 spec 將 `dms.visit.item` 接回 `dms.product`（產品項層）

### 5.3 legacy 資料回填

至少處理：

- 既有 `dms.product` → 回填 `template_id`、`internal_code`、`production_year`
- 既有以顏色拆分的多筆 `dms.product` → 收斂為單一產品項 + 多筆 `dms.product.color`
- 既有 `dms.vehicle.price` → 建立對應 `dms.price.version` / `dms.price.line`
- 既有 `dms.installment.plan` → 建立對應 `dms.installment.rule` / `dms.installment.rule.line`

> 若舊資料無法完整推回 `機種 / 型式 / 型號` 三層，需以 `02-clarify.md` 記錄假設並由專案負責人確認。

---

## 6. 不得回退的保護條件

1. `dms_core` 不可修改
2. `user_management` 菜單與角色指派行為不可破壞
3. `dms_visit` 的送出物品功能不可失效，但本輪允許暫時改為非產品綁定輸入
4. `dms_finance` 既有測試與資料流不可失效
5. 舊資料不可失聯、不可粗暴刪除
