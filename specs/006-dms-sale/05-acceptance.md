# 驗收標準（05-acceptance）— dms_sale

## 安裝驗證
- [x] `docker compose exec -T odoo bash -lc "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev -i dms_sale --stop-after-init 2>&1 | tail -10"` 無 ERROR
- [x] 重啟後 `/web/login` HTTP 200

## 功能驗收

### 訂單建立
- [x] 新增訂單時序號自動產生（格式：SO2026030001）
- [x] 選擇「車款」後，現金售價欄位自動帶入（優先取 `dms.price.line` 的最新生效版本，無資料時 fallback `dms.vehicle.price`）
- [x] 選擇電車車款後，牌險費 8 欄自動帶入，頂部顯示藍色提示橫幅
- [x] 選擇油車車款後，牌險費欄位不自動填入，頂部顯示橘色警示橫幅
- [x] 牌險合計自動加總（9 欄）

### 車行訂單（B2B）
- [x] 交易類型切換為「車行」後，車行欄位與車行金流區塊才顯示
- [x] 選擇車行 + 車款 + 期數後，傭金欄位自動帶入（來自 dms.commission.rule）

### 分期付款
- [x] 付款方式選「分期」後，分期公司/期數/月付金欄位才顯示
- [x] OrderProcessor 匯入遇到 `是否有分期=18期` 時，可正確寫入 `installment_periods=18`，且不會因 `finance_company` invalid selection 失敗

### 匯入補正
- [x] `result.json` 只有身分證辨識、缺少 docx 文字時，若資料夾內 xlsx 有原始資料，重新同步後可補上缺漏的車型資訊
- [x] 同一筆 OrderProcessor 訂單若存在僅時間戳不同的近似資料夾，重新同步正確資料夾後會更新既有缺值訂單，而非另開新單
- [x] Excel 匯入來源 `車種型號=A1` 時，若對應 `dms.product` 建在模板 `family_name/model_name`，仍可正確帶入 `product_id`
- [x] 同一客戶若先由 OrderProcessor 建立訂單，後續 Excel 匯入同筆交易時，系統會更新原單並補上 `excel_sync_id`，不會新增第二筆訂單
- [x] 同一客戶若先由 Excel 匯入建立訂單，後續 OrderProcessor 同步同筆交易時，系統會更新原單並補上 `source_folder`，不會新增第二筆訂單
- [x] 既有 `sale_origin` 在跨來源合併後維持原值，不因補寫另一來源資料而被覆蓋

### 精品明細
- [x] 可新增多筆精品明細（O2m tab）
- [x] 選擇精品後自動帶入單價與安裝費
- [x] 小計自動計算：(單價 + 安裝費) × 數量

### 狀態機
- [x] 草稿→確認訂單→確認 狀態正確
- [x] 確認→重回草稿→草稿 狀態正確
- [x] 草稿→取消訂單→取消 狀態正確

## UI 合規（參照 `specs/000-roadmap/03-ui-standards.md`）
- [x] tree 視圖所有欄位皆 optional（active=show）
- [x] search view 有「啟用中」和「已歸檔」篩選器
- [x] 所有 UI 文字為繁體中文
