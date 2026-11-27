# UI／UX 統一規範

全站畫面與操作流程的單一來源。新增或修改模板前先對照本檔；
`sales/tests/test_ui_consistency.py` 會擋下已知的偏離寫法。

## 樣式檔

- 全域樣式只有 `static/css/app.css`，由 `templates/base.html` 載入；不得再新增全域覆寫檔。
  2026-09-29 已將原 `ui-comfort`、`account-workspace`、`catalog-selection`、`site-review`、
  `ppt-refinements` 依原載入順序併入檔尾各區段。
- 模組專屬樣式放在 `static/css/<模組>.css`，由頁面的 `{% block head %}` 載入，
  只加模組修飾，不重新定義頁首、按鈕、空狀態等共用元件。
- 只有單一模組用到的規則不放 app.css（T-242 A 案，分批從 app.css 搬出；只搬不改內容）：
  模組 CSS 的 `<link>` 放在該頁 `{% block head %}` 最前面，層疊順序維持「app.css → 搬出的規則 → 頁面原本的模組 CSS」；
  `{% load static %}` 要在 `{% block head %}` 之前。已搬出：價格表（`price-list.css`）、車行獎勵（`dealer-rewards.css`）、
  照片看板（`catalog-photo-board.css`）、假日（`business-holidays.css`）；第二批：領牌規則（`registration-fee-rules.css`）、
  機種與品牌（`vehicle-models.css`）、車行與年節送禮（`sales-sources.css`）、刪除審核（`order-deletion-queue.css`）、
  快速進車（`inventory-quick-entry.css`）、配件批次修改（`accessory-bulk.css`）、統一撥款對帳（`reconciliation.css`）。
  `test_ui_consistency.PageStylesheetSplitTests` 擋下這些前綴回到 app.css；
  搬移工具與驗收（全路由截圖比對、CSS coverage）在 `tools/ui_audit/`（不進 CI）。
- 顏色、圓角、字級一律使用 `app.css` 開頭的設計參數。六種外觀主題靠同一組參數切換，
  寫死色碼會讓夜間／高對比外觀失效。例外：參數定義與主題區塊、主題選擇器的預覽色塊、列印樣式與 `contract.css`。
  半透明色用 `color-mix(in srgb, var(--參數) N%, transparent)`；陰影與遮罩用 `--shadow-ink`。
  報表圖表的分類色用 `--chart-s1`～`--chart-s8` 與 `--chart-other`（2.11.0 起，淺深色各自驗證色盲分辨）；
  哪個分類用哪一格由 `sales/reporting/engine.py` 與報表 JS 依固定順序對應，同一分類每頁同色，「其他」類固定中性灰。

| 類別 | 參數 |
| --- | --- |
| 基本色 | `--ink`／`--ink-soft`（文字）、`--muted`、`--surface*`、`--paper`、`--line-soft`／`--line-mid`／`--line`／`--line-strong`（由淺到深的線條）、`--forest`（操作）、`--navy`（框架）、`--gold`（重點）、`--focus-ring` |
| 狀態色 | `--green`／`--blue`／`--amber`／`--red` 各有 `-soft`（底）、`-border`（淡邊框）、`-border-strong`（強調邊框）、`-ink`（深色文字）；`--amber-strong` 為待處理強調色，只用在圓點、邊條等非文字標記（對白底 3.37，不能當文字，文字用 `--amber-ink`）；紅（優先）與黃（注意）並列的等級標記另以形狀區分：紅＝實心點加外圈、黃＝空心圈，長條的黃級加斜紋（T-300） |
| 色上文字 | `--on-accent`（主色、深藍底上的白字）、`--on-status`（狀態色底上的字，夜間自動轉深） |
| 識別色 | `--identity-sym-*`、`--identity-suzuki*`、`--identity-yellow*`、`--identity-violet*`（品牌與分線群組標籤）、`--chart-1`、`--chart-s1`～`--chart-s8`／`--chart-other`（報表圖表分類色） |
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
- 頁首為半透明淺色玻璃（860px 以下頁首、底部導覽、精靈底部列、訂單精簡列改不透明底、不用 `backdrop-filter`，iPhone 捲動才順），目前所在功能以墨黑膠囊標示；按鈕一律膠囊形，按下有輕微回饋。
- 卡片用髮絲邊線＋`--shadow-soft`，不再用粗框；欄位聚焦為群青光暈。
- 動態參數：`--ease-out`、`--dur-1`～`--dur-3`；換頁淡入、頁首區上浮與跨頁轉場只在桌面，860px 以下與 `prefers-reduced-motion` 時全部關閉。
- 新增顏色或動態一律先加參數，元件只引用參數；元件外觀寫在該元件原本的規則（1.34.4 起已合併），
  檔尾「設計系統 2.0」段落只留必須排在其他元件規則之後才能生效的少數覆蓋。
