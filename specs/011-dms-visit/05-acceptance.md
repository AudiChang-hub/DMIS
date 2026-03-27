# 05 — Acceptance：拜訪紀錄模組（dms_visit）

## 驗收標準

### AC-01：模組安裝
- [ ] `docker compose up -d` 後在 Odoo Apps 搜尋 `dms_visit` 並安裝，無 ERROR / WARNING。
- [ ] `docker compose logs odoo` 不出現 `dms_visit` 相關錯誤。

### AC-02：行事曆視圖
- [ ] 在「車行管理」→「拜訪行事曆」能看到月曆介面。
- [ ] 已建立的拜訪紀錄在對應日期出現標記，顏色依 state 區分。
- [ ] 點擊事件標記後可進入拜訪表單視圖。

### AC-03：清單視圖
- [ ] 在「車行管理」→「拜訪清單」能看到表格，顯示 visit_date、dealer_id、visitor_id、purpose_id、state。
- [ ] 可按月份、車行、拜訪人員分組。
- [ ] 搜尋「今日拜訪」篩選器正確過濾。

### AC-04：拜訪表單
- [ ] 可新增拜訪紀錄，visit_date、dealer_id、visitor_id 為必填，缺一則儲存失敗並提示。
- [ ] 選擇 dealer_id 後，車行地址與電話自動帶出（唯讀顯示）。
- [ ] 可在「送出物品」頁籤新增送出物品名稱、數量、備註並儲存成功。
- [ ] 若歷史資料仍帶 `product_id`，系統可自動回填 `item_name`，且畫面不因此失效。
- [ ] 點擊「確認完成」按鈕，state 變為 done；點擊「取消」變為 cancel；點擊「重置草稿」回 draft。

### AC-05：車行 Smart Button
- [ ] 在車行表單頁頂部出現「拜訪紀錄」Smart Button，顯示拜訪數量。
- [ ] 點擊後開啟該車行的拜訪清單，自動帶入 `default_dealer_id`。

### AC-06：權限與 Record Rule
- [ ] `group_dms_visit_user` 成員：只能查看自己（visitor_id = 自己）的拜訪，無法看到他人的紀錄。
- [ ] `group_dms_visit_user` 成員：無法刪除拜訪紀錄（unlink 回傳 Access Error）。
- [ ] `group_dms_visit_admin` 成員：可查看所有拜訪紀錄，可刪除。
- [ ] 非以上群組成員：無法訪問 dms.visit 模型（Access Error）。

### AC-07：不破壞現有功能
- [ ] `make smoke` 在 180 秒內完成且 HTTP 200。
- [ ] 車行管理（dms_core）、銷售管理（dms_sale）、財務結算（dms_finance）功能正常。
- [ ] 安裝 dms_visit 前後，現有資料表紀錄數量不變。

### AC-08：單元測試
- [ ] `docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -i dms_visit` 執行無 ERROR。
- [ ] 8 個測試案例全部通過（0 FAIL / 0 ERROR）。
- [ ] 自動排程測試以 `dms.visit.schedule` 為基礎，而非已移除的 dealer 布林欄位。

## 驗證指令

```bash
# 啟動測試環境
make up

# 安裝模組
docker exec dmis-odoo-1 odoo --stop-after-init -d dmis_dev -i dms_visit

# 執行冒煙測試
make smoke

# 查看容器狀態
docker compose ps

# 執行單元測試（option）
docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -i dms_visit
```
