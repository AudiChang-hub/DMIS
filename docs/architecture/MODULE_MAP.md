# 按任務定位模組

這是 Warm 索引，不是每次必讀；先在列出的範圍搜尋符號，再讀相關上下文。

| 問題 | 程式／畫面定位 | 主要測試 |
| --- | --- | --- |
| SUI 顏色、展示與篩選 | `sales/catalog_views.py`、`templates/sales/catalog.html`、`catalog_detail.html`、`catalog_manage.html`、`catalog_edit.html` | `test_catalog_color_list.py`、`test_catalog_management.py` |
| 原廠車型比對（官網檢查、補圖） | `sales/official_catalog_views.py`、`sales/services/official_catalog.py`、`templates/sales/official_catalog.html` | `test_official_catalog.py` |
| 機種沿用建立／批次調整／批次套用附加獎勵 | `sales/vehicle_model_tool_views.py`、`sales/services/vehicle_model_copy.py`、`vehicle_model_batch.py`、`vehicle_model_reward_batch.py`、`templates/sales/vehicle_model_copy.html`、`vehicle_model_batch.html`、`vehicle_model_reward_batch.html` | `test_vehicle_model_copy.py`、`test_vehicle_model_batch.py`、`test_vehicle_model_reward_batch.py` |
| 車色／分期帶入填單 | `sales/services/catalog_selection.py` | `test_catalog_selection.py`；`tests/frontend/catalog-payment.test.cjs` |
| Excel 匯入 | `sales/services/legacy_import.py`、`legacy_finance.py` | `test_legacy_import.py`、`test_legacy_finance.py` |
| 訂單三頁籤／收支 | 在 `sales/`、`templates/sales/` 搜尋 `workspace`；自動儲存驗證後的存檔與連動在 `sales/services/order_save.py`（訂車與配件、收支各區段、汰舊補助，畫面與之後的回匯共用）；規格 `specs/043-order-workspace/` | `tests/frontend/order-workspace.test.cjs`；`test_order_save_parity_t232.py`（存檔前後對照）；以 `rg --files sales/tests -g '*workspace*'` 定位 |
| 套表列印（信封、減徵貨物稅聲明書、簽收單，取代 Excel＋Word 合併列印） | `sales/form_print_views.py`、`sales/services/form_print.py`（A4 版面座標、信封 Word 檔、欄位對照 `FORM_FIELD_SOURCES`）、`sales/form_templates/envelope/`（信封 Word 原稿內文與樣式）、`templates/sales/form_print.html`、`static/js/form-print.js` | `test_form_print.py` |
| 訂單匯出（自選欄位、預覽；之後的回匯批次修改） | `sales/order_exchange/`（`columns.py` 欄位與可回匯標記、`scope.py` 範圍同全部訂單頁、`workbook.py` xlsx 版面、`views.py`）、`templates/sales/order_exchange/export.html`、`static/js/order-export.js`；匯出紀錄 `OrderExportRecord` | `test_order_export_t232.py` |
| 訂單修正／刪除 | 在 `sales/` 搜尋 `completed_order`、`deletion`；不先載入整個 models | `test_completed_order_corrections.py`、`test_order_deletion.py` |
| 畫面授權／帳號與訂單範圍 | `sales/access/`、`sales/permission_workspace.py`；搜尋 `screen_access` | `test_screen_access.py`、`test_catalog_accounts.py`、`test_customer_order_access.py` |
| 報表／機種分類 | 在 `sales/` 搜尋 `report_classification`、`reporting` | `test_reporting.py`、`test_report_classification.py` |
| 使用說明（T-197 新版，文章單一來源） | `sales/help/articles*.py`（內容）、`schema.py`（格式）、`views.py`、`templates/help/`；`docs/USER_MANUAL.md` 由 `manage.py build_user_manual` 產生；截圖 `static/help/screens/` 由 `tools/help_screens/run.py` 依合成資料（`seed_help_demo`）重拍 | `test_help_articles_t197.py` |
| 發布版號 | `config/release_notes.py`、`scripts/check_release.py` | [發布政策](../RELEASE_POLICY.md) |
| 部署 | `scripts/deploy_django.sh`、`docker-compose.django*.yml` | [維運文件](../reference/OPERATIONS.md) |

表內未寫前綴的 Python 測試均在 `sales/tests/`。不知道名稱時先 `rg --files <範圍> -g '*關鍵字*'`，再 `rg -n '<符號>' <檔案>`。

## Source of Truth

- 業務資料結構：相關 Django model 與 migration；只讀涉及欄位及其遷移。
- 行為：服務實作＋目前測試；規格描述意圖，歷史 specs 不凌駕已確認的新需求。
- 現況：[CURRENT_STATE](../context/CURRENT_STATE.md)；規則：[BUSINESS_RULES](../context/BUSINESS_RULES.md)。
- 舊 ERD 不代表現行 Django schema；需要整體新 ERD 時另立任務，不在每次 bugfix 產生。
