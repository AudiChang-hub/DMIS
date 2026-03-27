# 05 — Acceptance：新一代產品管理模組重建（015-dms-product-rebuild）

## A. 新產品模組功能驗收

- [x] 可從新頂層 App「產品管理」進入主畫面
- [x] 可建立產品模板，至少可輸入品牌、機種、型式、型號、能源型式
- [x] 可建立 SKU，至少可輸入模板、車色、出廠年份、內部唯一代碼、啟用狀態
- [x] 同一模板下可建立不同車色 / 不同出廠年份的多筆 SKU
- [x] SKU 僅於產品模板表單中的產品項頁籤維護，不提供獨立選單頁面
- [x] 停用後的產品項仍可在模板頁籤看見，並可直接重新啟用
- [x] 可於產品模板的產品項頁籤直接複製既有 SKU，再微調顏色等欄位
- [x] 產品項複製後會自動生成新的唯一 `internal_code`，不因沿用舊碼而報重複
- [x] 產品項列級複製後不會重複堆疊相同 breadcrumb
- [x] 可於產品模板的產品項頁籤直接刪除未被其他資料引用的 SKU
- [x] 模板清單中的 `SKU 數量` 僅計算啟用中的產品項
- [x] 產品模板可從操作選單執行「複製」，並建立新模板與對應產品項
- [x] SKU 選取下拉可明確辨識出廠年份與顏色
- [x] 出廠年份於畫面直接顯示年份文字，例如 `2026`，不得顯示為 `2,026`
- [x] 不可建立重複 `internal_code`
- [x] 未手動輸入 `internal_code` 時，系統會依「型號 + 出廠年份」自動生成可讀代碼
- [x] 若同型號同年份有多筆 SKU，系統會自動補尾碼維持唯一性
- [x] 主要清單畫面以 list 為主，不依賴圖片作主畫面核心

## B. 價格生效邏輯驗收

- [x] 可建立價目版本（名稱、生效日、狀態、備註）
- [x] 可在同一價目版本下為同一 SKU 建立價格基準（現金價、牌價）
- [x] 可於價目版本中一次多選多個 SKU，批次建立多筆價格基準
- [x] 批次加入多個 SKU 時，可一併輸入統一現金價與牌價並套用到所有新增價格列
- [x] 查詢價格時，系統抓取 `effective_date <= 查詢日` 的最新版本
- [x] 不要求手動維護價格迄日
- [x] 同 SKU 不同價目版本可有不同價格

## C. 分期規則驗收

- [x] 可建立分期規則模板
- [x] 可建立多筆規則明細（起始期數、結束期數、價格基準）
- [x] 規則明細期數區間不得重疊
- [x] 規則結構不依賴 `type_1 / type_2 / type_3` 固定欄位
- [x] 同 SKU 在不同價目版本下可掛不同分期規則模板

## D. 費用規則驗收

- [x] 可建立費用類型主檔
- [x] 預設至少存在「開辦費」與「設定費」
- [x] 可在規則明細下新增多筆費用明細
- [x] 費用明細可設定外加 / 內含 / 公司吸收
- [x] 費用類型可擴充，不侷限於兩個固定欄位

## E. migration / 相容驗收

- [x] 舊 `dms.product` 資料不失聯
- [x] 舊 `dms.product` 能回填 `template_id`、`internal_code`、`production_year`
- [x] 若 legacy `dms.vehicle.price` 有資料，可回填到新價格結構
- [x] 若 legacy `dms.installment.plan` 有資料，可回填到新規則結構
- [x] 不可粗暴刪除 legacy 資料

## F. 不影響既有功能驗收

- [x] `dms_sale` 可正常建立銷售訂單
- [x] `dms_sale` 選擇車款後可正確查價（新結構或 legacy fallback）
- [x] `dms_visit` 可正常建立拜訪並記錄送出物品
- [x] `dms_finance` 可正常建立財務結算
- [x] `user_management` 可正常建立與指派群組

## G. 不影響現有使用者驗收

- [x] 現有使用者原本可完成的主要流程不失效
- [x] 不因新模組建立造成既有畫面開啟失敗
- [x] 不因模組重建造成現有資料不可查詢
- [x] 新入口與相容入口的關係有明確文件說明

## H. 車行管理模組回歸驗收

- [x] 車行建立、編輯、搜尋正常
- [x] 品牌管理正常
- [x] 拜訪清單正常
- [x] 拜訪行事曆正常
- [x] 車行管理相關權限不變

## I. Odoo 測試與升級驗收

- [x] `dms_product` 可正常安裝
- [x] `dms_product` 可正常升級
- [x] 新模組 menu / action / view 可正常載入
- [x] `dms_product` 的 Odoo 測試全部通過
- [x] 受影響模組升級指令無 ERROR

## J. 驗證指令

至少需實際執行並列出結果：

```bash
make up
docker compose ps
docker compose restart odoo
make smoke
docker exec dmis-odoo-1 odoo --stop-after-init -d dmis_dev -u dms_product,dms_sale,dms_visit
docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -i dms_product
docker exec dmis-odoo-1 odoo --test-enable --stop-after-init -d dmis_dev -u dms_core,dms_visit,user_management,dms_finance
```

> 若任何測試失敗，不得跳過，必須修正或明確說明阻塞原因。

### 本輪實際驗證結果（2026-03-27）

- `make up` / `make smoke`：此環境未安裝 `make`，改以 `docker compose up -d` 與 `bash scripts/smoke_odoo.sh` 執行等效流程
- `docker compose ps`：`db` / `odoo` / `cloudflared` 皆為 `Up`
- `python3 scripts/cleanup_dms_catalog_metadata.py --database dmis_dev --user odoo`：成功清除重建前孤兒 `base.module_dms_product` XML ID
- `docker exec dmis-odoo-1 odoo --stop-after-init -d dmis_dev -i dms_product --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo`：成功
- `docker exec dmis-odoo-1 odoo --http-port=8070 --test-enable --stop-after-init -d dmis_dev -u dms_core,user_management,dms_sale,dms_visit,dms_product --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo`：`0 failed, 0 error(s) of 62 tests`
- `bash scripts/smoke_odoo.sh`：`OK: received 200 from http://localhost:8069/web/login`
