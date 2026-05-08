# 實作計畫（02-plan）— dms_sale 匯入補正

## 背景

- OrderProcessor 有機會只產出身分證辨識結果，`result.json` 缺少 docx 文字內容，導致訂單建立時僅有客戶姓名、沒有車型。
- 另一類資料雖有正確 docx，但 `是否有分期=18期` 這類值會被誤寫入 `finance_company` selection，造成建立失敗。
- 同一筆訂單若有兩個時間相近的資料夾，正確資料重新同步時需要能接手既有缺值訂單，而不是再開新單。
- 同一筆交易若先後經過 OrderProcessor 與 Excel 匯入，現行兩條路徑各自只用 `source_folder` 或 `excel_sync_id` 去重，會把同一客戶同一筆交易拆成兩張訂單。

## 本次變更

1. `order_sync` 一律嘗試讀取 xlsx fallback，並以「只補缺漏」方式合併欄位。
2. 正規化分期欄位，將純期數解析到 `installment_periods`，避免 invalid selection。
3. 重新同步 OrderProcessor 資料夾時，優先更新相同或近似資料夾簽名的既有缺值訂單。
4. 重啟 Odoo 後，以指定資料夾重同步驗證歷史案例可補正車型。
5. Excel 匯入的車型匹配補上模板 family/model/code fallback，避免 A1 這類模板名稱無法命中 legacy `dms.product`。
6. 補上 Excel 與 OrderProcessor 的跨來源去重邏輯，讓同一客戶同一筆交易可回寫同一張訂單並保留雙方追蹤欄位。