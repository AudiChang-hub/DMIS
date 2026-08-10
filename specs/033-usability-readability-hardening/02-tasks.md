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
- [x] 執行完整驗證、Commit、推送及正式部署確認。

## 本機驗證紀錄

- `node --check static/js/searchable-select.js`：通過。
- `python manage.py check`：通過。
- `python manage.py makemigrations --check --dry-run`：無遺漏 migration。
- 模擬正式環境執行 `python manage.py check --deploy`：通過。
- `python manage.py test sales`：288 項全部通過。

## 正式站驗收紀錄

- GitHub Actions（commit `2cc8530`）：Django 品質檢查與 Docker build 全部通過。
- T470P 正式專案以 fast-forward 更新，部署前完成 PostgreSQL 與媒體備份；資料庫與 Redis 未重啟。
- `https://dmis.moto-core.com/health/`：回傳正常。
- 390px 手機版：全部訂單、統一撥款對帳、建立訂單及訂單頁籤無整頁水平溢出。
- 搜尋 `ABC-1234`、`abc1234`、`ABC 1234`：均為 2 筆且命中摘要一致。
- 未選車型時車色停用且僅顯示「請先選擇車型」；不再載入全部車色。
- 系統狀態頁：資料庫、背景工作、搜尋索引與媒體空間皆正常，且未顯示秘密或連線字串。