- 同一選擇器只寫一處。不同寬度的調整寫在 `@media` 內，且必須排在基礎規則之後；
  在後面再寫一次無條件的同選擇器規則，會讓前面的 `@media` 調整失效（1.34.4 頁首超出即此原因）。
- 斷點成對時，手機側寫 `max-width: 860px`，桌面側寫 `min-width: 860.02px`（不寫 `861px`），
  避免 Windows 縮放產生的小數寬度落在兩者之間；JS 判斷寬度用同一個 `matchMedia`，不用整數 `innerWidth`。
- 手機共用基礎（T-226，`app.css` 檔尾，只在 860px／600px 以下）：
  - 欄位（input、select、textarea）一律 16px，低於 16px 時 iPhone 點欄位會自動放大畫面；元件不要再把欄位字級調小。
  - 欄位、下拉、篩選列按鈕同高 `--control-h`（44px）。
  - 600px 以下頁首按鈕群組（`hero-actions`）每顆至少半列寬、不換行；字太長放不下半列時自己滿寬一列，每列都是等寬兩顆或一顆。
  - 標題 `text-wrap: balance`、段落 `pretty`，減少孤字；不用 `word-break: keep-all`（中文沒有空格，會整句無法斷行）。
- 手機文字完整顯示（T-267，只在 860px／600px 以下，電腦版不變）：
  - 不用省略號、`line-clamp` 或固定窄欄把字藏起來；放不下就自然換行（`MobileTextTests` 檢查）。所有寬度共用的省略號規則，要在手機斷點改回完整顯示。
  - 標題列、摘要列右側的筆數與短按鈕不縮、不換行，左側說明自己換行；不能把右側擠成一字一行。
  - 單行欄位與下拉放不下時由 `phone-full-text.js` 處理：先佔滿整列，仍放不下就在下方補一行完整內容；提示文字先縮小（最小 12px），再放不下才整句移到欄位下方。
  - 手機上全螢幕的面板（例如訂單總覽）頂端要有固定的「← 返回」（44px、避開瀏海 `env(safe-area-inset-top)`），返回手勢只關面板、不離開頁面。
  - 驗收：`tools/ui_audit/mobile_text_audit.py` 在 375／390 量水平溢出、被藏的文字、一字一行與被拆開的短標籤；電腦版用 `snapshot_compare.py` 前後逐像素比對。
- 訂單總覽區塊位置固定（T-289、T-307）：不用 CSS `columns` 瀑布流依卡片高度分欄；最上面「重點摘要」四格（車主、車輛、選號與領牌、汰舊，點了跳到該區，只顯示不進複製），下面卡片一列兩張、同列等高（`order_overview.OVERVIEW_PAIRS`），跳轉順序同卡片順序，窄版單欄順序不變；空白欄位留在原位改小字；備註是標題區的便條紙（彈窗由 JS 搬到標題，完整頁面在 hero；固定高度截斷，「看全文」浮層），不是卡片；「加購項目與贈品」是下方表格區第一張；「複製全部」的區塊順序維持 `sections`；所有區塊、區塊內欄位列與明細表每張單一律輸出（T-292，含車行獎勵／汰舊／取消與退款、其他費用／補助項目；沒資料顯示「—」或空狀態），不因付款方式、來源、汰舊、加購增減；只有權限（收支）會少列。
- 品質檢查：每次調整外觀，以 6 種主題 × 24 個代表頁量文字對比（一般字 ≥ 4.5、大字 ≥ 3），
  並檢查 375／390／1024／1440 寬度無橫向溢出（`?ui_audit=1` 會比對整頁 scrollWidth）；動到頁首時另掃 861–1400px。

