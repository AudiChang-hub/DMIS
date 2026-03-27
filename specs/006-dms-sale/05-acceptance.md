# 驗收標準（05-acceptance）— dms_sale

## 安裝驗證
- [ ] `docker compose exec -T odoo bash -lc "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev -i dms_sale --stop-after-init 2>&1 | tail -10"` 無 ERROR
- [ ] 重啟後 `/web/login` HTTP 200

## 功能驗收

### 訂單建立
- [ ] 新增訂單時序號自動產生（格式：SO2026030001）
- [ ] 選擇「車款」後，現金售價欄位自動帶入（優先取 `dms.price.line` 的最新生效版本，無資料時 fallback `dms.vehicle.price`）
- [ ] 選擇電車車款後，牌險費 8 欄自動帶入，頂部顯示藍色提示橫幅
- [ ] 選擇油車車款後，牌險費欄位不自動填入，頂部顯示橘色警示橫幅
- [ ] 牌險合計自動加總（9 欄）

### 車行訂單（B2B）
- [ ] 交易類型切換為「車行」後，車行欄位與車行金流區塊才顯示
- [ ] 選擇車行 + 車款 + 期數後，傭金欄位自動帶入（來自 dms.commission.rule）

### 分期付款
- [ ] 付款方式選「分期」後，分期公司/期數/月付金欄位才顯示

### 精品明細
- [ ] 可新增多筆精品明細（O2m tab）
- [ ] 選擇精品後自動帶入單價與安裝費
- [ ] 小計自動計算：(單價 + 安裝費) × 數量

### 狀態機
- [ ] 草稿→確認訂單→確認 狀態正確
- [ ] 確認→重回草稿→草稿 狀態正確
- [ ] 草稿→取消訂單→取消 狀態正確

## UI 合規（參照 `specs/000-roadmap/03-ui-standards.md`）
- [ ] tree 視圖所有欄位皆 optional（active=show）
- [ ] search view 有「啟用中」和「已歸檔」篩選器
- [ ] 所有 UI 文字為繁體中文
