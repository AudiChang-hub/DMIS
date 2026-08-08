# Odoo 至 DMIS Next 正式切換紀錄

## 切換範圍

- 正式網域：`https://dmis.moto-core.com/`
- 新系統：`/home/audi/project/DMIS-next`
- 舊系統：`/home/audi/project/DMIS`
- 正式網域沿用既有 Cloudflare Tunnel 與 `http://odoo:8069` 來源名稱；切換後
  由新系統 `tunnel-proxy` 接手該名稱並轉送至 `http://web:8000`。

## 已搬遷主檔

| 資料 | 結果 |
| --- | ---: |
| 車行／網路平台 | 174 筆 |
| 聯絡窗口 | 162 筆 |
| 品牌合作政策 | 99 筆 |
| 車型 | 42 筆 |
| 顏色 | 76 筆 |
| 價格版本 | 43 筆 |
| 車行傭金調整 | 4 筆 |
| 台數獎金規則 | 6 筆 |
| 國定假日 | 240 筆 |

匯入採 transaction、可乾跑、可重跑，並使用車行代碼、車型組合鍵與有效日期
避免重複建立。

## 未自動搬遷及人工確認清單

- 舊 Odoo 1,614 筆銷貨單不自動轉為正式訂單，避免與 Excel 正式歷史資料
  重複。歷史訂單應使用後續專用匯入流程處理。
- 18 筆舊分期列缺少可可靠判斷的分期公司，保留於匯入報告供人工對照。
- 2 筆實物獎勵規則不自動換算為金額。
- 19 個油車車型缺少可驗證排氣量，已建立車型但排氣量留空，不猜測數值。
- 1 筆特定車行台數獎金缺少品牌，未匯入以避免錯套規則。

## 備份與回復

切換前備份位於：

`/srv/dmis-data/dmis-next/migration/pre-cutover-20260808_165639/`

內含舊 Odoo PostgreSQL、filestore、SHA256、主檔匯出與匯入報告；新 Django
資料庫備份位於：

`/srv/dmis-data/dmis-next/backups/postgres/daily/dmis_20260808_165639.sql.gz`

若正式網域驗證失敗，停止 `tunnel-proxy`，將舊 Odoo container 重新接回
`dmis_default` network 的 `odoo` alias，再啟動舊 Odoo。舊資料庫與 filestore
在觀察期內不得刪除。

## 驗證清單

- `python manage.py test`
- `python manage.py check --deploy`
- `https://dmis.moto-core.com/health/` 回傳 200
- 登入頁與靜態檔正常
- 主檔筆數與匯入報告相符
- T470P 其他服務持續運作
- 舊 Odoo 自動部署 timer 在切換成功後停用
