# 05 - Acceptance

驗收條件：

1. 能夠在 Odoo UI 中建立/編輯 `車行`，表單分頁與欄位正確顯示。
2. 勾選 `店長同上` 後，UI 即時 (onchange) 將 `負責人` 同步到 `店長`。
3. 透過 API/import 建立或更新時，若 `manager_same_as_owner=True` 且未提供 `store_manager`，系統會補上 `owner_name`。
4. `sym_dispatch_capacity` 與 `suzuki_dispatch_capacity` 不可為負，會觸發 ValidationError。
5. tree/search/view 可正確篩選與群組，並且 `品牌` / `車行類型` 的選單存在。 

驗證指令：

```bash
docker compose ps
make smoke
```

（若新增 tests，請在 smoke 中包含執行測試）
# Acceptance Criteria（驗收）

- `docker compose up` 可啟動 Odoo 與 Postgres
- `make smoke` 能在 180 秒內得到 200/302/303 回應
- PR 若修改 `addons/**` 或 `docker-compose.yml`，且未同步更新 `specs/**`，CI 失敗
- 可在 Odoo Apps 中看到並安裝「車行」模組（dealer）

新增車行（Dealer）MVP 驗收條件：

- 在 Odoo 後台能看到 `DMS -> 車行` 選單，點入後可看到清單（tree）與明細（form）。
- 能夠建立新的車行並填寫 `code`、`name`（必填）。
- `code` 欄位為唯一（重複代碼建立時會失敗並提示）。
- 搜尋功能應能以 `code`、`name`、`phone` 查詢到正確記錄。
- 基本 ACL 生效：一般使用者具有讀寫建立刪除的基本權限（以 `security/ir.model.access.csv` 為準）。

## UI/UX 改善驗收條件

### 列表（tree view）
- 列表不顯示「簡稱」（`short_name`）欄位、不顯示「縣市」（`city`）欄位。
- 列表顯示欄位：車行代碼、車行名稱、負責人、店長、電話1、手機、車行類型、品牌。

### 基本資料 labels
- 車行名稱、負責人 labels 在 form 中清楚可見（顯示欄位標題，非僅 placeholder）。

### 店長同負責人
- 勾選「同負責人」後，店長欄位立即帶入負責人姓名（onchange 生效）。
- 負責人變更且「同負責人」仍勾選時，店長同步更新。
- 取消勾選後，店長姓名保留（不自動清空）。
- 透過 API（create/write）傳入同負責人勾選時，亦能防呆同步。

### 車行類型與品牌
- 車行類型可從下拉選單選擇（`dms.dealer.type` 主檔）。
- 品牌可多選（many2many_tags widget），支援多品牌車行。
- 多品牌保存後再次開啟仍存在（Many2many 正確儲存）。

### 明細可編輯
- 點進車行明細預設為編輯模式（不需再手動點 Edit 按鈕）。

### labels 粗體（若 SCSS 已加入）
- form view 中所有欄位 label 呈現粗體，區塊分隔清楚。

### 手動測試案例
1. 建立車行，填入負責人「張大哥」，勾選「同負責人」→ 店長自動顯示「張大哥」。
2. 修改負責人為「李老闆」（保持勾選）→ 店長同步變更為「李老闆」。
3. 取消「同負責人」勾選 → 店長保持「李老闆」，不被清空。
4. 選擇品牌「三陽」和「台鈴」→ 儲存後重開，兩個品牌仍存在。
5. 開啟車行列表，確認欄位清單不含「簡稱」「縣市」。