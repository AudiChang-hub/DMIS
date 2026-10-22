# Handoff

更新日期：2026-10-17

## 本次完成

全專案盤點結案：正式站 1.85.4（`439dda9`）與 main 一致、CI 全綠；各工作階段皆已完成。使用者 2026-10-17 的決定已寫入 [CURRENT_STATE](CURRENT_STATE.md) 與 [BUSINESS_RULES](BUSINESS_RULES.md)（車行單掛帳記客戶應收尾款不扣傭金、本店單指定車行不算基礎傭金、車行結算全員可看、不設預設店別、簽名 PDF 不另實測、不使用 Email 通知）。教學影片工具 `tools/tutorials/` 已提交保留。

10-02 舊交接項目結案：官網檢查排程每週一正常執行；五組訂單合併因 2026-10-05 正式資料清空而不再適用；簡訊／LINE 通知使用者未要求；`claude/code-setup` 分支（`07deedc`，舊版 AI 工具文件，已被 main 取代）已刪除本機與遠端。已合併的殘留 worktree 已移除。

## 修改檔案

docs/context/CURRENT_STATE.md、docs/context/BUSINESS_RULES.md、docs/context/HANDOFF.md、tools/tutorials/；未改應用程式、正式資料或部署。

## 驗證結果

- `python -m unittest discover -s tests/context` 通過；今日各次推送 CI 皆通過。
- 正式站 SSH 唯讀核對：HEAD `439dda9`、web healthy、`/health/` 回 ok；帳號權限 admin／morris／nina／Sylvia 皆有收支權限；目前無掛帳中訂單、無車行設額度。
- 教學工具已在本機暫存環境試跑示範資料建立成功；完整錄影未跑。

## 尚未完成

無待接手工作。

## 已知風險

- 多個工作階段可能同時發布；發布前先查 `gh run list` 與正式站 deployed-sha，避免重複打標籤或部署。
- 教學錄影腳本 `scenarios/open_order.py` 寫於建立訂單改為多筆付款前，重錄前先試跑核對選擇器。
- 正式主機 SSH：`ssh -i "C:/Users/user/.ssh/line_monitor_ubuntu_ed25519" -o IdentitiesOnly=yes -o BatchMode=yes t470p "<指令>"`；專案目錄 `/home/audi/project/DMIS-next`；僅限已授權維運。

## Rollback 注意事項

- T-96 統一撥款對帳（2026-10-22）：
  - 回到上一版：部署上一版，反向 migration 0196 只刪除未入帳、金額 0 的平台撥款列。14760B 重算後的預計撥款 28,800 保留，不還原。
  - 已入帳的平台單：如果平台撥款已在對帳頁入帳過才 rollback，舊版不認得平台撥款列（`system_key=platform_disbursement`）。之後該訂單只要再同步一次收款，收支的「實際車價收入」就會還原成入帳前的人工值。
  - 做法：rollback 前先唯讀列出已入帳的平台撥款列，回舊版後逐張到收支人工重填；否則不要 rollback，改以修正版往前修。

## 下一步

等使用者新需求；從 [AGENTS](../../AGENTS.md) 路由定位，不自動寫入正式資料。

## 下一位 Agent 建議先看

[CURRENT_STATE](CURRENT_STATE.md)、[BUSINESS_RULES](BUSINESS_RULES.md) 財務與訂單小節。
