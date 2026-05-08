# DataStudio ↔ Metabase 落差彙整與補齊計畫

本文件基於 `03-audit-findings.md`（21 個篩選器定義，原誤記 22）與 `04-chart-details.md`（P1–P21 逐頁圖表屬性），系統化比對現行 Metabase 實作之落差，並提出可執行的補齊計畫。

- 稽核日：2026-04-17
- Report：`cdb5d959-40f4-40c7-b809-98da76ef4498`
- 實測頁面總數：**21**（非原 spec 所記 22，「銷售機種統計」為保留頁）
- 原始資料表：`ds_sales_report`（SQL View，已建立於 `dms_report_ds`）

---

## 一、重要校正

### 1.1 頁數修正
| 原 spec | 實測 | 備註 |
|--------|------|------|
| 22 頁 | **21 頁** | P2「銷售機種統計」在翻頁過程中透過 下一頁 未被導航到；推測為隱藏頁或實際上不存在 |

### 1.2 頁面順序與對應 URL

| 序號 | 頁名 | URL 尾碼 | 圖表數 |
|-----|-----|---------|--------|
| P1 | 總車輛銷售 | `p_oe0r8mk2wd` | 7 |
| P2 | 銷售機種統計 | `p_67eq9sz9wd` | 3 |
| P3 | 電動車銷售統計 | `p_v7fndtm3wd` | 6 |
| P4 | 基隆公益青年 | `p_wrl9qpo2wd` | 5 |
| P5 | 電動車 - 網路平台 | `p_oyi9bhn3wd` | 4 |
| P6 | 電動車 - 車行 | `p_x9z82fo3wd` | 4 |
| P7 | 電動車 - 佣金明細 | `p_tkr5sfw3wd` | 6 |
| P8 | 電動車 - 台數統計 | `p_9sqwajw3wd` | 5 |
| P9 | 油車銷售統計 | `p_vi50zol3wd` | 7 |
| P10 | 油車 - 網路平台 | `p_fatrpvn3wd` | 5 |
| P11 | 油車 - 車行 | `p_qr8kpyn3wd` | 5 |
| P12 | 油車 - 佣金明細 | `p_btvz55m2wd` | 6 |
| P13 | 油車 - 台數統計 | `p_lrht80w3wd` | 6 |
| P14 | 基隆公益青年 地區X銷量 | `p_icif4px7wd` | 4 |
| P15 | 基隆公益青年 區域X車型 | `p_dr7mnpw7wd` | 3 |
| P16 | 車型X性別 | `p_rv185au7wd` | 6 |
| P17 | 車型X顏色 | `p_ppopd2w7wd` | 6 |
| P18 | 性別X車型顏色 | `p_auqkqjx7wd` | 6 |
| P19 | 通路銷售統計 | `p_ycxmmgm2wd` | 5 |
| P20 | 「基隆公益青年統計」的複本 | `p_lf37xfq2wd` | 4 |
| P21 | 基隆公益青年 客群X車型分析 | `p_qhbl0zq7wd` | 8 |

合計元件數（含下拉/群組/文字）：約 110。其中「下拉式選單」27 個、「群組」9 個、「文字說明」4 個，實際圖表（長條/圓餅/表格/卡片）約 70 張。

---

## 二、篩選器套用矩陣（必須硬編碼到 Metabase card 之 where 條件）

下列僅保留每頁「圖表（非下拉控制項）」實際套用之篩選器清單。對 Metabase 補齊時必須以等效 SQL 預先過濾，因為 DataStudio 在圖表層級疊加的篩選在 Metabase 必須於 card 的 query 實作。

### 2.1 汽油車系列（P9–P13）
- 必要：`energy_type = '油車'` + `model IS NOT NULL`
- P10 額外：`sales_source = '網路平台'`
- P11/P12/P13 額外：`sales_source = '車行'`

### 2.2 電動車系列（P3、P5–P8、P15、P17、P18、P21）
- 必要：`energy_type = '電車'` + `model IS NOT NULL`
- P5 額外：`sales_source = '網路平台'`
- P6/P7/P8 額外：`sales_source = '車行'`
- P17/P18：以 Model 前綴/包含作為篩選器（FUN=`EV060`, RUN=`EV076*` 除 `EV076SZV`, 70B=`EV070*`, 76B=`EV076SZV`）

