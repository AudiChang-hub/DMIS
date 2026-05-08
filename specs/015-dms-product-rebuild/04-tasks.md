# 04 — Tasks：新一代產品管理模組重建（015-dms-product-rebuild）

## Phase 1：Spec / Clarify

- [x] 完成 `specs/015-dms-product-rebuild/00-charter.md`
- [x] 完成 `specs/015-dms-product-rebuild/01-spec.md`
- [x] 完成 `specs/015-dms-product-rebuild/02-clarify.md`
- [x] 完成 `specs/015-dms-product-rebuild/03-plan.md`
- [x] 完成 `specs/015-dms-product-rebuild/04-tasks.md`
- [x] 完成 `specs/015-dms-product-rebuild/05-acceptance.md`
- [x] 確認 legacy `name/model` → `機種/型式/型號` migration 規則

## Phase 2：新模組骨架

- [x] 建立 `addons/dms_product/__init__.py`
- [x] 建立 `addons/dms_product/__manifest__.py`
- [x] 建立 `addons/dms_product/models/__init__.py`
- [x] 建立 `addons/dms_product/views/`
- [x] 建立 `addons/dms_product/security/`
- [x] 建立 `addons/dms_product/tests/`

## Phase 3：Canonical 模型

- [x] 建立 `models/product_template.py`
- [x] 建立 `models/price_version.py`
- [x] 建立 `models/price_line.py`
- [x] 建立 `models/installment_rule.py`
- [x] 建立 `models/installment_rule_line.py`
- [x] 建立 `models/fee_type.py`
- [x] 建立 `models/installment_rule_fee.py`
- [x] 建立 `models/installment_rule_binding.py`

## Phase 4：相容層

- [x] 建立 `models/product_compat.py`，以 `_inherit = 'dms.product'` 擴充產品項欄位
- [x] 建立 migration / backfill 邏輯（template、internal_code、production_year）
- [x] 調整 `internal_code` 自動生成規則為「型號 + 出廠年份」，衝突時自動補尾碼
- [x] 將 `production_year` 改為文字欄位，避免年份被格式化為千分位顯示
- [x] 若有 legacy 價格資料，建立 price version / price line backfill
- [x] 若有 legacy installment plan 資料，建立 rule / rule line backfill

## Phase 4-1：拜訪模組脫鉤

- [x] 調整 `addons/dms_visit/models/visit_item.py`，讓送出物品不再必須綁定 `dms.product`
- [x] 調整 `addons/dms_visit/views/visit_views.xml`，改以可獨立輸入送出物品為主
- [x] 調整 `addons/dms_visit/tests/test_visit.py`
- [x] 驗證拜訪清單 / 拜訪表單仍可正常建立送出物品

## Phase 5：視圖與選單

- [x] 建立產品模板 tree / form / search
- [x] 將產品項維護收斂到產品模板表單的產品項頁籤，不提供獨立入口
- [x] 讓模板頁籤中的停用產品項仍可見並可重新啟用
- [x] 讓 `sku_ids` 關聯本身包含停用資料，避免模板頁籤與產品項數量不一致
- [x] 將模板 `產品項數量` 調整為僅統計啟用中的產品項
- [x] 在模板頁籤加入產品項列級複製動作，支援快速建立新年份產品項
- [x] 在模板頁籤加入產品項列級「維護顏色」入口，讓使用者逐列新增顏色而非手打頓號
- [x] 移除模板表單中的「產品顏色」頁籤，避免與列級維護入口重複
- [x] 收斂維護顏色彈窗，移除 `color_code`、`相容欄位`、`圖片（相容）`
- [x] 修正產品顏色刪除 / 停用後的可售顏色摘要同步
- [x] 修正產品項複製時的 `internal_code` 重生流程，避免前台誤觸唯一鍵錯誤
- [x] 修正產品項列級複製後的回傳動作，避免 breadcrumb 重複堆疊
- [x] 修正模板頁籤刪除產品項時的 FK 行為，讓未被引用的產品項可直接刪除
- [x] 為產品模板補上可見的「複製」動作
- [x] 建立價目版本 tree / form / search
- [x] 建立價格基準 tree / form / search
- [x] 移除獨立「價格基準」選單，統一由價目版本頁籤維護
- [x] 調整產品項顯示名稱，於選取下拉中顯示 `內部代碼 / 車種`
- [x] 建立價目版本批次加入產品項精靈，支援多選一次建立多筆價格列
- [x] 讓批次加入精靈可同時輸入統一現金價與牌價
- [x] 為價目版本補上可見的「複製」動作
- [x] 複製價目版本時一併複製價格基準，並重設新版本名稱與狀態
- [x] 建立分期規則模板 tree / form / search
- [x] 建立費用類型 tree / form / search
- [x] 建立規則掛接 tree / form / search
- [x] 建立頂層 `產品管理` App 選單
- [x] 規劃並實作舊 `dms_sale` 產品 / 價目入口的相容處理

## Phase 6：最小必要交易相容

- [x] 更新 `dms_sale` 查價邏輯，優先讀新價格結構
- [x] 保留 legacy `dms.vehicle.price` fallback
- [x] 驗證 `dms_visit` 在脫鉤後仍可正常記錄送出物品
- [x] 驗證 `dms_finance` 測試不受影響

