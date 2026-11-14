# DMIS：AI 工作入口

本檔只放導航與必要限制，細節看連結文件。

## 開始工作

1. 讀 [CURRENT_STATE](docs/context/CURRENT_STATE.md)，執行 `git status --short --branch`；不動他人未提交的修改。
2. 依下表定位：先搜尋再讀取，只開相關函式、測試與規格；找不到才擴大一層。不一次載入全部 models、tests、migrations、specs 或 Git 歷史。
3. 讀取上限：每檔初讀 150 行、單次輸出 2000 tokens、搜尋先取前 30 筆；大檔只讀命中處前後 40–80 行。不用空字串或 `^` 搜尋列整檔，不一次讀多份程式全文。
4. 唯讀定位只需 CURRENT_STATE、相關規則段落與 1–3 個入口或測試。指定要完整閱讀的 Skill／指令例外，分段讀到結尾。
5. SUI／車色先跑 `python tools/context_lookup.py catalog`，importer 先跑 `python tools/context_lookup.py importer`；沒有具體錯誤時，看完輸出就停。Windows 依副檔名搜尋用 `rg -g '*.html' <符號> templates/sales`。
6. 只有接手未完成的工作才讀 [HANDOFF](docs/context/HANDOFF.md)；不從聊天歷史重建現況。

| 任務 | 先看 | 需要時再看 |
| --- | --- | --- |
| SUI／選車／車色／展示 | `sales/catalog_views.py`、`templates/sales/catalog*.html` | `sales/tests/test_catalog_color_list.py`、`test_catalog_management.py` |
| importer／Excel 匯入 | `sales/services/legacy_import.py` | `test_legacy_import.py`、BUSINESS_RULES「Excel 匯入」 |
| 畫面樣式／操作流程 | [UI 規範](docs/reference/UI_GUIDELINES.md)、`static/css/app.css` | `sales/tests/test_ui_consistency.py` |
| 訂單／財務／權限／其他 | [模組索引](docs/architecture/MODULE_MAP.md) | 搜尋相關符號與對應測試 |
| 測試／安裝 | [開發驗證](docs/reference/DEVELOPMENT.md) | 測試清單以 CI 為準 |
| 部署／備份 | [維運](docs/reference/OPERATIONS.md) | 僅部署任務 |
| Skills／MCP／Context | [工具政策](docs/reference/AI_TOOL_POLICY.md) | 僅工具設定任務 |

## 修改邊界

- **鐵律：只改要改的標的。** 不得影響其他畫面、流程、樣式、資料或共用元件；必須動共用部分，先列影響範圍。波及非目標處即退版重修，不疊補丁。
- 修 bug 先找根因並補會重現問題的測試；同類問題列出回報，修不修由使用者決定。提交前看 `git diff`，只含標的。
- 重大修改先提 A／B：schema、migration、importer 核心、商業規則（含公式、唯一鍵）、權限、API、核心模型、架構、大型重構、正式資料。列出檔案、資料影響、驗證與 rollback，等使用者選定；選定範圍內直接完成，不再重複確認。其餘小修正與測試可直接做。
- 財務、訂單、匯入異動先讀 [有效商業規則](docs/context/BUSINESS_RULES.md) 的相關小節。
- runtime 只有 Django，不用舊 Odoo／Metabase 指令啟動服務。業務寫入走有驗證、交易與稽核的服務；Django admin 只做唯讀查詢。
- 不提交真實個資、附件、secret、資料庫、log、備份；不讀與任務無關的客戶資料。部署出問題不用破壞性 Git 或重啟資料庫處理。
- 應用變更依 [發布規範](docs/RELEASE_POLICY.md) 升版、測試、commit／push、部署並在正式站驗證流程，沒驗證到的部分要明說；runtime 或部署行為改變時同步更新對應 specs，小改動不另建 spec。AI 規則與純文件修改不升版、不部署。
- 樣式依設計系統 2.0，全域「避免預設樣式」除外。

## Context 維護

- Hot（每次讀）：本檔與 CURRENT_STATE，合計 ≤ 8000 位元組、各 ≤ 5000，CI 會檢查。Warm（需要時讀）：商業規則、決策、模組索引、reference。Cold（只在追溯歷史時讀）：archive、舊 specs／PR、log、備份。
- CURRENT_STATE 只寫現況；失效內容移到 archive，同一事實只留一處。
- 現況、規則或重要決策改變才更新對應文件；有待接手的工作才覆寫 HANDOFF，不累積工作日誌。
