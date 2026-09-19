# 按任務定位模組

這是 Warm 索引，不是每次必讀；先在列出的範圍搜尋符號，再讀相關上下文。

| 問題 | 程式／畫面定位 | 主要測試 |
| --- | --- | --- |
| SUI 顏色、展示與篩選 | `sales/catalog_views.py`、`templates/sales/catalog.html`、`catalog_detail.html`、`catalog_manage.html`、`catalog_edit.html` | `test_catalog_color_list.py`、`test_catalog_management.py` |
| 車色／分期帶入填單 | `sales/services/catalog_selection.py` | `test_catalog_selection.py`；`tests/frontend/catalog-payment.test.cjs` |
| Excel 匯入 | `sales/services/legacy_import.py`、`legacy_finance.py` | `test_legacy_import.py`、`test_legacy_finance.py` |
| 訂單三頁籤／收支 | 在 `sales/`、`templates/sales/` 搜尋 `workspace`；規格 `specs/043-order-workspace/` | `tests/frontend/order-workspace.test.cjs`；以 `rg --files sales/tests -g '*workspace*'` 定位 |
| 訂單修正／刪除 | 在 `sales/` 搜尋 `completed_order`、`deletion`；不先載入整個 models | `test_completed_order_corrections.py`、`test_order_deletion.py` |
| 畫面授權／車行帳號 | 在 `sales/` 搜尋 `screen_access`、`catalog_accounts` | `test_screen_access.py`、`test_catalog_accounts.py` |
| 報表／機種分類 | 在 `sales/` 搜尋 `report_classification`、`reporting` | `test_reporting.py`、`test_report_classification.py` |
| 發布版號 | `config/release_notes.py`、`scripts/check_release.py` | [發布政策](../RELEASE_POLICY.md) |
| 部署 | `scripts/deploy_django.sh`、`docker-compose.django*.yml` | [維運文件](../reference/OPERATIONS.md) |

表內未寫前綴的 Python 測試均在 `sales/tests/`。不知道名稱時先 `rg --files <範圍> -g '*關鍵字*'`，再 `rg -n '<符號>' <檔案>`。

## Source of Truth

- 業務資料結構：相關 Django model 與 migration；只讀涉及欄位及其遷移。
- 行為：服務實作＋目前測試；規格描述意圖，歷史 specs 不凌駕已確認的新需求。
- 現況：[CURRENT_STATE](../context/CURRENT_STATE.md)；規則：[BUSINESS_RULES](../context/BUSINESS_RULES.md)。
- 舊 ERD 不代表現行 Django schema；需要整體新 ERD 時另立任務，不在每次 bugfix 產生。