## Phase 7：測試

- [x] 新增 `addons/dms_product/tests/test_product_template.py`
- [x] 新增 `addons/dms_product/tests/test_product_price.py`
- [x] 新增 `addons/dms_product/tests/test_installment_rule.py`
- [x] 新增 `addons/dms_product/tests/test_migration_compat.py`
- [x] 執行 `dms_product` 模組安裝測試
- [x] 執行 `dms_product` 模組升級測試
- [x] 執行 `dms_sale` 回歸測試
- [x] 執行 `dms_visit` 回歸測試
- [x] 執行 `dms_finance` 回歸測試
- [x] 執行 `user_management` 回歸測試

## Phase 8：產品項與顏色收斂修正

- [x] 將 `dms.product` 從「年份 + 顏色」收斂為「模板 + 出廠年份」產品項
- [x] 將顏色正式收斂到 `dms.product.color`
- [x] 在產品模板表單加入顏色維護頁籤
- [x] 將價目版本 / 價格基準的選取改為年份產品項，不再依顏色拆分
- [x] 將規則掛接改為綁定年份產品項，不再依顏色拆分
- [x] 補產品資料 consolidation migration，將同模板同年份的多色產品項合併
- [x] 補 `dms_sale` 顏色選擇回歸驗證
- [x] 補 `dms_product` 顏色 / 產品項新結構測試
- [x] 執行 smoke 測試

## Phase 8：文件與交付

- [x] 更新 `README.md`
- [x] 更新 `SETUP.md`
- [x] 更新 `docs/USER_MANUAL.md`
- [x] 更新 `docs/erd.md`
- [x] 更新 `specs/000-roadmap/01-module-map.md`
- [x] 更新 `specs/000-roadmap/02-master-checklist.md`
- [x] 更新 `specs/006-dms-sale/**`
- [x] 更新 `specs/011-dms-visit/**`
- [x] 視需要更新 `specs/014-module-removal/**` 歷史註記
## Phase 9：修復 installment_plan_id _unknown comodel 錯誤

- [x] 診斷根本原因：`dms_sale`（17/43）比 `dms_product`（41/43）早載入，
  導致 `Many2one.setup_nonrelated()` 在 comodel 不在 pool 時永久設為 `_unknown`
- [x] 在 `dms_sale/models/product_installment_line_proxy.py` 宣告空殼 `_name = 'dms.product.installment.line'`，
  確保 `installment_plan_id` field setup 時 comodel 已存在
- [x] 在 `dms_product/models/product_installment_line.py` 改為 `_inherit`，
  由後載入的 `dms_product` 補充完整欄位與商業邏輯
- [x] 驗證 onchange RPC 無 `_unknown` 錯誤

- [ ] 以繁體中文 commit
- [ ] push 到 remote branch
- [ ] 整理 PR 標題與描述（繁體中文）

## Phase 10：價格表 UI 與資料維運（2026-04-29 補強）

- [x] 在價格表 tree 與產品頁面 tree 加入「開啟詳細資料」按鈕（`action_open_form`），保留 inline 編輯同時支援切換到 form 編修
- [x] 修正價格表品牌欄位下拉被相鄰 sticky 欄遮擋（`pricelist_sticky.css`：`td.o_sticky_col:focus-within{z-index:10}`、`.o-autocomplete--dropdown{z-index:1080}`）
- [x] 修正 `addons/dms_core/views/brand_views.xml` 中 image tree widget 非法 `width="40px"` 屬性（改為 `options="{'size':[40,40]}"`），消除 OwlError `Invalid props for component 'ImageField'`
- [x] 將「品牌」選單改為僅 `base.group_system`（系統管理員）可見，並清除 dmis_dev 殘留的 `DMS/車行管理者` 綁定
- [x] 將型號為 `EV0*` 的 7 筆產品（eReady 系列）品牌統一修正為「台鈴 Suzuki」（其中 6 筆原誤標為「宏佳騰 Aeon」）
- [x] 價格表整體排版調整：標題列字體縮為 12px、tbody 改 nowrap + 橫向捲動、長欄（顧客贈品/附加費用說明/車色）改 `pre-line` 完整顯示並自動撐高列高

## Phase 11：eReady Fun 命名統一（2026-05-08）

- [x] 更新 `specs/015-dms-product-rebuild/01~05`，定義 `EV062` / `EV062FL` 的 canonical 機種名稱為 `eReady Fun`
- [x] 修正 `dms.sale.order.display_product_name` 的 stored compute 依賴，讓產品名稱異動時既有訂單可自動重算
- [x] 新增可重跑的資料修正方法 / 腳本，將 `EV062` / `EV062FL` 的模板機種、產品名稱與必要的歷史訂單顯示名稱統一為 `eReady Fun`
- [x] 更新 `scripts/create_missing_products.py`，避免未來再建立出 `eReady EV062` / `eReady EV062FL`
- [x] 補最小回歸測試，驗證產品改名後訂單顯示名稱會同步更新
- [x] 執行 Odoo 升級、重啟、`docker compose ps` 與 smoke 驗證