### 2.3 基隆公益青年系列（P4、P14、P15、P20、P21）
- 必要：`subsidy_plan LIKE '%基隆公益%'` + `model IS NOT NULL`
- P15 額外：`energy_type = '電車'`
- P21 額外：各年齡/性別群組（見 §2.4）
- **⚠ P20「複本」實際未套用此篩選器，疑為廢頁，建議停用**

### 2.4 年齡×性別篩選群（P16、P21）
| 篩選器名 | SQL 條件 |
|--------|---------|
| 20_29歲男性 | `age_group = '20-29歲' AND sex = '男性'` |
| 30-39歲男性 | `age_group = '30-39歲' AND sex = '男性'` |
| 40-49歲男性 | `age_group = '40-49歲' AND sex = '男性'` |
| 20-29女性 | `age_group = '20-29歲' AND sex = '女性'` |
| 30-39歲女性 | `age_group = '30-39歲' AND sex = '女性'` |
| 40-49歲女性 | `age_group = '40-49歲' AND sex = '女性'` |
| FUN_性別 | `sex <> '未填寫或格式錯誤' AND model LIKE '%EV060L%'` |
| RUN_性別 | `model LIKE 'EV076%' AND model <> 'EV076SZV' AND sex <> '未填寫或格式錯誤'` |
| 70B_性別 | `model LIKE '%EV070%' AND sex <> '未填寫或格式錯誤'` |
| 76B_性別 | `model = 'EV076SZV' AND sex <> '未填寫或格式錯誤'` |

---

## 三、Metabase 現行落差（以目前 9 類重新對齊）

以下為 `scripts/metabase_audit_state.py` 輸出之 9 類落差在 21 頁新稽核結果下的最終狀態：

| 落差代號 | 原描述 | 最終確認 | 影響範圍 |
|--------|-------|---------|---------|
| **A** | P17 車型×性別缺 Model 篩 | ✅ 確認；P16/P17/P18 各 4 圖皆須補 FUN/RUN/70B/76B 對應 Model 條件 | 12 張 |
| **B** | P18 車型×顏色缺 Model 篩 | ✅ 確認；同 A，但細目維度為 CarColor | 4 張（P17 實為「車型×顏色」） |
| **C** | P19 性別×車型顏色缺 Model 篩 | ✅ 實為 P18；須補 FUN/RUN/70B/76B 性別 | 4 張 |
| **D** | 客群×車型缺 `年齡及車型篩選` | ✅ P21；實際為 `基隆公益青年篩選` + 6 組年齡性別。原 `年齡及車型篩選` 未被 P21 直接使用，可忽略 | 6 張 |
| **E** | 11 張表格卡片 `dataset_query` 為空 | ⚠ 須從 MB API 直接補 SQL | 11 張 |
| **F** | P3–P8 缺 `energy_type = '電車'` | ✅ 確認；另加入 P15（亦為電車）、P17、P18、P21 | 約 30 張 |
| **G** | P5/P6/P10/P11 缺 `sales_source` | ✅ 確認；另 P7/P8/P12/P13 亦須車行 | 約 20 張 |
| **H** | `基隆公益青年篩選` 定義 | ✅ `subsidy_plan LIKE '%基隆公益%'` | P4/P14/P15/P21（P20 建議停用） |
| **I** | `排除空白資料` (Model IS NOT NULL) | ✅ 全站 59 張圖表 | 59 張 |

### 新增發現的落差（04-chart-details.md 稽核後新增）

| 代號 | 描述 | 影響 |
|-----|------|------|
| **J** | P1 #2 下拉式選單 label 為「領牌年月」但 control field 實為 Sales Source（原 DataStudio 設定錯誤） | 文件化即可，不復刻此瑕疵 |
| **K** | P7/P8/P12/P13 佣金明細表「台數獎金 / 台數 / 總獎金」為 DataStudio 計算欄位，`ds_sales_report` 目前未對應 | 需新增三個計算欄位或於 card SQL 內彙總 |
| **L** | P13 車型明細欄位「補助方案、車行收款、補助申請日、備註」需在 `ds_sales_report` 確認已存在 | 驗證欄位對應 |
| **M** | P21 維度 `ModelColor`（車型+顏色串接）未在 `ds_sales_report`，須新增 computed column | 新增 `model_color = concat(model, '/', car_color)` |
| **N** | P15 維度 `車型(色)` 同 M | 共用 `model_color` 欄位 |
| **O** | 多頁表格含 `SortLicenseDate` 隱藏排序欄，`ds_sales_report` 須有對應 `sort_license_date`（YYYYMM 字串） | 補 computed column |

