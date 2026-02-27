# 驗收條件 (05-acceptance)

## 庺穎/環境
- `docker compose up` 為一鍵啟動 Odoo + PostgreSQL
- `make smoke` 在 180 秒內得到 200/302/303 回應
- PR 若修改 `addons/**` 或 `docker-compose.yml`，且未同步更新 `specs/**`，CI 必須失敗

## 車行 (dms.dealer) 驗收條件

### 模型
- [ ] `dms.dealer.code` 唯一約束 + 建立時自動產生
- [ ] `store_manager` 非必填可空白
- [ ] `manager_same_as_owner=True` 時，`store_manager` 自動帶入負責人名稱且只讀
- [ ] 4 個 Boolean 價格欄位可獨立勾選
- [ ] `sym_dispatch_capacity`/`suzuki_dispatch_capacity` 負數引發 ValidationError
- [ ] `name_search` 支援 code/name/phone_1/mobile/owner_name/store_manager/address/brand_ids.name

### 品牌 (dms.brand)
- [ ] 可新增、編輯、刪除品牌
- [ ] 名稱唯一約束，重複時顯示錯誤
- [ ] `active` 支援欸檔 (Archive)

### 車行類型 (dms.store_type)
- [ ] 可新增、編輯、刪除車行類型
- [ ] 名稱唯一約束，重複時顯示錯誤
- [ ] `active` 支援歸檔

### 視圖/UX
- [ ] `DMS -> 車行` 選單可進入 tree/form
- [ ] Form 有 4 個分頁：基本資料/聯絡資訊/價格表群組/排車容量
- [ ] Tree 列 name/owner_name/store_manager/phone_1/mobile
- [ ] 搜尋列 name/owner_name/store_manager/phone_1/mobile
- [ ] 搜尋列含 4 個 Boolean 價格表 filter
- [ ] `DMS -> 品牌` / `DMS -> 車行類型` 選單存在

### 測試
- [ ] `make test` / `odoo -u dms_core --test-enable` 所有測試通過
- [ ] Boolean 價格欄位持久化測試
- [ ] 排車容量負數測試
- [ ] `manager_same_as_owner` create/write 流程測試
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