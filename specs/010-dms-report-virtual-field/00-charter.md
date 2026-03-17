# 00 — Charter：虛擬欄位模組（dms_report_virtual）

## 宗旨

讓分析人員與管理者在系統 UI 中即可定義「虛擬欄位」——透過關鍵字、正則或 Python 表達式將原始欄位值映射至自訂分類——無需修改程式碼或資料庫結構，便可在 Pivot / Graph 報表中依此分類分群統計。概念類似 Looker Studio 的「計算欄位」功能。

## 範圍

- 新增 `dms_report_virtual` 模組於 `addons/dms_report_virtual/`。
- 依賴 `dms_report_rule`（進而依賴 `dms_report`、`dms_finance`、`dms_sale` 等模組）。
- 核心模型 `dms.report.virtual.field`：描述一個虛擬欄位及其規則集。
- 核心模型 `dms.report.virtual.field.rule`：定義單一規則行（contains / regex / python）。
- 擴充 `dms.report.rule`：新增 `virtual_dimension_ids`，讓報表規則可引用虛擬欄位。
- 預覽向導 `dms.report.vf.preview`：根據規則計算分組並以精靈視窗展示結果。
- 測試向導 `dms.report.vf.test.wizard`：讓使用者輸入記錄 ID，即時驗證規則匹配結果。
- 不修改既有模組核心邏輯（dms_report、dms_report_rule、dms_sale、dms_finance）。

## 目標用戶

| 角色 | 需求 |
|------|------|
| BI 分析師 / 管理員 | 建立品牌分類、區域分類等虛擬欄位，無需開發資源 |
| 財務/業務人員 | 套用已建立的公開虛擬欄位於自訂報表中，快速分群統計 |
| 系統管理員 | 集中管理所有虛擬欄位，稽核規則正確性 |

## 成功指標

1. 安裝模組無 ERROR / WARNING，`-i dms_report_virtual --stop-after-init`。
2. 管理者可建立虛擬欄位，定義多條規則，並透過「測試」按鈕驗證規則正確性。
3. 在報表規則中選取虛擬維度，點擊「預覽報表」後顯示依虛擬欄位分組的彙整結果。
4. 一般使用者只能讀取公開或自己建立的虛擬欄位；無法修改他人定義。
5. `make smoke` / `docker compose ps` 180 秒內通過。

## 限制

- V1 預覽使用 Python 側計算（非原生 SQL group by），最多處理 1,000 筆記錄。
- Python 規則使用 `safe_eval` + 白名單（re, math），避免執行任意程式碼。
- 不提供 Dashboard / 即時推送（可列入 Phase 5）。
- Odoo 16 Community Edition，不依賴 Enterprise 元件。