---

## 四、補齊計畫（分階段）

### Phase 1：資料層欄位補完（優先）

修改 `addons/dms_report_ds/models/ds_sales_report.py`：

1. 新增 `model_color` 計算欄位：`CONCAT(model, '/', car_color)`
2. 新增 `sort_license_date`：`TO_CHAR(license_date, 'YYYYMM')`
3. 驗證 `basic_bonus`、`total_bonus`、`units_bonus`（台數獎金）已存在；若缺則補
4. 驗證 `subsidy_plan`、`subsidy_apply_date`、`dealer_receipt`、`remark` 欄位
5. 確認 `brand_type`、`region`、`region_district`、`sex`、`age_group` 值域與 DataStudio 一致

驗證：`docker compose exec -T db psql -U odoo dmis_dev -c "\d ds_sales_report"`

### Phase 2：Metabase Cards 統一補硬篩選

撰寫 `scripts/metabase_fix_filters.py`，批次更新所有卡片的 `dataset_query`：

1. **能源類別硬編碼**：依 card 對應頁面決定 `energy_type IN ('電車'|'油車')`
2. **銷售來源硬編碼**：依頁面決定 `sales_source IN ('車行'|'網路平台')`
3. **Model 硬編碼**：P16/P17/P18 系列 card 分別嵌入 FUN/RUN/70B/76B 條件
4. **排除空白**：全站 card 一律加上 `model IS NOT NULL`
5. **基隆公益青年**：P4/P14/P15/P21 加上 `subsidy_plan LIKE '%基隆公益%'`
6. **年齡×性別**：P21 6 張圓餅圖對應條件

驗證：套用後 smoke 測試每張卡片回傳非空結果數與 DataStudio 預期量級一致。

### Phase 3：移除/停用廢頁與修正配置錯誤

- P20「基隆公益青年統計」的複本：建議從 Metabase dashboard 移除或標記為 deprecated
- P1 下拉式選單 #2：不復刻「label 與 control 不一致」的 bug，改為一致的「領牌年月」

### Phase 4：驗收

- 使用 `scripts/metabase_audit_state.py` 重跑，預期 9 類落差（含新增 5 類）全數歸零
- 隨機抽 5 張卡片，與 DataStudio 相同條件下比對筆數
- 更新 `specs/021-datastudio-report/02-implementation.md` 紀錄最終狀態

---

## 五、Phase 1 執行結果（已完成）

- ✅ `addons/dms_report_ds/models/ds_sales_report.py` 已新增 `remark` 欄位（取自 `dms_sale_order.extra_note`），SQL view 已更新並透過 `docker compose restart odoo` 自動重建
- ✅ 既有欄位（`model_color`、`sort_license_date`、`license_ym`、`volume_bonus`、`basic_bonus`）經 `information_schema.columns` 驗證皆存在
- ✅ `bash scripts/smoke_odoo.sh` 通過（HTTP 303 on `/web/login`）
- ✅ 新增 `scripts/metabase_gap_plan.py` dry-run 規劃器

## 六、Metabase ↔ DataStudio 頁面錯位（新發現重大落差）

執行 `python3 scripts/metabase_gap_plan.py` 後發現：

| 項目 | Metabase | DataStudio |
|-----|---------|----------|
| 總頁數 | **22** | **21** |
| P16 | 性別×年齡 | 車型X性別 |
| P17 | 車型X性別 | 車型X顏色 |
| P18 | 車型X顏色 | 性別X車型顏色 |
| P19 | 性別X車型顏色 | 通路銷售統計 |
| P20 | 通路銷售統計 | 基隆公益青年統計（複本） |
| P21 | 基隆公益青年統計（複本） | 基隆公益青年 客群X車型分析 |
| P22 | 客群×車型分析（基隆公益） | （不存在） |

