# DMIS：AI 工作入口

Context 是索引，不是資料倉庫。這裡只放導航與必要限制。

## 開始工作

1. 先讀 [CURRENT_STATE](docs/context/CURRENT_STATE.md)，查看 `git status --short --branch`；保留他人的未提交修改。
2. 按下表定位。先搜尋，再讀取；先定位，再展開。只開相關函式、測試與規格，不遍讀 repository。
3. 只有「繼續／接手」才讀 [HANDOFF](docs/context/HANDOFF.md)。不從聊天歷史重建已整理的現況。
4. 找不到時才擴大一層搜尋；不得將所有 models、tests、migrations、specs 或 Git history 一次載入。
5. 初次定位每個檔案最多 150 行、單次工具輸出最多 2000 tokens；搜尋命中先取前 30 筆。大檔只讀命中函式前後 40–80 行，禁止用空字串／`^` 搜尋列出整檔。不批次 Get-Content 多份程式全文；找到候選入口即回報或深入該函式，不順手擴查整個 models／views。
6. 明確要求唯讀定位時，只需 CURRENT_STATE、相關規則段落、1–3 個入口／測試；不要為「完整了解」展開全部相依檔。必須完整閱讀的 Skill／指令是例外，按需分段讀到 EOF。
7. SUI／車色先執行 `python tools/context_lookup.py catalog`；importer 先執行 `python tools/context_lookup.py importer`。定位器提供有效規則、現行函式與測試名稱，沒有具體錯誤時到此停止，不額外掃描 models、migrations 或歷史。Windows 搜尋副檔名用 `rg -g '*.html' <符號> templates/sales`，不把萬用字元當實體檔名。

| 任務 | 第一個定位範圍 | 按需補充 |
| --- | --- | --- |
| SUI／選車／車色／展示 | `sales/catalog_views.py`、`templates/sales/catalog*.html` | `sales/tests/test_catalog_color_list.py`、`test_catalog_management.py` |
| importer／Excel 匯入 | `sales/services/legacy_import.py` | `test_legacy_import.py`、BUSINESS_RULES「Excel 匯入」 |
| 訂單／財務／權限／其他 | [模組索引](docs/architecture/MODULE_MAP.md) | 精確搜尋相關符號與對應測試 |
| 測試／安裝 | [開發驗證](docs/reference/DEVELOPMENT.md) | CI 是測試清單的來源 |
| 部署／備份 | [維運](docs/reference/OPERATIONS.md) | 只在部署任務讀取 |
| Skills／MCP／Context | [工具政策](docs/reference/AI_TOOL_POLICY.md) | 只有工具設定任務才讀盤點 |

## 修改邊界

- 唯一正式 runtime 是 Django；不要依歷史 Odoo／Metabase 指令啟動服務。
- 重大修改（schema、migration、importer 核心、商業規則、權限、API、核心模型、架構、大型重構、正式資料）先提出 A／B，列檔案、資料影響、驗證與 rollback，等明確選擇。已批准的範圍直接完成，不重複索取確認。
- 小型修正與測試可直接做；runtime／部署行為變更同步對應 specs，不為小改動硬建六份空文件。
- 財務、訂單與匯入異動先看 [有效商業規則](docs/context/BUSINESS_RULES.md) 的相關小節；不可擅自改公式、唯一鍵或正式資料。
- Django admin 只作唯讀查詢；業務寫入走具驗證、交易與稽核的服務。
- 不提交真實個資、附件、secret、DB、log、備份；不讀取無關客戶資料。不用破壞性 Git 或重啟資料庫解決部署問題。
- 應用交付依 [發布規範](docs/RELEASE_POLICY.md) 升版、測試、commit／push、部署與真實流程驗證；未驗證部分明說。本地 AI 規則／純文件整理不冒充應用升版，也不觸發正式部署。

## Context 維護

Hot 僅本檔與 CURRENT_STATE；商業規則、決策、模組索引與 reference 是 Warm；archive、舊 specs／PR、logs、備份是 Cold，僅追溯歷史才讀。
CURRENT_STATE 只描述現在。已失效資訊應 Archive。優先維持 Single Source of Truth。
改變現況／規則／重要決策才更新對應文件；有待接手工作才覆寫 HANDOFF，不累積工作日誌。
