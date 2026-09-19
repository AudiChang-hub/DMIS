# Context 架構驗證

日期：2026-09-19；基準提交 9b83d43。僅開發環境，不代表應用重新發布。

## 結果

| 檢查 | 結果 |
| --- | --- |
| `python -m unittest discover -s tests/context -v` | 8 項通過 |
| `python -m py_compile tools/context_lookup.py tests/context/test_context_policy.py` | 通過 |
| `python scripts/check_release.py` | 通過；應用 1.11.0 未變 |
| 有效檔案 `git diff --cached --check -- . ':(exclude)docs/archive/2026-09-19/**'` | 通過；封存原文的三行既有尾端空白刻意保留，不改寫歷史 |
| 封存原文 | 15 份與基準 Git 內容核對一致，manifest 保存正規化 SHA-256 |
| 全域設定差異 | 僅新增 tool_output_token_limit 和 node_repl enabled_tools；原模型、hooks、pipe 等不變 |
| 全域備份 | 原 AGENTS 7519 bytes、config 4178 bytes；複製後 SHA-256 已核對 |
| Codex config/read | project layer 未被停用；4096、並行 2、指定插件停用與 cua 白名單有效 |
| Codex skills/list | 本機新 CLI 12 份、零載入錯誤；不等於所有 Desktop 平台注入數量 |
| 新工作階段實際定位 | SUI／importer 均正確；最終回歸只一次 shell 操作，輸出約 6.9k 字元，未展開整個 models／migrations |

## 閱讀預算

全域 AGENTS 約 2 KiB、專案 AGENTS 約 4 KiB、CURRENT_STATE 約 1.6 KiB；三者合計低於 10 KiB。
README 從原 14,892 bytes 改為 1,956 bytes；完整內容按需轉往 reference 或 archive，沒有靠刪備份達成。
這是檔案 bytes，不是實際模型 token 或費用保證；工具固定提示、模型、快取及平台記憶仍影響消耗。

## 實際測試發現與修正

1. 單在專案層補 node_repl whitelist 而沒有 transport，config/read 可合併但 strict-config 報 invalid transport。
   已將白名單移到既有全域 transport 同層，不在 repo 寫死使用者機器路徑。
2. 最初只靠自然語言「少讀檔案」仍出現過量搜尋。已補明確範圍，建立兩個 bounded 定位器；
   最終新 CLI 對使用者短需求，從 CURRENT_STATE 直接執行兩個定位器並停止，沒有依賴提示額外指定檔案。
3. 全域 CLI 原模型 gpt-5.3-codex-spark 被帳號拒絕。保留永久設定，驗收僅命令列指定可用的 gpt-5.6-sol。
   這是既有設定問題，不冒稱預設 CLI 已可直接啟動。
4. 新 CLI 仍回報供應商技能 icon 相對路徑警告及 PowerShell snapshot 不支援；不影響本次定位，未修改供應商 cache。

## 可重現的代表任務

新開唯讀工作階段，使用帳號目前支援的模型，分別或合併詢問：

> 幫我修改 SUI 顏色問題／幫我修正 importer bug。這次僅驗收唯讀定位，沒有額外錯誤細節，不改檔、不碰資料庫、不開瀏覽器。

應先定位目前規則、執行對應 helper，指出相關入口與需要的重現資訊；不得擅自更改車色或唯一鍵。
任務模糊時不可把「找得到入口」宣稱「bug 已修復」。

## 未執行與回復

沒有 migration、正式資料異動、訂單合併、應用部署或完整 Django／實機測試。
全域檔案與 repo 的回復方法見 [工具政策](AI_TOOL_POLICY.md)。
本次透過獨立分支保存，不會因完成文件工作就合併 main 或重新發布正式應用。
