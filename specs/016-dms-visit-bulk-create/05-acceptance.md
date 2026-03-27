# 05 — Acceptance：拜訪行事曆批次建立（016-dms-visit-bulk-create）

## 功能驗收

- [x] 可從主選單開啟批次建立拜訪功能
- [x] 行事曆雙擊開啟的單筆拜訪表單不顯示批次選擇入口
- [x] 可一次多選多間車行
- [x] 可統一輸入拜訪日期
- [x] 可統一輸入拜訪人員
- [x] 可統一輸入拜訪目的
- [x] 送出後會建立多筆 `dms.visit`，每筆對應一間車行
- [x] 建立後的每筆拜訪都可在拜訪清單/行事曆看見

## 相容驗收

- [x] 既有單筆建立拜訪流程仍可正常使用
- [x] `dms.visit.schedule` 自動排程不受影響
- [x] 既有 record rule 仍有效

## 測試驗收

- [x] `docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -u dms_visit ...` 通過
- [x] `bash scripts/smoke_odoo.sh` 通過
