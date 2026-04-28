# 023 - Excel 銷貨資料匯入 Wizard

## 版本
- 功能版: 16.0.1.2.0
- 建立日期: 2026-04-15
- 最後更新: 2026-04-28（英文車行名稱大小寫不敏感比對）

## 目的
將「車輛進銷貨庫存表(客戶資料).xlsx」銷貨頁籤的歷史資料（共約 1582 筆）匯入 DMIS 銷售訂單，並支援後續重複同步（upsert）。

開發期間可持續以最新 Excel 執行匯入，upsert 機制確保相同序號不重複建立。正式釋出前再清空並匯入最終版本。

## 匯入機制
- 主鍵：`excel_sync_id`（Excel 欄1 序號）
- 邏輯：有序號已存在 → 更新；不存在 → 新增
- 匯入後狀態：已成立（confirmed）
- `excel_sync_id` 須同時有 ORM unique constraint（`_sql_constraints`）及 DB-level UNIQUE index，確保資料庫層防護

## 新增欄位（dms.sale.order）— 第一批
| 欄位 | 類型 | 說明 |
|---|---|---|
| `excel_sync_id` | Char | 來源序號，upsert 比對主鍵，DB UNIQUE |
| `source_dealer_name` | Char | 原始車行名稱（車行找不到時暫存） |
| `subsidy_boie_status` | Char | 工業局申請狀態（原始文字） |
| `subsidy_moenv_status` | Char | 環境部申請狀態（原始文字） |
| `subsidy_city_status` | Char | 縣市政府申請狀態（原始文字） |

## 新增欄位（dms.sale.order）— 第二批（display 架構）
| 欄位 | 類型 | 說明 |
|---|---|---|
| `source_color_name` | Char, copy=False | **永遠**寫入 Excel 原始顏色文字，無論是否找到對應 `color_id` |
| `display_color_name` | Char, computed, store=True | `color_id.name` 若有，否則 `source_color_name` |
| `display_product_name` | Char, computed, store=True | `product_id.name` 若有，否則 `source_product_name` |
| `display_dealer_name` | Char, computed, store=True | `dealer_id.name` 若有，否則 `source_dealer_name` |

`display_*` 欄位設計目的：讓報表 group by 與清單顯示在 Many2one 找不到時仍有可讀文字，不顯示空白。

compute 依賴：
- `display_color_name` depends `color_id, source_color_name`
- `display_product_name` depends `product_id, source_product_name`
- `display_dealer_name` depends `dealer_id, source_dealer_name`

## 現有欄位調整
- `source_product_name`：移除客戶資訊區塊的重複顯示，統一只在車輛資訊區塊顯示（attrs: `source_product_name != False`）
- `sale_origin`：Selection 加入 `('excel', 'Excel 匯入')` 值；匯入時寫 `'excel'`，不再沿用 `'manual'`

## 補助欄位雙讀設計（欄 60/61/62）
Excel 欄 BI/BJ/BK 同時被讀取兩次，此為刻意設計：
- **文字讀**（`subsidy_boie_status` / `subsidy_moenv_status` / `subsidy_city_status`）：原樣存入，可能為 `V`、申請進度文字或空白
- **數字讀**（`subsidy_moea` / `subsidy_moenv` / `subsidy_local`）：嘗試轉 float，失敗 fallback 0.0
- 兩者互不干擾，各自填入不同的模型欄位

## Wizard 模型：dms.excel.import.wizard
流程：上傳 Excel → 預覽（新增N/更新N）→ 確認匯入

顏色處理邏輯：
1. `source_color_name` ← 永遠寫入原始顏色字串（無論有無找到 M2O record）
2. `color_id` ← 若有找到對應 `dms.product.color` record 才額外寫入

車行比對邏輯（英文大小寫不敏感）：
- 中文車行名稱：以 `name = dealer_name` 精確比對（既有行為）。
- 英文車行名稱（純 ASCII）：因 Excel 端與車行主檔皆可能存在大小寫不一致（全大寫 / 全小寫 / 混雜），改採大小寫不敏感比對：
  1. 以 `name ilike dealer_name` 取候選清單。
  2. 對每筆候選比較 `candidate.name.strip().upper() == dealer_name.upper()`，命中即視為對應車行。
- 仍找不到時：寫入 `source_dealer_name` 暫存原始名稱並記錄警告，行為與既有設計一致。
- 判斷英文 / 中文之依據：字串中所有字元皆為 ASCII（`ord(c) < 128`）即視為英文車行名稱。
- 對應實作：`addons/dms_sale/wizard/excel_import_wizard.py` 的 `_is_ascii_name()` helper 與 `_build_vals()` 內車行比對區塊。

## 驗證指令
```bash
docker compose restart odoo
bash scripts/smoke_odoo.sh

# 匯入後驗證
docker compose exec -T db psql -U odoo dmis_dev -c "
SELECT
  COUNT(*) FILTER (WHERE excel_sync_id IS NOT NULL) AS excel匯入,
  COUNT(*) FILTER (WHERE source_product_name IS NOT NULL) AS 車款備存,
  COUNT(*) FILTER (WHERE source_color_name IS NOT NULL) AS 顏色備存,
  COUNT(*) FILTER (WHERE source_dealer_name IS NOT NULL) AS 車行備存
FROM dms_sale_order;"

# 確認無重複序號
docker compose exec -T db psql -U odoo dmis_dev -c "
SELECT excel_sync_id, COUNT(*) FROM dms_sale_order
WHERE excel_sync_id IS NOT NULL
GROUP BY excel_sync_id HAVING COUNT(*) > 1;"
```
