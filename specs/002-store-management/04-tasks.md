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