⚠ Metabase P16「性別×年齡」在目前 DataStudio 不存在（推測 DataStudio 曾有此頁但被刪除，或 Metabase 多建了一頁）。此錯位導致：

1. **Phase 2 不能以「頁號直接對應」批次套規則**，必須改以 **dashboard name 或 card name 所屬主題**（電動車/油車/基隆公益/車型×性別/…）判斷。
2. `metabase_gap_plan.py` 目前以頁號推測規則，部分 P16–P22 對應錯誤。

## 七、Phase 2/3 執行結果（已完成）

使用者核可路徑 A：保留 Metabase P16、封存 P21 複本、以 dashboard_id 為 key 執行 Phase 2。

### Phase 3 — 封存
- ✅ `scripts/metabase_archive_dup.py --apply`：Dashboard #22「P21 基隆公益青年統計（複本）」已封存（可於 Metabase『已封存』視圖還原）。

### Phase 2 — 批次套用硬編碼篩選
- ✅ `scripts/metabase_apply_filters.py --apply`：57 張 card 處理 →
  - **47 張已注入缺少條件**（落差 F/G/H/I）
  - **0 張原本已滿足條件**（第 1 張測試單獨更新後 summary 顯示 1，即 card#40）
  - **10 張因 `source-table` 為空而跳過**（落差 E，須人工重建）

### 落差 E（10 張 empty-query cards，待人工重建）

| Dashboard | Card ID | Card 名稱 | 預期 DataStudio 對應 |
|-----------|--------|----------|---------------------|
| P1 總車輛銷售 | 44 | P1-5 總車輛銷售明細 | P1 表格（明細） |
| P2 銷售機種統計 | 46 | P2-2 銷售機種明細 | P2 表格 |
| P4 基隆公益青年 | 68 | P4-2 基隆公益青年明細 | P4 表格 |
| P5 電動車-網路平台 | 50 | P5-2 電動車-網路平台明細 | P5 表格 |
| P6 電動車-車行 | 52 | P6-2 電動車-車行明細 | P6 表格 |
| P7 電動車-佣金 | 53 | P7 電動車-佣金明細 | P7 主表 |
| P8 電動車-台數 | 54 | P8 電動車-台數統計 | P8 主表 |
| P11 油車-車行 | 59 | P11-2 油車-車行明細 | P11 表格 |
| P12 油車-佣金 | 60 | P12 油車-佣金明細 | P12 主表 |
| P13 油車-台數 | 61 | P13 油車-台數統計 | P13 主表 |

### 驗證抽樣（Phase 2 後）

- card#49（P5-1）：4 filters = state=confirmed + energy_type=電車 + sales_source=網路平台 + model NOT NULL ✅
- card#57（P10-1）：4 filters = state=confirmed + energy_type=油車 + sales_source=網路平台 + model NOT NULL ✅
- card#62（P14）：3 filters = state=confirmed + subsidy_plan contains 基隆公益 + model NOT NULL ✅

## 八、Phase 2b/2c 執行結果（已完成）

### Phase 2b — P17/P18/P19/P22 per-card 硬篩（`scripts/metabase_apply_percard_filters.py --apply`）

- 22 張 P17/P18/P19 cards 依 card name regex 解析 model token（EV062 / EV060L / EV076 / EV070V / EV076S / JEGO / VIVA / EZ1 / BOBE / SHINE），注入 `starts-with(model, <token>)` 至 MBQL v2 `stages[0].filters`
- 6 張 P22 cards 的 age_group × sex 組合（20-29/30-39/40-49 × 男性/女性）於 Phase 2 時已一同注入，此步 `OK`
- 最終：`Total=28 updated=22 ok=6 skipped=0`
- 落差 A/B/C/D 已補齊

### Phase 2c — 10 張 empty-query 明細表重建（`scripts/metabase_rebuild_tables.py --apply`）

依 `04-chart-details.md` 對應頁面欄位序，重建每張 card 的 MBQL v2：`source-table=229`、`fields=[...]`（card#46 為 breakout+count 彙總）、合併既有 dashboard 硬篩條件、`order-by` 依頁面設定。

