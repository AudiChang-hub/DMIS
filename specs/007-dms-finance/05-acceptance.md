# 05 — Acceptance：財務結算模組驗收標準

## 安裝驗證

```bash
# 1. 啟動服務
make up

# 2. 升級/安裝模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev \
   -u dms_finance --stop-after-init 2>&1 | grep -E 'ERROR|Module|loaded'"

# 3. 重啟 Odoo（讓 Python 重新載入）
docker compose restart odoo

# 4. 健康檢查
Invoke-WebRequest -Uri http://localhost:8069/web/health -UseBasicParsing | Select-Object StatusCode

# 5. Smoke test
make smoke
```

## 功能驗收清單

### 選單

- [x] 頂部導覽列出現「財務結算」主選單
- [x] 點選後顯示財務結算清單（初始為空）

### Smart Button

- [x] 開啟任一已確認的銷售訂單，頂部顯示「財務結算 (0)」按鈕
- [x] 點擊按鈕後自動建立結算記錄並跳轉
- [x] 再次點擊按鈕顯示「財務結算 (1)」並進入同一記錄

### 自動帶入

- [x] 若訂單有 fee_vehicle_registration + fee_insurance > 0，則「牌險費支出」自動帶入
- [x] 若訂單有 commission > 0，則「車行傭金支出」自動帶入
- [x] 若訂單有 fee_plate_selection > 0，則「選號支出」自動帶入

### 計算欄位

- [x] 新增收入明細後，`total_income` 即時更新
- [x] 新增支出明細後，`total_expense` 即時更新
- [x] `net_profit = total_income - total_expense` 計算正確

### 資料完整性

- [x] 同一銷售訂單無法建立第二筆財務結算（唯一性約束）
- [x] 刪除收入/支出明細後淨利重新計算
