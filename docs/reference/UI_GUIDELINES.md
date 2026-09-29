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
  寫死色碼會讓夜間／高對比外觀失效。例外：參數定義與主題區塊、主題選擇器的預覽色塊、列印樣式與 `contract.css`。
  半透明色用 `color-mix(in srgb, var(--參數) N%, transparent)`；陰影與遮罩用 `--shadow-ink`。
  報表圖表的資料系列色由 `sales/reporting/engine.py` 與報表 JS 定義，不屬 CSS 參數。

| 類別 | 參數 |
| --- | --- |
| 基本色 | `--ink`／`--ink-soft`（文字）、`--muted`、`--surface*`、`--paper`、`--line-soft`／`--line-mid`／`--line`／`--line-strong`（由淺到深的線條）、`--forest`（操作）、`--navy`（框架）、`--gold`（重點）、`--focus-ring` |
| 狀態色 | `--green`／`--blue`／`--amber`／`--red` 各有 `-soft`（底）、`-border`（淡邊框）、`-border-strong`（強調邊框）、`-ink`（深色文字）；`--amber-strong` 為待處理強調色 |
| 色上文字 | `--on-accent`（主色、深藍底上的白字）、`--on-status`（狀態色底上的字，夜間自動轉深） |
| 識別色 | `--identity-sym-*`、`--identity-suzuki*`、`--identity-yellow*`、`--identity-violet*`（品牌與分線群組標籤）、`--chart-1` |
| 圓角 | `--radius-xs` 6px、`--radius-sm` 8px、`--radius-md` 12px（按鈕、輸入框）、`--radius-lg` 16px、`--radius` 18px（主卡片）、`--radius-pill`；3px 以下的細線與 `50%` 可直接寫 |
| 字級 | `--text-2xs` 11px、`--text-xs` 12px、`--text-sm` 13px、`--text-sm-plus` 14px、`--text-base` 16px、`--text-md` 18px、`--text-lg` 20px、`--text-xl` 24px、`--text-2xl` 28px、`--text-3xl` 32px；大標題可用 `clamp()` |
| 間距刻度 | `--space-1`～`--space-8`：4、8、12、16、24、32、48、64px；padding／margin／gap 只用刻度，0–3px 細線例外 |
| 間距角色 | `--card-pad`（頁面層卡片內距 24px）、`--inset-pad`（內層小框與篩選列 16px）、`--bar-pad`（單行工具列／儲存列 12px 16px）、`--stack-gap`（頁面層區塊間距 24px）、`--stack-gap-sm`（內層小框間距 16px）；700px 以下自動縮為 16／12／8·12／16／12px |
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
5. **間距**：頁面層區塊（卡片、篩選列、分頁列、狀態列）之間一律 `--stack-gap`；卡片內距 `--card-pad`，
   卡片內的小框用 `--inset-pad`、彼此間距 `--stack-gap-sm`。父層是 grid／flex 時只用父層 `gap`，
   子層不再加 margin，避免疊加。可收合區塊關閉時只顯示標題列，內距放在標題列與內容區，不放在外框。

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

## 下拉選單

- 原生 `<select>`（單選）由 `app.css` 末段統一外觀：取消系統箭頭，改用與可搜尋選單相同的線條箭頭
  （顏色 `--select-chevron`）、`--radius-md` 圓角、滑過加深邊框、聚焦綠色外框、停用時淡化。
  各頁只調整寬度與高度，不自行畫箭頭或改圓角。
- 選項多或需要搜尋時，在 select 加 `data-searchable-select` 使用可搜尋選單。
- 自訂的下拉觸發按鈕（例如報表圖表類型、展開區塊）用 `<span class="ui-chevron">`，不使用 `⌄`、`▾` 等文字箭頭。

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