## 頁面骨架

每個完整頁面依序是：

1. **導覽列**：`{% site_navigation %}` 依權限自動算出上一層；需要指定上一層時改用
   `{% include "sales/_page_back.html" with fallback_url=… label=… %}`。
   兩者擇一，不得再手寫 `← 返回…` 連結或按鈕。報表頁覆寫 `{% block report_nav %}`。
   返回列就是麵包屑：上一層以「← 名稱」膠囊強調，目的地固定，不用瀏覽器上一頁；
   `ui-navigation.js` 會帶回該列表在本分頁最後的篩選與捲動位置（不帶 `edit` 等一次性參數）。
   上一層是首頁時整列不顯示，手機只留「← 上一層」。只有錯誤頁用 `data-history-back` 退回上一頁。
   從哪來回哪去（T-291）：`sales/back_source.py` 的 `SOURCE_LABELS` 是可當來源的頁面與返回名稱；
   這些頁的 `<main data-link-source>` 點往其他頁時由 `ui-navigation.js` 補 `back_to`＝來源路徑與篩選，
   目的頁返回列改成「← 來源名稱」（來源就是上一層時只換網址），同頁篩選、分頁、pushState 一路帶著。
   `back_to` 只接受白名單頁的本站相對路徑，其餘照原階層。新增來源頁只改 `SOURCE_LABELS`，
   不在連結上手寫參數；不該帶來源的連結加 `data-no-back-to`。
   右下角懸浮鈕（T-297）：`base.html` 的 `{% page_dock %}`（`_page_dock.html`＋`page-dock.js`）全站一處，
   往下捲超過一個畫面才出現、回到半個畫面內隱藏；「↑」回頂端並把焦點移到 `#main-content`（減少動態用 `instant`）。
   「← 來源名稱」只在返回列有顯示來源時出現，由 `_page_back.html` 的 `page_dock_source` 記下同一組網址與名稱，
   不另判斷；訂單頁精簡列已有返回鍵，只放「↑」。層級 35，遇到底部固定或黏住的列由 JS 往上讓開；列印隱藏。
2. **頁首**：每頁只有一個 `h1`，放在標準頁首：

   ```html
   <section class="hero-row compact-hero">
     <div><p class="eyebrow">所屬區域</p><h1>頁面標題</h1><p class="muted">一句說明</p></div>
     <div class="hero-actions">…次要動作… <a class="button primary">主要動作</a></div>
   </section>
   ```

   模組需要不同排版時，在 `hero-row` 上加修飾 class（例如 `report-heading`），不另建頁首元件。
   確認頁與單卡片頁也一樣：標題放在卡片上方的頁首，卡片只放說明與表單。
3. **分頁**：同一物件的多個設定頁用 `account-tabs`。
   機種的各項設定共用 `sales/_vehicle_model_workspace.html`（頁首＋分頁列取代標準頁首與返回列，
   樣式在 `static/css/vehicle-model-workspace.css`，頁面以 `_vehicle_model_workspace_head.html` 載入）；
   新增機種相關設定頁時加入此工作區，送出後導回同一分頁。
   「傭金與獎勵」「結算成本」「原廠獎勵與補助」三個分頁只顯示、不收 POST，設定在各自的專屬頁（T-286）。
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

## 篩選與查詢

- **列表頁**：設好條件，按「套用」才查。篩選表單的送出按鈕一律叫「套用」，排在「清除」之後；
  下拉、勾選、打字都不自動送出（不寫 `onchange` 送出、不用 JS 打字就查）。
