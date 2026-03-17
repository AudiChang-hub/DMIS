# 00 — Charter：報表規則設定模組（dms_report_rule）

## 宗旨

讓管理者與分析人員無須修改程式碼，即可在系統介面自行定義「報表規則」——包含資料模型、分析維度、數值指標、圖表類型及篩選條件——並即時預覽、儲存與共享，實現類似 Looker Studio 的動態 BI 報表體驗。

## 範圍

- 新增 `dms_report_rule` 模組於 `addons/dms_report_rule/`。
- 依賴 `dms_report` 模組，在「報表分析」主選單下新增「報表規則」子選單。
- 核心模型 `dms.report.rule`：儲存報表名稱、指定資料模型、維度欄位、指標欄位、圖表類型、篩選條件及共享設定。
- 一鍵「預覽報表」：呼叫後動態產生 `ir.actions.act_window`，以 Odoo 原生 Pivot / Graph 視圖呈現。
- 不修改 `dms_report` 的既有固定報表，保持向下相容。

## 目標用戶

| 角色 | 需求 |
|------|------|
| 財務/業務分析人員 | 按需自訂報表維度與指標，快速生成分析視圖 |
| 管理者 | 集中管理並共享報表規則，無需仰賴開發者 |
| 一般使用者 | 瀏覽公開規則、使用預覽功能 |

## 成功指標

1. `docker compose up` 後安裝模組無 ERROR / WARNING。
2. 管理者可建立、編輯、刪除任意規則；一般使用者只能管理自己的規則。
3. 點擊「預覽報表」能正確開啟對應模型的 Pivot 或 Graph 視圖，維度與指標生效。
4. `make smoke` 180 秒內完成且 HTTP 200。

## 限制

- Odoo 16 Community Edition，不依賴 Enterprise 視圖元件。
- `filter_domain` 使用 Odoo `safe_eval`，避免程式碼注入。
- 不提供自訂 Dashboard 或即時推送功能（可列入 Phase 5 規劃）。
