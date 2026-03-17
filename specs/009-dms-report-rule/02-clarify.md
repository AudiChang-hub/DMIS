# 02 — Clarify：待釐清事項（dms_report_rule）

## 已釐清

| # | 問題 | 答覆 |
|---|------|------|
| 1 | `filter_domain` 是否需要 UI 的 visual domain builder？ | 目前以純文字輸入為主，附說明提示；UI builder 列入 Phase 5 TODO |
| 2 | `measure_ids` 在 Graph 視圖是否生效？ | Graph 視圖本身只顯示第一個 measure；context 中帶入所有 measure 供 Pivot 使用 |
| 3 | `chart_type = 'pie'` 時 Odoo 16 Community 是否支援？ | `ir.ui.view` graph 支援 `pie`，可使用 |
| 4 | 一般用戶是否可修改公開規則？ | 否，public 規則只能讀取；只有 owner 或 admin 才能修改 |

## 待議 TODO

| # | 問題 | 影響 |
|---|------|------|
| T1 | 是否需要「複製規則」功能（copy_rule）？ | 方便使用者快速建立變體；可在 v1.1 加入 |
| T2 | 維度欄位是否需要支援 Date 欄位的 interval（month/week）？ | 目前 group_by 傳 `['order_date:month']` 格式需要 UI 支援 date operator；v1 暫時只傳欄位名稱 |
| T3 | 匯出報表規則為 JSON 供備份或分享？ | 低優先，列入 Phase 5 |