- **報表中心、選車頁**：維持選了就自動查（報表中心規則見 T-142）。
- **例外，維持選了就換**：只有一個關鍵字欄位的純搜尋框，按鈕維持「搜尋」；「每頁顯示」這類檢視設定；
  切換「看哪一份資料」的控制項（價格表分發「月份」、套表列印「範圍」）；
  為了重新載入下一層選項的連動（價格表「縣市」→「行政區」）。
- 新頁面照這條；要例外時寫在該頁模板註解並加進上面的例外清單。

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
    本店公司資料未設定、車輛改回現有庫存；清單見 `test_confirm_pages_share_confirm_panel`。
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
- 上傳、刪除、歸類檔案與留在原頁的整張表單儲存，不重新整理、不捲動（1.86.19）：會變動的區塊加 `id` 與 `data-inplace-region`，
  表單加 `data-inplace-form`，由 `inplace-regions.js` 送出並把導回頁面的同 id 區塊換進畫面（錨點區塊維持螢幕位置、焦點留在原處）。
  伺服器照舊驗證後導回並帶 messages；錯誤訊息或同網址重新顯示時，原表單與已選檔案保留。
  會改動多個步驟的動作（訂金入帳、完成交車等）加 `data-inplace-success="reload"`：失敗原地顯示，成功後重新載入回到原分頁與位置。
  換入區塊內的元素若有腳本綁定，監聽 `inplace:updated` 重新綁定。
  上傳可能連帶改動訂單或收支（例如最後一份領牌文件自動完成領牌）：訂單頁沒被換掉的自動儲存表單在 `inplace:updated` 時
  從新頁面取現值與版本號做三方合併，交車區塊（`#delivery-stage`）整塊換新（T-92）。

## 空狀態與表格

- 沒有資料時用 `empty-state`：
  `<div class="empty-state">[<span class="empty-state__icon" aria-hidden="true">＋</span>]<h3>標題</h3><p>說明與下一步</p>[按鈕]</div>`；
  區塊內較小時加 `small`。
- 所有資料表格一律 `inventory-table-wrap` 包 `table.inventory-table`：表頭淡底、13px 粗體，儲存格 14px、
  上下 12px 內距、列間細線、滑過淡底。欄位少、放在區塊內的小表加 `inventory-table--fit`（不強制 1080px 寬）。
  可水平捲動的表格外層需有 `tabindex="0"` 與 `aria-label`。
- 每個 `td` 帶 `data-label`：600px 以下自動變成卡片，欄名在上、值在下（兩格並排的小格，T-267）；操作欄加 `inventory-row-action` 橫跨整列，名稱、備註這類長欄位用 `grid-column: 1 / -1` 佔整列。
  列標題用 `tbody th`（例：月份、車型），手機版會成為卡片標題。
- 數字欄在 `th` 與 `td` 加 `is-number`：右對齊、等寬數字。
- 對齊：表格直接放在無內距面板（`section-block`、`inventory-list-panel`）時，首尾欄內距等於卡片內距；
  放在有內距卡片（報表面板、營運走勢、已刪除訂單、系統管理頁）時，表格延伸到卡片左右邊緣，首尾欄文字仍與標題對齊。不自行覆寫表頭顏色或內距。
- 例外：列印文件（`contract_print`）、報表閱讀器的 `report-results`（沿用同一組表頭顏色與線條）、
  價格表分工的拖曳排序表（`price-assignment-table`，表頭與儲存格數值同資料表）。

## 側邊把手導覽