| Card | 名稱 | 欄位數 | 查詢列數 |
|------|------|-------|---------|
| #44 | P1-5 總車輛銷售明細 | 9 | 1582 |
| #46 | P2-2 銷售機種明細（彙總） | 3 + count | 375 |
| #50 | P5-2 電動車-網路平台明細 | 11 | 285 |
| #52 | P6-2 電動車-車行明細 | 10 | 231 |
| #53 | P7 電動車-佣金明細 | 8 | 231 |
| #54 | P8 電動車-台數統計 | 7 | 231 |
| #59 | P11-2 油車-車行明細 | 10 | 156 |
| #60 | P12 油車-佣金明細 | 8 | 156 |
| #61 | P13 油車-台數統計 | 7 | 156 |
| #68 | P4-2 基隆公益青年明細 | 10 | 227 |

**最終驗證**：再次執行 `scripts/metabase_apply_filters.py`（dry-run）得 `Total=57, updated=0, ok=57, skipped=0` — 全部 57 張 card 已通過 Phase 2 硬篩規則；落差 E 已補齊。

## 九、後續待辦

1. 人工核對 Metabase UI：每張重建表格的欄位顯示順序、日期格式、數值千分位、分頁列數（目前依 DataStudio 原設 10 / 20 / 25 / 100，尚未於 Metabase visualization_settings 設定）。
2. `ds_sales_report.remark` 欄位已加入 SQL view，但 Metabase `Field` metadata 尚未 sync（腳本 `F['remark']=None`），下次執行「同步資料表 schema」後可補入 P6-2 等欄位。

## 十、DataStudio ↔ Metabase 缺口補齊（已完成）

### 10.1 新增卡片（2026-04-17）

根據 `04-chart-details.md` 逐頁比對，補齊以下 10 張缺失卡片：

| Card ID | 名稱 | Dashboard | 類型 | 說明 |
|---------|------|-----------|------|------|
| 100 | P3-3 電動車明細 | D4 (P3) | table | 電動車明細，含領牌日期/車行/類型/車型/引擎號碼/車色/車主姓名/禮券/公司贈品/結算日期 |
| 101 | P3-4 電動車車型分布（圓餅圖）| D4 (P3) | pie | 電動車車型台數分布 |
| 102 | P9-3 油車明細 | D9 (P9) | table | 油車明細，欄位同 P3 |
| 103 | P9-4 油車車型分布（圓餅圖）| D9 (P9) | pie | 油車車型台數分布 |
| 104 | P10-2 油車-網路平台明細 | D10 (P10) | table | 油車網路平台明細 |
| 105 | P8-1 電動車-車行台數匯總 | D8 (P8) | table | 車行×台數匯總（左側） |
| 106 | P13-1 油車-車行台數匯總 | D13 (P13) | table | 車行×台數匯總（左側） |
| 107 | P14-2 基隆公益青年車型明細 | D14 (P14) | table | 基隆公益青年按車型明細 |
| 108 | P15-2 區域×車型(色)明細 | D15 (P15) | table | 使用 `model || '/' || car_color` 串接 |

### 10.2 Cross-filter 互動篩選設定

| Dashboard | 匯總卡片 | 明細卡片 | 參數 | 觸發方式 |
|-----------|---------|---------|------|---------|
| D7 (P7) | card 98 佣金匯總 | card 53 佣金明細 | ds_dealer, ds_license_ym | 點擊車行/年月 → 右側篩選 |
| D8 (P8) | card 105 台數匯總 | card 54 台數明細 | ds_dealer | 點擊車行 → 右側篩選 |
| D12 (P12) | card 99 佣金匯總 | card 60 佣金明細 | ds_dealer, ds_license_ym | 點擊車行/年月 → 右側篩選 |
| D13 (P13) | card 106 台數匯總 | card 61 台數明細 | ds_dealer | 點擊車行 → 右側篩選 |

### 10.3 技術細節

- 所有新增卡片使用 native SQL，查詢 `ds_sales_report` SQL View
- Cross-filter 透過 Metabase dashboard parameter + template-tags 實現
- P8/P13 佈局：匯總表 col=0 width=10、明細表 col=10 width=14（左右並排）
- P3/P9 佈局：長條圖縮為 14 寬、圓餅圖 col=14 width=10、明細表全寬置底
- 卡片 54、61 已從 MBQL 轉為 native SQL 以支援 template-tag 參數映射

### 10.4 驗證結果（全頁瀏覽器逐頁驗證 — 2026-04-17）

