# 全域 UI 標準（UI Standards）

> 所有 DMS 模組的列表視圖（list/tree view）必須遵守本規範。  
> 本規範適用於 dms_core、dms_product、dms_customer 及所有後續模組。

---

## 列表視圖統一規則

### 1. `active` 欄位必須存在
- 所有列表均須呈現 `active` 欄位，`optional="show"`（預設顯示）。
- 讓使用者在列表中直接看到該筆是否啟用。
- 若模型本身無 `active` 欄位，必須在模型中新增 `active = fields.Boolean(default=True)`。

### 2. 欄位選擇器（optional columns）
- 所有業務欄位均需加入 `optional` 屬性：
  - **預設顯示**（`optional="show"`）：核心識別欄位，初始可見，不超過 **8 欄**（含 active）。
  - **預設隱藏**（`optional="hide"`）：補充資訊欄位，可由使用者自行勾選顯示。
- **欄位完整性**：列表的可選欄位必須涵蓋詳細資料（form view）中所有欄位，不得短少。One2many 子表格欄位除外（不適合列表顯示）。
- 欄位總數（show + hide）沒有硬性上限，但建議控制在 20 欄以內。

### 3. 15 欄硬限制（JS Patch）
- 每個使用自訂 list view 的模組，**必須**提供對應的 JS patch 檔案。
- Patch 邏輯：攔截 `toggleOptionalField`，當已顯示欄位數 ≥ 15 時：
  1. 阻止切換（不呼叫 `_super`）
  2. 顯示 warning notification（「列表最多只能顯示 15 個欄位…」）
  3. 強制 OWL rerender：`this.state.columns = [...this.state.columns]`（確保 checkbox 回復）
- Patch 命名規則：`{module_name}.{modelCamelCase}ColumnLimit`
- 僅對該模組對應的 `resModel` 生效，不影響其他模型的列表。
- **例外**：模型欄位數少於 15 欄（如純查詢資料表）時，JS patch 可免。

### 4. Search View 篩選
- 每個 search view 必須包含：
  - `filter name="filter_active"` — 「啟用中」`[('active','=',True)]`
  - `filter name="filter_archived"` — 「已歸檔」`[('active','=',False)]`
- 兩個 filter 之間加 `<separator/>`。

### 5. 全程中文化（中華民國慣用語）
- 所有 UI 文字（視圖 string 屬性、filter/group 標籤、placeholder、alert 提示文字）一律使用繁體中文。
- 專有名詞（品牌名稱如「三陽」「台鈴」「Yamaha」、技術識別碼如「DMS」、欄位技術名如 `code`）不受限。
- 用語遵循中華民國常用習慣：
  - 「啟用」→「啟用中」（表示持續狀態）
  - 「刪除」、「儲存」、「取消」維持標準台灣繁中
  - 避免使用中國大陸慣用語（如「删除」、「保存」、「确认」）

### 6. 查詢資料表（lookup table）規則
- 欄位數少（≤ 5 欄）的純查詢資料表（如品牌、車行類型），仍需遵守：
  - `name` 以 `optional="show"` 呈現
  - `active` 以 `optional="show"` 呈現
  - 提供 search view，含「啟用中」及「已歸檔」篩選
  - 免 JS 15 欄 patch（欄位數不可能達到限制）

---

## 各模組合規狀態

| 模組 | active show | optional 完整 | 欄位完整 | 15欄 JS | 啟用中/歸檔篩選 | 中文化 |
|---|---|---|---|---|---|---|
| dms_core（dms.dealer） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| dms_core（dms.brand） | ✅ | ✅ | ✅ | 免 | ✅ | ✅ |
| dms_core（dms.store_type） | ✅ | ✅ | ✅ | 免 | ✅ | ✅ |
| dms_product（dms.product） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| dms_customer（res.partner） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 範本（Template）

