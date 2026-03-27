# PR：feat/dms_visit → feat/dealer-uiux

## 功能說明

新增 **dms_visit** 模組，為 DMIS 系統加入車行拜訪紀錄管理，整合至現有「車行管理」功能下。

### 主要功能

| 功能 | 說明 |
|------|------|
| 拜訪清單 | 表格式清單，可搜尋、篩選、群組 |
| 拜訪行事曆 | 月曆視圖，依 visit_date 顯示，顏色區分狀態 |
| 拜訪表單 | 完整欄位編輯，含狀態流轉按鈕 |
| 送出物品明細 | 可在表單「送出物品」頁籤記錄送出的 dms.product 品項與數量 |
| 車行 Smart Button | 車行表單顯示拜訪次數，點擊跳轉拜訪清單 |
| 拜訪目的類別 | 管理員可維護目的分類 |

### 新增模型

- `dms.visit.purpose`：拜訪目的類別
- `dms.visit`：拜訪紀錄（visit_date / dealer_id / visitor_id / purpose_id / state / item_ids）
- `dms.visit.item`：送出物品中間表（product_id / quantity / note）
- `dms.dealer` 繼承：新增 `visit_ids`, `visit_count`, `action_open_visits()`

### 安全設定

- `group_dms_visit_user`：讀寫自己的拜訪（Record Rule 限制 visitor_id = 自己）
- `group_dms_visit_admin`：讀寫刪除所有拜訪

## Commits

| SHA | 說明 |
|-----|------|
| `980df37` | docs(specs): 新增 011-dms-visit 規格文件 |
| `298e7d6` | feat(dms_visit): 新增拜訪紀錄模組（dms_visit） |
| `0e6dc85` | test(dms_visit): 新增 5 個單元測試案例 |

## 驗收步驟

```bash
# 1. 啟動環境
make up

# 2. 安裝模組
docker exec dmis-odoo-1 odoo --stop-after-init -d dmis_dev -i dms_visit

# 3. 冒煙測試
make smoke

# 4. 確認容器正常
docker compose ps

# 5. （選擇性）執行單元測試
docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -i dms_visit
```

## 驗收清單

- [ ] 安裝模組無 ERROR / WARNING
- [ ] 「車行管理」選單下出現「拜訪清單」與「拜訪行事曆」（需有 group_dms_visit_user 或 admin）
- [ ] 行事曆視圖能正確顯示拜訪事件，點擊可進入表單
- [ ] 表單可新增送出物品，儲存成功
- [ ] 車行表單有「拜訪紀錄」Smart Button
- [ ] Record Rule 正確（user 僅見自己；admin 見所有）
- [ ] `make smoke` HTTP 200
- [ ] 現有功能（車行管理、銷售、財務）不受影響
