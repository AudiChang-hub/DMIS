# 00 — Charter：拜訪紀錄模組（dms_visit）

## 宗旨

改善與車行往來的拜訪管理，在 Odoo 系統中集中記錄每次拜訪的時間、地點（車行）、目的、拜訪人員及送出物品，提供清單與行事曆兩種界面，讓業務人員與管理者能快速查看拜訪紀錄，並與現有「車行管理」功能緊密整合。

## 範圍

- 新增 `dms_visit` 模組於 `addons/dms_visit/`，`application=False`（非獨立 App）。
- 依賴模組：`dms_core`、`dms_sale`。
- 功能選單掛載於現有「車行管理」主選單下，不建立頂層 App 選單。
- 擴充 `dms.dealer`：新增 `visit_ids` One2many 欄位與「拜訪紀錄」Smart Button。
- 不修改 `dms_core`；產品模型 `dms.product` 由 `dms_sale` 提供，`dms_visit` 僅以依賴與 `_inherit` / 關聯欄位方式整合。

## 目標用戶

- **業務人員**：記錄拜訪車行的過程與送出物品，查詢拜訪行事曆。
- **管理者**：檢視所有業務員的拜訪紀錄，維護拜訪目的類別。

## 成功指標

1. `docker compose up` 後安裝模組無 ERROR / WARNING。
2. 在「車行管理」→「拜訪行事曆」能以月曆方式查看拜訪事件，點擊可進入表單。
3. 在「車行管理」→「拜訪清單」能以表格搜尋、群組、篩選拜訪紀錄。
4. 在車行表單頁的 Smart Button 顯示該車行拜訪數量，點擊後進入篩選後的拜訪清單。
5. 拜訪表單可新增送出物品（品名、數量、備註），儲存成功。
6. Record Rule 正確：一般使用者只能看自己的拜訪；管理者可看所有拜訪。
7. `make smoke` 在 180 秒內完成且 HTTP 200，現有功能不受影響。

## 限制

- Odoo 16 Community Edition，不使用 Enterprise 功能。
- 本模組不依賴 `mail` 模組（無 Chatter）；若未來需要可再擴充。
- 送出物品連結至 `dms.product`（本系統自訂產品），而非 Odoo 標準 `product.product`。
- 不刪除或修改任何現有模組的資料表、欄位或邏輯。
