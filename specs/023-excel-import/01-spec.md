# 023 - Excel 銷貨資料匯入 Wizard

## 版本
- 功能版: 16.0.1.0.0
- 建立日期: 2026-04-15

## 目的
將「車輛進銷貨庫存表(客戶資料).xlsx」銷貨頁籤的歷史資料（共約 1582 筆）匯入 DMIS 銷售訂單，並支援後續重複同步（upsert）。

## 匯入機制
- 主鍵：`excel_sync_id`（Excel 欄1 序號）
- 邏輯：有序號已存在 → 更新；不存在 → 新增
- 匯入後狀態：已成立（confirmed）

## 新增欄位（dms.sale.order）
| 欄位 | 類型 | 說明 |
|---|---|---|
| `excel_sync_id` | Char | 來源序號，upsert 比對主鍵，unique |
| `source_dealer_name` | Char | 原始車行名稱（車行找不到時暫存） |
| `subsidy_boie_status` | Char | 工業局申請狀態（原始文字） |
| `subsidy_moenv_status` | Char | 環境部申請狀態（原始文字） |
| `subsidy_city_status` | Char | 縣市政府申請狀態（原始文字） |

## 現有欄位調整
- `source_product_name`：移除 `groups='base.group_no_one'`，開放一般使用者可見

## Wizard 模型：dms.excel.import.wizard
流程：上傳 Excel → 預覽（新增N/更新N）→ 確認匯入

## 欄位對應（完整版）
見對話紀錄 2026-04-15 的最終確認表。

## 驗證指令
```
make up / docker compose restart odoo
docker compose exec odoo odoo -u dms_sale -d dmis_dev --stop-after-init
bash scripts/smoke_odoo.sh
```
