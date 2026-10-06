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

## 設計系統 2.0（1.31.0 起）

- 視覺語言：暖白底（`--paper`）、墨黑文字（`--ink`）、群青操作色（`--forest`／`--action-*`），
  螢光綠（`--gold`）只用於深色重點區塊的小面積點綴；夜間主題為深墨底配柔和群青。
- 字型：`--font-sans`（Inter＋系統中文黑體）用於內文，`--font-display`（Manrope＋系統中文黑體）用於標題與大數字；
  字型檔在 `static/fonts`（SIL OFL 1.1，只含英數字），由 `base.html` 預先載入。表格、時間、金額使用等寬數字。
- 頁首為半透明淺色玻璃，目前所在功能以墨黑膠囊標示；按鈕一律膠囊形，按下有輕微回饋。
- 卡片用髮絲邊線＋`--shadow-soft`，不再用粗框；欄位聚焦為群青光暈。
- 動態參數：`--ease-out`、`--dur-1`～`--dur-3`；換頁淡入、頁首區上浮，`prefers-reduced-motion` 時全部關閉。
- 新增顏色或動態一律先加參數，元件只引用參數；元件外觀寫在該元件原本的規則（1.34.4 起已合併），
  檔尾「設計系統 2.0」段落只留必須排在其他元件規則之後才能生效的少數覆蓋。
- 同一選擇器只寫一處。不同寬度的調整寫在 `@media` 內，且必須排在基礎規則之後；
  在後面再寫一次無條件的同選擇器規則，會讓前面的 `@media` 調整失效（1.34.4 頁首超出即此原因）。
- 斷點成對時，手機側寫 `max-width: 860px`，桌面側寫 `min-width: 860.02px`（不寫 `861px`），
  避免 Windows 縮放產生的小數寬度落在兩者之間；JS 判斷寬度用同一個 `matchMedia`，不用整數 `innerWidth`。
- 品質檢查：每次調整外觀，以 6 種主題 × 24 個代表頁量文字對比（一般字 ≥ 4.5、大字 ≥ 3），
  並檢查 390／1024／1440 寬度無橫向溢出；動到頁首時另掃 861–1400px。

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
   機種的各項設定共用 `sales/_vehicle_model_workspace.html`（頁首＋分頁列取代標準頁首與返回列，
   樣式在 `static/css/vehicle-model-workspace.css`，頁面以 `_vehicle_model_workspace_head.html` 載入）；
   新增機種相關設定頁時加入此工作區，送出後導回同一分頁。
4. **內容**：`section-block`／`card` 區塊；清單頁用 `inventory-filters` 篩選列、
   `inventory-list-panel` 與分頁 `{% pagination %}`。
5. **間距**：頁面層區塊（卡片、篩選列、分頁列、狀態列）之間一律 `--stack-gap`；卡片內距 `--card-pad`，
   卡片內的小框用 `--inset-pad`、彼此間距 `--stack-gap-sm`。父層是 grid／flex 時只用父層 `gap`，
   子層不再加 margin，避免疊加。可收合區塊關閉時只顯示標題列，內距放在標題列與內容區，不放在外框。

## 對齊

- 同一張卡片內，標題、內容文字、表格首欄與內層小框的外框共用同一條左緣（卡片內距 `--card-pad`）；
  同一頁上下疊放的頁面層卡片，標題起點也要一致。
- `section-block` 是無內距面板：標題用 `.section-title`，文字內容包在 `.section-body`，清單列、表格自帶左右 `--card-pad`；
  不直接把 `h2`／`p`／清單列塞進面板（有內距的情境如首頁、系統管理頁除外）。
- 已有內距的卡片（`.card`、`static-section` 等）裡，標題列與表單格線不再重複左右內距；表格首尾欄內距歸零。
- 內層小框不可貼齊外層卡片邊緣，也不可比外框圓角更大；需要分段時用分隔線，不做框中框。
- 多欄資料列用固定欄寬的 grid，不用 `space-between` 讓中間欄位漂浮。
- 卡片最後一個元素不留下邊距；頁面操作按鈕放在頁首的 `hero-actions`，不放在頁首之前。
- 收合區塊（`details`）一律使用全站 summary 樣式：右側線條箭頭、標題對齊內容，不出現瀏覽器預設 ▶。
- 驗證方式：本機以 `static/_audit/align.js` 類的量測在 1600／1280／390px 檢查（工具不提交），規則由
  `test_ui_consistency.py` 部分把關。

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

## 提示框與確認頁

- 說明、警示、阻擋事項用 `callout`（`callout--warning`／`--danger`／`--info`／`--success`）：
  `<div class="callout callout--warning"><span class="callout__icon" aria-hidden="true">!</span><div><h3>標題</h3><ul>…</ul><p>…</p></div></div>`；
  不在面板裡再放一個 `section-block` 當提示框。
- 需要使用者勾選確認的項目用 `.check-list` 包 `<label class="check-row"><input type="checkbox"><span>說明</span></label>`，整列可點。
- 不可逆操作的確認頁結構：`section-block.confirm-panel` → `.section-title` → `.section-body.confirm-panel__body`（說明、`confirm-facts` 資料、callout）
  → `form.confirm-panel__form`（原因欄、check-list、`form-actions.confirm-panel__actions`）。面板與頁首同一左緣，不置中。
  - Django 勾選欄位用 `{% include 'sales/_check_row.html' with field=… %}`，錯誤訊息會接在該列下方。
  - 原值／新值對照用 `.confirm-compare`（兩欄、左側細線，有差異的一欄加 `is-changed`），不另畫框。
  - 表單較長時用 `.confirm-panel__group`（小標題＋說明＋欄位）分段，並排欄位放 `.confirm-panel__grid`。
  - 核對內容較多時可連續放多張 `confirm-panel`（例：歷史更正頁的核對 → 影響 → 確認），送出表單固定在最後一張。
  - 被阻擋時仍保留操作列，只放返回按鈕；阻擋原因用 `callout--danger`。
  - 目前套用：訂單刪除／還原、台數獎金規則刪除、車行永久刪除、公告整理、歷史領牌改期、歷史退訂換買家、
    開單公司確認、開單公司未確認、淨利解鎖；清單見 `test_confirm_pages_share_confirm_panel`。
