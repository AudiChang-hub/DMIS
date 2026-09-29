# UI／UX 統一規範

全站畫面與操作流程的單一來源。新增或修改模板前先對照本檔；
`sales/tests/test_ui_consistency.py` 會擋下已知的偏離寫法。

## 樣式檔

- 全域樣式只有 `static/css/app.css`，由 `templates/base.html` 載入；不得再新增全域覆寫檔。
  2026-09-29 已將原 `ui-comfort`、`account-workspace`、`catalog-selection`、`site-review`、
  `ppt-refinements` 依原載入順序併入檔尾各區段。
- 模組專屬樣式放在 `static/css/<模組>.css`，由頁面的 `{% block head %}` 載入，
  只加模組修飾，不重新定義頁首、按鈕、空狀態等共用元件。
- 顏色、圓角、字級一律使用 `app.css` 開頭的設計參數。六種外觀主題靠同一組參數切換，
  寫死色碼會讓夜間／高對比外觀失效。例外：主題選擇器的預覽色塊、列印文件（`contract.css`）。

| 類別 | 參數 |
| --- | --- |
| 顏色 | `--ink`、`--muted`、`--surface*`、`--line*`、`--forest`（操作）、`--navy`（框架）、`--gold`（重點）、`--red`／`--amber`／`--green`／`--blue`（狀態，搭配 `*-soft` 底色） |
| 圓角 | `--radius-xs` 6px、`--radius-sm` 8px、`--radius-md` 12px（按鈕、輸入框）、`--radius-lg` 16px、`--radius` 18px（主卡片）、`--radius-pill`；3px 以下的細線與 `50%` 可直接寫 |
| 字級 | `--text-2xs` 11px、`--text-xs` 12px、`--text-sm` 13px、`--text-sm-plus` 14px、`--text-base` 16px、`--text-md` 18px、`--text-lg` 20px、`--text-xl` 24px、`--text-2xl` 28px、`--text-3xl` 32px；大標題可用 `clamp()` |
| 頁寬 | `page_class`：`page-shell--wide`（清單、報表）、`page-shell--form`（表單）、預設 `page-shell--standard`、`page-shell--compact`；寬度由 `--shell-*` 決定，目前表單 1440px、其餘 1560px |

## 頁面骨架

每個完整頁面依序是：

1. **導覽列**：`{% site_navigation %}` 依權限自動算出上一層；需要指定上一層時改用
   `{% include "sales/_page_back.html" with fallback_url=… label=… %}`。
   兩者擇一，不得再手寫 `← 返回…` 連結或按鈕。報表頁覆寫 `{% block report_nav %}`。
2. **頁首**：每頁只有一個 `h1`，放在標準頁首：

   ```html
   <section class="hero-row compact-hero">
     <div><p class="eyebrow">所屬區域</p><h1>頁面標題</h1><p class="muted">一句說明</p></div>
     <div class="hero-actions">…次要動作… <a class="button primary">主要動作</a></div>
   </section>
   ```

   模組需要不同排版時，在 `hero-row` 上加修飾 class（例如 `report-heading`），不另建頁首元件。
   確認頁與單卡片頁也一樣：標題放在卡片上方的頁首，卡片只放說明與表單。
3. **分頁**：同一物件的多個設定頁用 `account-tabs`；車行管理共用 `sales/_dealer_source_tabs.html`。
4. **內容**：`section-block`／`card` 區塊；清單頁用 `inventory-filters` 篩選列、
   `inventory-list-panel` 與分頁 `{% pagination %}`。

## 按鈕

| 等級 | class | 用途 |
| --- | --- | --- |
| 主要 | `button primary` | 每個操作列最多一個 |
| 次要 | `button ghost` | 取消、清除、返回、列印等並列動作 |
| 輔助 | `button secondary` | 切換、快捷入口等低強調動作 |
| 危險主要 | `button danger` | 確認頁上的不可逆主要動作，位置同主要按鈕 |
| 危險次要 | `button danger-outline` | 清單或詳細頁上的刪除、停用入口，放在操作列最前 |

- 一律帶等級，不使用無等級的 `button`；`small` 只調尺寸。JS 產生的按鈕同樣適用。
- 操作列（`form-actions`、`hero-actions`、`inventory-filter-actions`）順序：次要在前、主要最後。
- 同一表單有多個**送出**按鈕時，按 Enter 會觸發第一個；此時主要動作維持第一個送出按鈕，
  不為了視覺順序調換（例：訂單刪除確認、說明文字管理）。

## 確認與送出

- 刪除、作廢、覆寫、正式寫入等不可逆送出，一律在 `<form>` 或送出按鈕加 `data-confirm="…"`；
  `static/js/form-feedback.js` 統一處理確認、防重複送出與錯誤摘要。
- 不在模板寫 `onsubmit`／`onclick` 呼叫 `confirm()`。
  只有不經表單送出的腳本互動（例如刪除表單列）可以在 JS 內呼叫 `window.confirm`。
- 伺服器訊息走 Django messages，由 `message-toasts.js` 顯示；不在頁面另做提示框。

## 空狀態與表格

- 沒有資料時用 `empty-state`：
  `<div class="empty-state">[<span class="empty-state__icon" aria-hidden="true">＋</span>]<h3>標題</h3><p>說明與下一步</p>[按鈕]</div>`；
  區塊內較小時加 `small`。
- 主清單：`inventory-table-wrap` 包 `table.inventory-table`；區塊內小表：`table-wrap` 包 `table`。
  可水平捲動的表格外層需有 `tabindex="0"` 與 `aria-label`。

## 例外

錯誤頁、登入／強制改密碼、使用說明、公告閱讀頁、帳號權限工作區（`permissions/_header.html`）、
報表閱讀器與列印文件有獨立版面，不套用標準頁首，但仍須使用設計參數、按鈕等級與共用返回列。
例外清單維護在 `test_ui_consistency.py` 的 `HERO_EXEMPT`／`ACTION_ORDER_EXEMPT`。
