# 033 易用性、閱讀與辨識強化｜Tasks

- [x] 統一全部訂單搜尋正規化與命中摘要。
- [x] 修正手機全部訂單篩選列水平溢出。
- [x] 重構手機統一撥款對帳卡片。
- [x] 加入訂單工作頁籤可滑動提示。
- [x] 統一狀態色、字級、觸控尺寸及金額格式。
- [x] 統一配件與其他費用動態欄位樣式。
- [x] 為來源、車型及車色加入可搜尋選擇器。
- [x] 建立登入後系統診斷頁。
- [x] 補使用說明畫面辨識示例。
- [x] 補搜尋、RWD、診斷與可存取性回歸測試。
- [ ] 執行完整驗證、Commit、推送及正式部署確認。

## 本機驗證紀錄

- `node --check static/js/searchable-select.js`：通過。
- `python manage.py check`：通過。
- `python manage.py makemigrations --check --dry-run`：無遺漏 migration。
- 模擬正式環境執行 `python manage.py check --deploy`：通過。
- `python manage.py test sales`：288 項全部通過。
