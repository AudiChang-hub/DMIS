# 05 — Acceptance：報表分析模組驗收標準

## 安裝驗證

```bash
# 1. 啟動服務
make up

# 2. 安裝模組
docker compose exec -T odoo bash -lc \
  "PGHOST=db PGUSER=odoo PGPASSWORD=odoo odoo -d dmis_dev \
   -i dms_report --stop-after-init 2>&1 | grep -E 'ERROR|loaded in' | tail -5"

# 3. 重啟並確認
docker compose restart odoo; docker compose ps

# 4. Smoke test
make smoke
```

## 功能驗收清單

### 選單

- [x] 頂部導覽出現「報表分析」主選單
- [x] 子選單：銷售報表、利潤報表、傭金報表均可點選

### 銷售報表

- [x] Pivot 視圖可顯示，預設依月份分組
- [x] 可切換至 Graph（Bar）視圖
- [x] 可更換 group_by（車款、車行、交易類型）
- [x] 可更換 measure（amount_total、cost）

### 利潤報表

- [x] Pivot 視圖可顯示 total_income、total_expense、net_profit
- [x] Graph 視圖顯示 net_profit 逐月趨勢

### 傭金報表

- [x] Pivot 視圖僅顯示 sale_type = dealer 的資料
- [x] 可依車行 × 月份拆解傭金金額