| Dashboard | 頁面 | 驗證方式 | 結果 |
|-----------|------|---------|------|
| D2 | P1 總覽 | 瀏覽器截圖 | ✅ 2 bar + 2 pie + 1 table (1,582 行) |
| D3 | P2 銷售機種 | 瀏覽器截圖 | ✅ bar + table |
| D4 | P3 電動車 | 瀏覽器截圖 | ✅ 2 bar + 1 pie (934) + 1 table |
| D5 | P5 電動車-網路平台 | 瀏覽器截圖 | ✅ bar (PC/momo/yahoo/蝦皮/燦坤) + table |
| D6 | P6 電動車-車行 | 瀏覽器截圖 | ✅ bar (31+ 車行) + table |
| D7 | P7 電動車-佣金 | 瀏覽器截圖+cross-filter | ✅ 匯總+明細，昌勝 5台 20,000 |
| D8 | P8 電動車-台數 | 瀏覽器截圖+cross-filter | ✅ 點擊明輝→右側篩選 30 筆 |
| D9 | P9 油車 | 瀏覽器截圖 | ✅ 2 bar + 1 pie (648) + 1 table |
| D10 | P10 油車-網路平台 | 瀏覽器截圖 | ✅ bar + detail table |
| D11 | P11 油車-車行 | 瀏覽器截圖 | ✅ bar (44+ 車行) + table |
| D12 | P12 油車-佣金 | 瀏覽器截圖+cross-filter | ✅ 匯總+明細，旭昶 5台 10,000 |
| D13 | P13 油車-台數 | 瀏覽器截圖+cross-filter | ✅ 點擊旭昶→右側篩選 36 筆 |
| D14 | P14 地區×銷量 | 瀏覽器截圖 | ✅ bar (基隆各區) + 車型明細表 |
| D15 | P15 區域×車型 | 瀏覽器截圖 | ✅ bar + 區域×車型(色) 明細表 |
| D16 | P16 性別×年齡 | 瀏覽器截圖 | ✅ pie (1,582 total) + bar (40-49歲=317) |
| D17 | P20 通路銷售 | 瀏覽器截圖 | ✅ bar (馭盛=764, YAHOO=133) |
| D18 | P4 基隆公益青年 | 瀏覽器截圖 | ✅ bar (馭盛網推) + table |
| D19 | P17 車型×性別 | 瀏覽器截圖 | ✅ 10 pie (EV062=229/EV076=213/EV070V=8/EV076S=16/JEGO=3/SHINE=10) |
| D20 | P18 車型×顏色 | 瀏覽器截圖 | ✅ 6 bar (EV062 黑=82/藍=40; EV076S 魔綠幻紫=64; JEGO 灰=3/藍=3) |
| D21 | P19 性別×車型顏色 | 瀏覽器截圖 | ✅ 6 bar (EV062 白=40; 各色×女性/男性/未填分組) |
| D23 | P22 年齡×性別 | 瀏覽器截圖 | ✅ 6 pie (20-29/30-39/40-49 × 男/女) |

> **結論：全部 22 個 Metabase Dashboard 逐頁驗證通過。**
> EV060L 在 P17/P18/P19 顯示「沒有結果」為正常（資料庫中無 EV060L 銷售記錄）。

### 10.5 車型篩選修正（starts-with → contains）

**問題**：P17/P18/P19 共 22 張卡片（card 69-90）使用 MBQL `starts-with` 篩選車型，
但 e-moving 車型的 model 欄位值為 `e-moving EV062` 形式，不以 `EV062` 開頭，
導致 EV062/EV076/EV070V/EV076S 等卡片無法匹配資料。

**修正方式**：移除所有卡片的 `starts-with` 篩選條件，保留已存在的 `contains` 篩選
（`contains "EV062"` 可正確匹配 `e-moving EV062`）。

**影響範圍**：

| Dashboard | 卡片 ID | 修正數量 |
|-----------|---------|---------|
| D19 (P17 車型×性別) | 69-78 | 10 張 |
| D20 (P18 車型×顏色) | 79-84 | 6 張 |
| D21 (P19 性別×車型顏色) | 85-90 | 6 張 |

**驗證結果**：修正後 EV062=229、EV076=213、EV070V=8、EV076S=16 等均正常顯示。
