# 02 — Clarify：待釐清事項（dms_report_virtual）

## 已釐清

| # | 問題 | 答覆 |
|---|------|------|
| 1 | V1 preview 是否需要原生 Pivot 視圖支援？ | 否，V1 使用 Python 側計算並以精靈顯示彙整結果；原生 Pivot 整合列入 V2 |
| 2 | `python` 規則是否支援多行表達式？ | `safe_eval` 僅支援單一表達式（expression），不支援 statement（如 if/else block）；複雜邏輯仍可使用三元運算 `a if cond else b` |
| 3 | V1 最多幾筆記錄做虛擬計算？ | 最多 1,000 筆；超過時自動截斷並顯示警告 |
| 4 | 虛擬欄位是否支援多個維度同時分組？ | V1 只取 `virtual_dimension_ids[0]` 第一個虛擬維度；多維支援列為 V2 |
| 5 | 「虛擬欄位」是否永久儲存至資料庫欄位？ | V1 不儲存（純計算）；V2 可考慮 `x_vf_<code>` 的 stored compute field |

## 待議 TODO

| # | 問題 | 影響 |
|---|------|------|
| T1 | V2：將虛擬欄位值同步存入 `x_vf_<code>` 實體欄位以支援原生 Pivot group by | 效能大幅提升、欄位數量增加 |
| T2 | V2：支援 AND/OR 複合條件（目前只有單一條件 per rule） | 需要新的條件資料結構（JSON 或子模型） |
| T3 | `field_name` 自動完成：依 `model_id` 動態列出可用欄位 | UX 改善，需前端 JS 或 Char 替換為 Many2one(ir.model.fields) |
| T4 | 預覽結果的匯出（CSV/Excel）？ | 低優先，列入 Phase 5 |
| T5 | 多個虛擬維度同時分組（巢狀 groupby）？ | V1 只支援第一個，V2 擴充 |
