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
- 欄位總數（show + hide）沒有硬性上限，但建議控制在 20 欄以內。

### 3. 15 欄硬限制（JS Patch）
- 每個使用自訂 list view 的模組，**必須**提供對應的 JS patch 檔案。
- Patch 邏輯：攔截 `toggleOptionalField`，當已顯示欄位數 ≥ 15 時：
  1. 阻止切換（不呼叫 `_super`）
  2. 顯示 warning notification（「列表最多只能顯示 15 個欄位…」）
  3. 強制 OWL rerender：`this.state.columns = [...this.state.columns]`（確保 checkbox 回復）
- Patch 命名規則：`{module_name}.{modelCamelCase}ColumnLimit`
- 僅對該模組對應的 `resModel` 生效，不影響其他模型的列表。

### 4. Search View 篩選
- 每個 search view 必須包含：
  - `filter name="filter_active"` — 「啟用中」`[('active','=',True)]`
  - `filter name="filter_archived"` — 「已歸檔」`[('active','=',False)]`
- 兩個 filter 之間加 `<separator/>`。

---

## 各模組合規狀態

| 模組 | active 欄位 | optional 欄位 | 15欄 JS | 歸檔篩選 |
|---|---|---|---|---|
| dms_core（dms.dealer） | ✅ | ✅ | ✅ | ✅ |
| dms_product（dms.product） | ✅ | ✅ | ✅ | ✅ |
| dms_customer（res.partner） | ✅（內建） | ✅（2026-03-01 更新） | ✅（2026-03-01 新增） | ✅（2026-03-01 新增） |

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