```xml
<tree string="XXX 清單">
  <!-- optional="show"：核心識別欄，≤8 欄 -->
  <field name="name"   optional="show"/>
  <field name="active" optional="show"/>
  ...
  <!-- optional="hide"：補充資訊欄 -->
  <field name="note"   optional="hide"/>
</tree>
```

```javascript
patch(ListRenderer.prototype, "{module}.{Model}ColumnLimit", {

    async toggleOptionalField(fieldName) {
        if (this.props?.list?.resModel !== "model.name") {
            return this._super(fieldName);
        }
        const turningOn = !this.optionalActiveFields[fieldName];
        if (turningOn) {
            const visibleCount = Object.values(this.optionalActiveFields)
                .filter(Boolean).length;
            if (visibleCount >= 15) {
                this.env.services.notification.add(
                    "列表最多只能顯示 15 個欄位，請先取消勾選其他欄位再新增。",
                    { title: "欄位顯示上限", type: "warning", sticky: false }
                );
                this.state.columns = [...this.state.columns];
                return;
            }
        }
        return this._super(fieldName);
    },
});
```

### 7. 響應式清單視圖（RWD）

行動裝置/平板瀏覽時，透過 CSS 媒體查詢自動隱藏次要欄位，降低橫向捲動負擔。

| 裝置寬度 | 保留欄位 | 自動隱藏欄位 |
|---|---|---|
| ≤ 575px（手機） | `code`、`name`、`phone_1` | 其餘所有 optional="show" 欄位 |
| 576–767px（直式平板） | 手機欄位 + `store_type_id` | `owner_name`、`store_manager`、`mobile`、`brand_auth_brand_display`、`active` |
| ≥ 768px（橫式平板以上） | 依 `optional` 設定全部顯示 | — |

- 隱藏規則寫在 `dms_theme.scss`（section 10），以 `[data-name]` / `[name]` 屬性選取欄位。
- 不影響使用者手動切換 optional columns，只控制「初始顯示行為」。

### 8. 防誤觸規範（Anti-Accidental-Edit）

目的：在手機/平板上降低誤觸修改資料的機率。

| 措施 | 說明 |
|---|---|
| 清單不可直接編輯 | `<tree>` 不設 `editable` 屬性，所有列均需點入 form view 才能編輯 |
| boolean 欄位清單唯讀 | 清單視圖中的 Boolean 欄位加 `readonly="1"`，如 `active`、`manager_same_as_owner` 等，防止觸碰直接翻轉 |
| 預設欄數最小化 | 手機視圖下 CSS 強制只顯示最少必要欄位，減少誤觸面積 |

---

## 品牌色彩規範（Brand Theme）

> 本系統主要服務三陽（SYM）與台鈴（Suzuki Taiwan）兩大品牌，全後台使用雙品牌主題色貫穿視覺。

### 品牌色定義

| 用途 | 色票 | 說明 |
|---|---|---|
| 主色（Primary） | `#1A7B3A` | 三陽 SYM 品牌綠 |
| 主色深版 | `#145F2D` | 按鈕 hover / active |
| 輔色（Secondary） | `#003087` | 台鈴 Suzuki 深海軍藍 |
| 輔色深版 | `#00236B` | 連結 hover |
| 輔色中版 | `#1A4B9C` | 選中行背景 tint |

### 套用範圍

- **頂部導覽列**：左紅右藍漸層背景（`linear-gradient(90deg, #CC0000, #003B8E)`）
- **主要按鈕（btn-primary）**：三陽紅
- **超連結**：台鈴藍
- **列表 hover**：三陽紅 4% 透明度
- **列表選中行**：台鈴藍 8% 透明度
- **狀態列 active 節點**：三陽紅
- **Notebook 分頁 active**：三陽紅底線
- **搜尋 facet 標籤**：台鈴藍底色

### 實作位置

- 樣式檔：`addons/dms_core/static/src/scss/dms_theme.scss`
- 掛載點：`web.assets_backend`（append，覆蓋 Odoo 預設樣式）
