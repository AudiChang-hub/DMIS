# 實作計畫（02-plan）— dms_sale 匯入補正

## 背景

- OrderProcessor 解析仍有 debug 價值，但在 Excel 匯入仍為正式路徑時，不應直接寫入 `dms.sale.order`。
- 目前雙路徑輸入會污染銷售大表與報表，因此 OrderProcessor 需要先退回 staging/debug 角色。
- 另一類資料雖有正確 docx，但 `是否有分期=18期` 這類值仍需在 staging 中正確正規化，方便後續對照解析品質。

## 本次變更

1. `order_sync` 一律嘗試讀取 xlsx fallback，並以「只補缺漏」方式組出 staging 欄位快照。
2. 正規化分期欄位，將純期數解析到 `installment_periods`，避免 staging 本身就失真。
3. 將 OrderProcessor 的落點改成 `dms.sync.log`，保存 raw payload 與標準化結果。
4. 重新同步 OrderProcessor 資料夾時，只重建暫存紀錄，不動 `dms.sale.order`。
5. Excel 匯入維持正式銷售資料唯一自動寫入路徑。