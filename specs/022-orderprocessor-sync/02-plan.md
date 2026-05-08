# 實作計畫（02-plan）— OrderProcessor 暫存區

## 背景

- OrderProcessor 與 Excel 同時具備寫入銷售資料的能力，會讓同一筆交易出現雙路徑輸入風險。
- 目前正式報表仍以 `dms.sale.order` 為主資料來源，因此在 Excel 匯入仍存在的過渡期間，OrderProcessor 不應直接進入銷售大表。
- 但 OrderProcessor 的解析結果仍有保留價值，需能在 Odoo 內查看原始 JSON、fallback 與標準化結果，以利 debug。

## 本次變更

1. 停用 OrderProcessor 直寫 `dms.sale.order` 的流程。
2. 擴充 `dms.sync.log`，讓它兼任 staging/debug 區，保存解析後欄位快照與 raw payload。
3. 保留既有 `folder_name` 去重與 `重新同步` 操作，但重新同步僅重建 staging，不刪改銷售訂單。
4. 更新暫存區清單/表單畫面，讓使用者可直接檢查客戶、車款、車行、分期與 raw JSON。
5. 驗證 OrderProcessor 新增資料不再進入 `dms.sale.order`，避免影響報表。
