# 有效商業規則（按任務讀相關段落）

核對：2026-09-19。本檔記錄有效語意與查證入口，不複製完整 schema；程式／測試與需求不符時提出差異，不自行選一邊覆蓋。

## 訂單與接待

- 店內與車行使用同一選車、選色、付款方案、填單流程；接待不能露出其他客戶訂單或內部財務。
- 建立與查詢分開授權；內部管理需使用者主動進入。車行只能存取其授權資料範圍。
- 訂單成立日不同於領牌日；歷史 Excel 缺訂單日期依既有匯入規則採領牌日，系統建立採成立時間。不可混用圖表日期口徑。
- 已完成訂單仍可依權限修正，保留原因、修改人與前後紀錄；不暗中重置交付／結算狀態。
- 刪除經專用流程與稽核；不得直接 SQL 刪除來繞過關聯檢查。正式資料批次合併另須確認衝突與交易邊界。
- 入口：`sales/tests/test_order_intake.py`、`test_reception_entry.py`、`test_completed_order_corrections.py`、`test_order_deletion.py`。

## Excel 匯入與識別

- 現行入口是 `sales/services/legacy_import.py`；財務還原見 `legacy_finance.py`。Odoo 的 excel_sync_id 規格不是目前實作。
- `_sales_transaction_key(data)` 使用車輛識別（缺值退回型號／車牌）、類別、領牌／發票／訂單日期順序擇一，以及車主身分證號或姓名的正規化雜湊組成；以函式為精確來源。
- 使用者提出「姓名＋車身／引擎號」辨識重複，是特定清理需求；**不是已實作的唯一約束**。空值不代表同車，不能只憑同名合併。
- 匯入須保持可重跑、防重複、已刪除資料不被舊列重建；原始財務值不能因缺項直接套新單算法而失真。
- 修改唯一鍵、映射或補值之前，先提出方案與歷史資料影響；測試：`sales/tests/test_legacy_import.py`、`test_legacy_finance.py`。

## 車型、車色與方案

- 選車展示列出啟用車型的啟用車色；沒照片不等於停用，應顯示待補圖卡。
- 車色必須屬於所選車型且仍啟用；選定車色與付款方案進入填單時保留選擇並重新驗證，不能信任前端價格。
- 來源：`sales/catalog_views.py`、`sales/services/catalog_selection.py`；測試 `test_catalog_selection.py`、`test_catalog_color_list.py`、`test_catalog_management.py`。

## 財務與權限

- 財務、成本、佣金、補助、淨利依既有營運欄位與快照計算；有效版本依領牌日等既定生效條件，不以目前價表覆蓋歷史交易。
- 最終總價折扣可輸入折數或折讓金額；**分期公司撥款、佣金與成本不跟著折扣**。既有核准與修改稽核仍有效。
- admin 指定哪些人可調整下單金額；此授權不連帶開放成本、佣金、淨利、報表或其他車行資料。
- 淨利須有權限及密碼解鎖；前端隱藏不能代替後端拒絕存取。取消／退款不是有效售出，不當作未領牌待辦或正常淨利。
- 來源：`sales/tests/test_screen_access.py`、`test_profit_privacy_ux.py`、`test_site_review_followup.py`、`test_financial_consistency.py`。精確公式按服務函式與對應測試定位，不在本文件複製。
