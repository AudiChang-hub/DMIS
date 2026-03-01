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
