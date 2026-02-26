# 車行主檔（002）驗收任務（繁體中文）

以下為可逐條驗收的 DoD 項目。每一項完成後，請在 PR 中註明驗證步驟與測試結果。

1. 模型擴充
  - 內容：在 `dms.dealer` 新增 `short_name`, `store_type`, `parent_id`, `child_ids`, `city`, `district`, `tags` (Many2many), `note` (Html), `partner_id` (res.partner)。
  - 驗收：已建立欄位且不刪除既有欄位；現有資料可讀取；至少新增 1 筆示範資料包含 `short_name` 與 `city`。

2. 顯示與搜尋
  - 內容：實作 `name_get` 顯示為 `[code] name`；`name_search` 支援 `code/name/phone/short_name`；tree & form 更新，search view 提供 filter 與 group by。
  - 驗收：下拉顯示 `[code] name`；可用 code/name/phone/short_name 搜尋；filter 與 group by 可用。

3. 資料完整性與治理
  - 內容：保留 SQL unique constraint；新增 python constraint 防止 `parent_id` 指向自己或造成循環；明確哪些欄位為必填或建議填寫（在 view 中標示）。
  - 驗收：無法建立相同 `code`；設定 `parent_id` 為自己或形成循環時會被拒絕；`code/name` 為必填驗證正常。

4. 權限與選單
  - 內容：新增群組 `DMS/車行使用者`（只讀）與 `DMS/車行管理者`（讀寫）；更新 `ir.model.access.csv` 以套用權限；保留 `DMS > 車行 > 列表` 選單。
  - 驗收：使用者屬於車行使用者群組時為唯讀；管理者可新增與編輯紀錄；選單與 action 正常顯示。

5. 示範資料
  - 內容：更新 `data/seed.xml`，至少 2 筆 demo 包含新欄位範例。
  - 驗收：示範資料可在安裝模組後看到，且包含 `short_name` 與 `city` 的範例值。

6. 遵守憲章規則
  - 內容：確認未新增匯入 wizard、未加入計算邏輯，並且為未來 003/004 留下擴充介面（tags/partner/link points）。
  - 驗收：代碼審查確認無匯入或計算邏輯，且新增欄位提供擴充可能。

7. 欄位細項驗收（依據需求清單）
  - 基本資料
    - 目標：`name`（店名）、`owner_name`（負責人）、`store_manager`（店長）皆為必填；`address` 與 `note` 可空。
    - 驗收：嘗試在表單省略必填欄位會被拒絕；能建立含 optional 欄位的紀錄且資料可讀回。

  - 聯絡資訊
    - 目標：`phone_1`、`phone_2`、`mobile`、`mobile_fax` 為選填欄位。
    - 驗收：可以任意組合建立/編輯聯絡欄位；搜尋可使用 phone_1/phone_2/mobile。

  - 價格表權限（勾選）
    - 目標：四個 boolean 欄位代表各品牌價格表的啟用權限。
    - 驗收：在 form 可以勾選/取消；資料儲存後值正確呈現。

  - 排車容量
    - 目標：`sym_dispatch_capacity`、`suzuki_dispatch_capacity` 必須為整數或空值，且不得為負數。
    - 驗收：輸入負數時會被拒絕；接受 0 或正整數。

  - 群組/活動（勾選）
    - 目標：多個 boolean 欄位表示群組或活動參與狀態。
    - 驗收：能在表單中切換勾選並於 tree/search 顯示或作為 filter 條件。

8. UI 與搜尋驗收
  - Tree：顯示 `code`,`name`,`short_name`,`store_type`,`phone_1`,`city`,`active`。
  - Form：使用 notebook 分頁（Basic / Contact / Prices & Capacities / Groups & Tags / Notes）。
  - Search：支援透過 `code/name/phone_1/short_name` 搜尋，且能 filter by `active`、`store_type`，支援 group by `store_type` 與 `city`。
  - 驗收：UI 元素存在且可互動，搜尋/分組/過濾回傳正確結果。

9. 權限驗收
  - 目標：`DMS/車行使用者`（只讀），`DMS/車行管理者`（可讀寫建立刪除）。
  - 驗收：以兩個不同使用者帳號驗證權限差異：使用者只能讀取、管理者可新增/修改/刪除。

10. Smoke 驗收
  - 目標：整合驗證流程在 PR 中提供可重現步驟。
  - 驗收：依照 PR 的驗證步驟執行後，API/HTTP smoke 與 UI 操作皆成功。

