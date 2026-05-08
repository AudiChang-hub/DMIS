# 022 OrderProcessor → Debug 暫存區

## 目標
讓 OrderProcessor 處理完成的訂單資料，自動進入 DMIS 的 debug 暫存區，供解析驗證與問題排查使用；在 Excel 匯入仍存在的過渡期間，不得直接寫入 `dms.sale.order`，避免影響正式銷售資料與報表。

## 架構
- docker-compose volume mount：`/home/audi/project/OrderProcessor/backup:/mnt/order_backup:ro`（唯讀）
- Odoo Scheduled Action（ir.cron）每 1 分鐘掃描 `/mnt/order_backup/`
- 讀取各資料夾內的 `result.json`，解析後寫入 `dms.sync.log` 作為 staging/debug 記錄
- `dms.sync.log` 同時保存原始 JSON、xlsx fallback 內容與標準化後欄位快照，供後續 debug 使用
- OrderProcessor 在本階段不得建立、更新或刪除 `dms.sale.order`
- 每筆處理結果仍寫入 `dms.sync.log`，失敗只記錄本筆，不影響其他資料夾處理

## 暫存模型（dms.sync.log）
| 欄位 | 說明 |
|---|---|
| sync_time | 處理時間 |
| folder_name | backup 資料夾名稱 |
| state | success / fail / skip / ignored |
| customer_name / id_number / customer_phone | 解析出的客戶主資訊 |
| source_product_name / source_color_name / source_dealer_name | 原始辨識字串 |
| product_id / color_id / dealer_id | 比對到的主檔 |
| sale_type / payment_method / finance_company / installment_periods / is_trade_in | 標準化後交易欄位快照 |
| raw_result_json | 原始 `result.json` 內容 |
| fallback_payload_json | xlsx fallback 讀到的原始內容 |
| staged_vals_json | 系統標準化後、原本準備寫入訂單的欄位快照 |
| fallback_used | 是否有使用 xlsx fallback |
| order_id | 僅保留歷史相容用途；新資料預設為空 |
| error_msg | 失敗原因 |

## 解析邏輯
- result.json 兩種格式皆支援（透過 `_normalize_data` 統一）：
  - 舊：`{text_map, front, back}`（或 `{docx:{text_map}, front, back}`）
  - 新：以檔名為 key
    * `*.docx` → `text_content` 多行字串，依「key：value」拆解為 text_map
    * `身分證正面.jpg` → `辨識面=front`、`擷取欄位` 視為 front dict
    * `身分證反面.jpg` → `辨識面=back`、`擷取欄位` 視為 back dict
- 若 result.json 解析後客戶姓名仍為空（含「（未知）」），fallback 讀取資料夾內含「原始資料」工作表的 `*.xlsx`：
  * 第一列為欄位名稱、第二列為資料；必須含「姓名」欄位才算有效
  * 欄位映射：機種/型號→車輛型號、顏色→車輛顏色、車行→車行名稱、姓名→front.姓名、生日→front.出生年月日、身分證→front.身分證字號、戶籍→back.住址、手機→車主電話、車主Email、是否有汰舊、是否有分期、備註、配件
- 車款：從「車輛型號」括號內取 SKU，搜尋 dms.product.model；找不到則留空，原始字串存 source_product_name
- 顏色：取括號前名稱，ilike 搜尋 dms.product.color；找不到留空
- 車行：先以原字串比對，再 fallback 去除全形/半形空白後重比（如「昌 億」→「昌億」）；空白則 sale_type='store'
- 預設車行：車行名稱空白時帶入店面（sale_type='store'，dealer_id=False）
- 汰舊：「是否有汰舊」不是「否」→ is_trade_in=True
- 分期：「是否有分期」不是「無」→ payment_method='installment'，解析分期公司
- 解析完成後僅寫入 `dms.sync.log` 暫存區；不得直寫 `dms.sale.order`

## 去重機制
以 dms.sync.log.folder_name 去重，只要 log 有紀錄（任意狀態）就跳過。
暫存紀錄被刪除後，才允許重新匯入同一資料夾。

## 重新同步（手動重試）
同步紀錄表單提供「重新同步」按鈕，呼叫 `dms.sync.log.action_resync`：
- 刪除該筆暫存/log 紀錄
- 由 `dms.order.sync._process_folder_by_name(folder_name)` 重新解析該資料夾並重建 staging
- 跳過 mtime 保護，使用者觸發時假設檔案已穩定
- 結束後跳轉顯示新建立的暫存紀錄
- 不得刪除或修改既有 `dms.sale.order`
適用情境：解析邏輯更新後，要對既有資料夾重跑；或失敗紀錄補資料後重試。

## 歷史資料處理
同步紀錄頁面提供「標記歷史資料」按鈕，一次將現有所有資料夾標記為 ignored，避免舊資料被誤匯入。

## 安全設計
- volume mount 唯讀（:ro），Odoo 無法修改 OrderProcessor 資料
- 每筆資料夾獨立 try/except，失敗不影響其他資料夾
- result.json mtime 需 > 60 秒，避免複製中途被讀取
- 在 Excel 匯入仍為正式寫入路徑期間，OrderProcessor 不得影響正式報表來源 `dms.sale.order`

## 選單位置
銷售管理 > OrderProcessor 暫存區（僅系統管理員可見，可透過群組管理調整）

## 驗證步驟
1. docker compose up -d
2. docker compose exec odoo ls /mnt/order_backup（確認 mount）
3. 手動觸發 Scheduled Action
4. 銷售管理 > OrderProcessor 暫存區 → 確認有成功紀錄
5. 確認欄位對應正確（以 旭昶_GIXXER SF 250 測資為準）
6. 確認 `dms.sale.order` 不會新增 `sale_origin='order_processor'` 訂單
7. 重複觸發 → 不重複建立第二筆暫存紀錄
8. bash scripts/smoke_odoo.sh → OK: 303

