# DataStudio SUZUKI銷售統計 — 重新稽核紀錄

本文件記錄 2026-04-17 對 DataStudio 報表 `cdb5d959-40f4-40c7-b809-98da76ef4498` 的逐項驗證，
取代並勘誤 `01-datastudio-extraction.md` 中未驗證的「推測條件」。

- Report ID：`cdb5d959-40f4-40c7-b809-98da76ef4498`
- 總頁數：22
- 來源：實際操作 DataStudio 編輯模式（透過瀏覽器自動化 + 「資源 → 管理篩選器」逐項開啟）

---

## 一、全域篩選器定義（22 個，已 100% 驗證）

| # | 名稱 | 使用數 | 條件（驗證結果） | 對應 `ds_sales_report` 欄位 |
|---|------|--------|------------------|------------------------------|
| 1 | 汽油車篩選器 | 16 | `Energy Type = '油車'` | `energy_type` |
| 2 | 電動車篩選器 | 24 | `Energy Type = '電車'` | `energy_type` |
| 3 | 網路平台篩選器 | 6 | `Sales Source = '網路平台'` | `sales_source` |
| 4 | 車行篩選器 | 18 | `Sales Source = '車行'` | `sales_source` |
| 5 | 基隆公益青年篩選 | 17 | `SubsidyPlan CONTAINS '基隆公益'` | `subsidy_plan` |
| 6 | 排除空白資料 | 59 | `NOT (Model IS NULL)` | `model` |
| 7 | 20_29歲男性 | 1 | `AgeGroup = '20-29歲' AND sex = '男性'` | `age_group`, `sex` |
| 8 | 30-39歲男性 | 1 | `AgeGroup = '30-39歲' AND sex = '男性'` | 同上 |
| 9 | 40-49歲男性 | 1 | `AgeGroup = '40-49歲' AND sex = '男性'` | 同上 |
| 10 | 20-29女性 | 1 | `AgeGroup = '20-29歲' AND sex = '女性'` | 同上 |
| 11 | 30-39歲女性 | 1 | `AgeGroup = '30-39歲' AND sex = '女性'` | 同上 |
| 12 | 40-49歲女性 | 1 | `AgeGroup = '40-49歲' AND sex = '女性'` | 同上 |
| 13 | 年齡及車型篩選 | 2 | `Model STARTS WITH 'EV' AND age <> 0 AND age >= 20 AND sex <> '未填寫或格式錯誤'` | `model`, `age`, `sex` |
| 14 | FUN_性別 | 2 | `sex <> '未填寫或格式錯誤' AND Model CONTAINS 'EV060L'` | `sex`, `model` |
| 15 | RUN_性別 | 2 | `Model STARTS WITH 'EV076' AND Model <> 'EV076SZV'` | `model` |
| 16 | 76B_性別 | 2 | `Model = 'EV076SZV' AND sex <> '未填寫或格式錯誤'` | `model`, `sex` |
| 17 | 70B_性別 | 2 | `Model CONTAINS 'EV070' AND sex <> '未填寫或格式錯誤'` | `model`, `sex` |
| 18 | FUN_顏色 | 1 | `Model CONTAINS 'EV060'` | `model` |
| 19 | RUN_顏色 | 1 | `Model STARTS WITH 'EV076' AND Model <> 'EV076SZV'` | `model` |
| 20 | 70B_顏色 | 1 | `Model STARTS WITH 'EV070'` | `model` |
| 21 | 76B_顏色 | 1 | `Model = 'EV076SZV'` | `model` |
| 22 | （保留編號予後續新增） | — | — | — |

> 註：DataStudio 對「排除」子句以 `AND NOT(...)` 方式合併。以上條件表為等價的 SQL 邏輯。

---

## 二、相較原 spec（`01-datastudio-extraction.md`）的勘誤

| 項目 | 原 spec 推測 | 驗證結果 | 嚴重度 |
|------|-------------|---------|--------|
| 基隆公益青年篩選 | 未知 / 可能是 region/dealer 相關 | `SubsidyPlan CONTAINS '基隆公益'` | 🔴 高 |
| 70B_顏色 | `Model = 'EV070'` | `Model STARTS WITH 'EV070'`（含 EV070V 等變體） | 🟠 中 |
| FUN_顏色 | `Model STARTS WITH 'EV060'` | `Model CONTAINS 'EV060'` | 🟢 低（差異極小） |
| 76B_顏色 | `Model = 'EV076SZV'` | 相符 | — |

---

## 三、22 頁頁面清單（已從「報表頁數」窗格取得）

**群組 A：銷售統計（13 頁）**
1. 總車輛銷售（P1，`p_oe0r8mk2wd`）
2. 銷售機種及車型統計（P2，目前為隱藏頁）
3. 電動車銷售統計（P3，`p_v7fndtm3wd`）
4. 基隆公益青年（P4）
5. 電動車 - 網路平台銷售統計（P5）
6. 電動車 - 車行銷售統計（P6）
7. 電動車 - 佣金明細表（P7）
8. 電動車 - 台數統計（P8）
9. 油車銷售統計（P9）
10. 油車 - 網路平台銷售統計（P10）
11. 油車 - 車行銷售統計（P11）
12. 油車 - 佣金明細表（P12）
13. 油車 - 台數統計（P13）

**群組 B：大數據分析（9 頁）**
14. 基隆公益青年 地區X銷量（P14）
15. 基隆公益青年 區域X車型（P15）
16. 性別X年齡（P16）
17. 車型X性別（P17）
18. 車型X顏色（P18）
19. 性別X車型顏色（P19）
20. 通路銷售統計（P20）
21. 「基隆公益青年統計」的複本（P21）
22. 基隆公益青年 客群X車型分析（P22）

---

## 四、後續待執行稽核（P1–P22 各頁圖表設定）

待逐頁點擊每張圖表，記錄其屬性面板中的：
- 資料來源
- 維度、細目維度
- 指標（含聚合方式）
- 預設日期範圍
- 套用之篩選器（對應本文件第一節）
- 排序欄位與方向
- 表格分頁列數
- 圖表類型細節（堆疊方向、樣式）

目前已完成 P1 的全域篩選器稽核，22 個已 100% 驗證。

---

## 五、對應 Metabase 目前落差（初步）

以下落差從 `scripts/metabase_audit_state.py` 輸出（`/tmp/mb_audit.txt`）與本文件第一節對比得出，待完成 P1–P22 圖表稽核後補齊細節：

- **A**：P17 車型×性別 — 10 張卡片缺 Model 篩選器
- **B**：P18 車型×顏色 — 6 張卡片缺 Model 篩選器
- **C**：P19 性別×車型顏色 — 6 張卡片缺 Model 篩選器
- **D**：P22 客群×車型 — 6 張卡片缺 `年齡及車型篩選`（age+sex+model）
- **E**：11 張表格卡片 `dataset_query` 為空
- **F**：P3–P8（電車系列） — 缺硬篩選 `energy_type = '電車'`
- **G**：P5/P6/P10/P11 — 缺硬篩選 `sales_source = '網路平台' | '車行'`
- **H**：`基隆公益青年篩選` 定義取得後需套用於 P4、P21
- **I**：`排除空白資料`（Model IS NOT NULL）需套用於 59 張卡片
