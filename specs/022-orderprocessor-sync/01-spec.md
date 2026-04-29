# 022 OrderProcessor → DMIS 訂單自動匯入

## 目標
讓 OrderProcessor 處理完成的訂單資料，自動匯入 DMIS 建立草稿銷售訂單，不需人工介入，且不影響現有功能與 OrderProcessor 正常運作。

## 架構
- docker-compose volume mount：`/home/audi/project/OrderProcessor/backup:/mnt/order_backup:ro`（唯讀）
- Odoo Scheduled Action（ir.cron）每 1 分鐘掃描 `/mnt/order_backup/`
- 讀取各資料夾內的 `result.json`，用 ORM 直接建立 `dms.sale.order`（state=draft）
- 每筆處理結果寫入 `dms.sync.log`，失敗只寫 log，不影響其他訂單處理

## 新增欄位（dms.sale.order）
| 欄位 | 型別 | 說明 |
|---|---|---|
| source_product_name | Char | 原始車款字串，如 GIXXER SF 250 (GSX250F) |
| source_folder | Char | backup 資料夾名稱，去重用，開發者模式才可見 |
| sale_origin | Selection(manual/order_processor) | 訂單來源，預設 manual |
| is_trade_in | Boolean | 有汰舊標記 |

## 新增模型（dms.sync.log）
| 欄位 | 說明 |
|---|---|
| sync_time | 處理時間 |
| folder_name | backup 資料夾名稱 |
| state | success / fail / skip / ignored |
| order_id | 關聯的 dms.sale.order（建立成功時） |
| error_msg | 失敗原因 |

## 解析邏輯
- result.json 兩種格式皆支援（透過 `_normalize_data` 統一）：
  - 舊：`{text_map, front, back}`（或 `{docx:{text_map}, front, back}`）
  - 新：以檔名為 key
    * `*.docx` → `text_content` 多行字串，依「key：value」拆解為 text_map
    * `身分證正面.jpg` → `辨識面=front`、`擷取欄位` 視為 front dict
    * `身分證反面.jpg` → `辨識面=back`、`擷取欄位` 視為 back dict
- 車款：從「車輛型號」括號內取 SKU，搜尋 dms.product.model；找不到則留空，原始字串存 source_product_name
- 顏色：取括號前名稱，ilike 搜尋 dms.product.color；找不到留空
- 車行：先以原字串比對，再 fallback 去除全形/半形空白後重比（如「昌 億」→「昌億」）；空白則 sale_type='store'
- 預設車行：車行名稱空白時帶入店面（sale_type='store'，dealer_id=False）
- 汰舊：「是否有汰舊」不是「否」→ is_trade_in=True
- 分期：「是否有分期」不是「無」→ payment_method='installment'，解析分期公司

## 去重機制
以 dms.sync.log.folder_name 去重，只要 log 有紀錄（任意狀態）就跳過。
訂單被刪除後不會重新匯入。

## 歷史資料處理
同步紀錄頁面提供「標記歷史資料」按鈕，一次將現有所有資料夾標記為 ignored，避免舊資料被誤匯入。

## 安全設計
- volume mount 唯讀（:ro），Odoo 無法修改 OrderProcessor 資料
- 每筆資料夾獨立 try/except，失敗不影響其他資料夾
- result.json mtime 需 > 60 秒，避免複製中途被讀取
- product_id 在 ORM 層移除 required，View 層保留 required="1"，業務操作行為不變

## 選單位置
銷售管理 > 同步紀錄（僅系統管理員可見，可透過群組管理調整）

## 驗證步驟
1. docker compose up -d
2. docker compose exec odoo ls /mnt/order_backup（確認 mount）
3. 手動觸發 Scheduled Action
4. 銷售管理 > 同步紀錄 → 確認有成功紀錄
5. 確認欄位對應正確（以 旭昶_GIXXER SF 250 測資為準）
6. 重複觸發 → 不重複建立
7. bash scripts/smoke_odoo.sh → OK: 303