有階段或需要大量捲動的頁面，使用共用側邊把手 `sales/_side_nav.html`（`side-nav.js`）：各段加 `data-side-nav-section="名稱"` 即自動產生目錄與捲動標示；
流程頁以 `nav_include` 放入既有步驟元件。行為比照機種清單：左側滑出、寬螢幕可釘選（依 `nav_key` 記住，首次預設釘選）、快捷鍵 `[`。手機（860px 以下）把手是頁首左側 44px 高的膠囊（`--nav-handle-width`），面板從頁首下方滑出，頁首品牌只留圖示讓位；不放在左下角，避免貼著底部操作列的刪除類按鈕或壓在內容上（UAT U-12）。手機操作列的刪除類按鈕與其他按鈕至少隔 16px。
捲動標示取頂端越過標頭下方判定線的最後一段；捲到頁底改標最後看得到的段落（頁尾短段落也點得到），點目錄後鎖定該段直到捲動停下。
訂單頁步驟（`_order_step_nav.html`）與機種清單為同類元件。訂單頁的工作入口只放左側步驟（收入與支出、列印與簽署文件等），頁首不重複放同功能按鈕、也不另列「下一步建議」卡；頁首右側只放訂單來源與台數歸屬小卡（變更以浮層展開，訂單來源欄位以 `form="order-form"` 併入訂單自動儲存）與刪除／退車這類單張訂單處置，頁首不黏住、不縮放；捲走後由疊在高度為 0 的 sticky 定位點上的精簡列（`order-compact-bar.js`）淡入，不改變版面高度、不墊高補位，精簡列不放刪除按鈕。精簡列最左邊是返回鍵：與麵包屑同一目的地，同樣用 `data-return-to` 帶回列表篩選與捲動位置，不另寫返回邏輯；1100px 以下只留 44px 圖示鍵（`aria-label`），600px 以下精簡列分兩行（返回／姓名／狀態，下面是儲存狀態／算給誰／變更），不刪內容（T-214）。手機（860px 以下）精簡列常駐頂端、不淡入也不縮小，最下一行是「第 N／7 步・點這裡換步驟」鈕與「總覽」鈕；換步驟用底部面板（`order-step-sheet.js`：訂單總覽、七步與狀態、其他；「正在看」與訂單進度「目前進度」分開標示），左上角把手收起（`order-nav--sheet`）；訂單維護頁不做上一步／下一步，步驟以 `scroll-margin-top` 停在精簡列下方（T-250）。頁首的大名稱、狀態與儲存狀態在手機版只留給讀屏（視覺隱藏），備註便條與車行小卡照常顯示（T-251）。左側步驟一律瞬間停在該區頂端（標頭與精簡列下方），不在頁尾補空白湊停點（2026-10-20、10-21）。姓名下方依序列電話 → 車型 → 車色 → 車牌號碼 → 引擎號碼／車身號碼，配車前的空值合成一格淡色「配車後顯示」，不列一排「未填」（10-21 T-42）。訂單頁的明細表單集（`OrderPage*FormSet`）不多一列空白；其他費用在左側「訂金與費用」步驟，欄位以 `form="order-form"` 併入訂單自動儲存，訂單表單不帶訂金欄位（T-43、T-44）。「訂車與配件」最後一區是「新車主資料」，附件只在左側「附件」。配件明細用精簡列（`_order_accessory_row.html`，建單精靈與訂單頁共用）：依配件區寬度以 container query 排版，寬版一個配件一列、欄名放表頭，刪除與備註鈕同列，備註需要時才展開；分期方案選擇列的按鈕併在同列右側，自訂分期時公司選單延伸、不留空白（10-21 T-50、T-51）。
需要自訂目錄時也用 `nav_include`：「機種與售價」放入 `_vehicle_model_list_nav.html`（品牌 → 機種，`vehicle-model-list-nav.js` 負責展開品牌、跳到該列、搜尋與目前位置）。

## 例外

錯誤頁、登入／強制改密碼、使用說明、公告閱讀頁、帳號權限工作區（`permissions/_header.html`）、
報表閱讀器與列印文件有獨立版面，不套用標準頁首，但仍須使用設計參數、按鈕等級與共用返回列。
例外清單維護在 `test_ui_consistency.py` 的 `HERO_EXEMPT`／`ACTION_ORDER_EXEMPT`。