- 多行文字框一律帶 `form-control`：Django 表單在 `attrs` 加 `"class": "form-control"` 或由表單類別統一補上；模板手寫的 `<textarea>` 也要加。
  欄位（`.field`）內的輸入元件填滿欄位寬度。

## 填寫表單

- 欄位一律用 `.field` 外框（`{% include 'sales/_field.html' %}`）：標籤 13px 粗體、`--field-label` 色，必填以 `<em>必填</em>` 標示，
  錯誤訊息用 `small.field-error`。整張表單直接輸出時用 `{% include 'sales/_form_fields.html' %}`，不使用 `form.as_p`／`as_table`／`as_div`。
- 欄位排成 `.form-grid`（桌面兩欄、手機一欄）；外層已有內距時加 `form-grid--plain`，單欄加 `form-grid--single`。
- 表單分段用有內距的卡片（`form-section static-section`）或 `section-block`；分段內的小分組只用標題與分隔線區分，不再畫第二層框。
- 表單與頁首同一左緣，不置中；可限制最大寬度。
- 勾選項目用整列可點的樣式（`check-row`，帳號頁的 `account-choice-grid` 外觀相同），勾選後變色。
- 送出按鈕：
  - 短表單在最後放 `form-actions`（次要在前、主要最後）。
  - 長表單用 `form-savebar`：固定在畫面底部，左側可放 `form-savebar__hint` 說明，右側放按鈕；手機版停在底部選單上方。
    全站只有這一種儲存列，不另做深色浮動按鈕或半透明條。
- 例外：訂單建立／修改與訂單工作台（`mobile-order-form`、`operations-form`）、報表設計器、登入流程有獨立版面。

## 確認與送出

- 操作回饋由 `static/js/busy-indicator.js` 統一處理：站內換頁、送出表單、使用者操作後 1.5 秒內發出的 `fetch`，
  超過 0.12 秒顯示頂端進度條（`.busy-bar`），超過 0.6 秒顯示下方提示（`.busy-status`），8 秒後提醒不要關閉頁面。
  定時輪詢不顯示。另開分頁、下載與錨點連結不顯示；個別連結或表單可加 `data-no-busy` 排除，`fetch` 可傳 `{busy: false}`。
  送出中的按鈕由 `form-feedback.js` 加上 `is-submitting`（轉圈＋「處理中…」），各頁不另做讀取動畫。

- 刪除、作廢、覆寫、正式寫入等不可逆送出，一律在 `<form>` 或送出按鈕加 `data-confirm="…"`；
  `static/js/form-feedback.js` 統一處理確認、防重複送出與錯誤摘要。
- 不在模板寫 `onsubmit`／`onclick` 呼叫 `confirm()`。
  只有不經表單送出的腳本互動（例如刪除表單列）可以在 JS 內呼叫 `window.confirm`。
- 伺服器訊息走 Django messages，由 `message-toasts.js` 顯示；不在頁面另做提示框。

## 空狀態與表格

- 沒有資料時用 `empty-state`：
  `<div class="empty-state">[<span class="empty-state__icon" aria-hidden="true">＋</span>]<h3>標題</h3><p>說明與下一步</p>[按鈕]</div>`；
  區塊內較小時加 `small`。
- 所有資料表格一律 `inventory-table-wrap` 包 `table.inventory-table`：表頭淡底、13px 粗體，儲存格 14px、
  上下 12px 內距、列間細線、滑過淡底。欄位少、放在區塊內的小表加 `inventory-table--fit`（不強制 1080px 寬）。
  可水平捲動的表格外層需有 `tabindex="0"` 與 `aria-label`。
- 每個 `td` 帶 `data-label`：600px 以下自動變成卡片，欄名顯示在值的左側；操作欄加 `inventory-row-action` 橫跨整列。
  列標題用 `tbody th`（例：月份、車型），手機版會成為卡片標題。
- 數字欄在 `th` 與 `td` 加 `is-number`：右對齊、等寬數字。
- 對齊：表格直接放在無內距面板（`section-block`、`inventory-list-panel`）時，首尾欄內距等於卡片內距；
  放在有內距卡片（報表面板、營運走勢、已刪除訂單、系統管理頁）時，表格延伸到卡片左右邊緣，首尾欄文字仍與標題對齊。不自行覆寫表頭顏色或內距。
- 例外：列印文件（`contract_print`）、報表閱讀器的 `report-results`（沿用同一組表頭顏色與線條）、
  價格表分工的拖曳排序表（`price-assignment-table`，表頭與儲存格數值同資料表）。

## 例外

錯誤頁、登入／強制改密碼、使用說明、公告閱讀頁、帳號權限工作區（`permissions/_header.html`）、
報表閱讀器與列印文件有獨立版面，不套用標準頁首，但仍須使用設計參數、按鈕等級與共用返回列。
例外清單維護在 `test_ui_consistency.py` 的 `HERO_EXEMPT`／`ACTION_ORDER_EXEMPT`。
