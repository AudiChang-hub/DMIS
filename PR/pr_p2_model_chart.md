# PR: 補強 P2 車型圖表與篩選連動

**分支**: `feat/015-dms-product-rebuild` → `main`

**Commit**: `de5bcfe` 補強 P2 車型圖表與篩選連動

---

## 變更摘要

### 1. P2 新增車型月趨勢圖的可重建腳本
- 在 Metabase dashboard 建置腳本中，為 P2 新增 `P2-3 銷售車型×領牌年月（長條圖）`
- 保留既有 `P2-1` 與 `P2-2`，不覆寫原本兩張正確圖表
- 對應 dashboard 版位同步擴充為三張卡

### 2. 補上 live dashboard 的 filter mappings 修復腳本
- 新增 `scripts/metabase_add_p2_model_chart.py`
- 腳本會以 `P2-1` 為來源複製查詢，將 breakout 改為 `model`
- 若 `P2-3` 已存在，腳本會補齊並修正 `parameter_mappings`
- 確保 P2-3 與同頁既有的「領牌年月 / 銷售來源」dashboard filters 連動

### 3. 規格同步更新
- 更新 P2 dashboard 圖表數說明，由 2 張改為 3 張
- 補充 P2 新圖的用途、限制與 filter mapping 要求
- 將此需求納入 gap analysis，避免後續重建遺漏

---

## 變更檔案

| 檔案 | 說明 |
|---|---|
| `scripts/metabase_setup_dashboards.py` | P2 建置時新增 `P2-3` 並調整 dashboard 版位 |
| `scripts/metabase_add_p2_model_chart.py` | 新增 live 補卡與 filter mappings 修復腳本 |
| `specs/021-datastudio-report/02-metabase-dashboards.md` | P2 圖表數更新為 3 |
| `specs/021-datastudio-report/04-chart-details.md` | 補充 P2-3 圖表與 filter mapping 規格 |
| `specs/021-datastudio-report/05-gap-analysis.md` | 新增 P2 model 趨勢圖補強缺口 |

---

## 驗證步驟

### 基線檢查

```bash
cd /home/audi/project/DMIS
make up
docker compose ps
make smoke
```

### 本次變更驗證

```bash
cd /home/audi/project/DMIS

# 1. 驗證腳本語法
python3 -m py_compile scripts/metabase_setup_dashboards.py
python3 -m py_compile scripts/metabase_add_p2_model_chart.py

# 2. 套用 / 修復 live P2 第三張圖與 filter mappings
python3 scripts/metabase_add_p2_model_chart.py
```

### UI 驗證

1. 開啟 `https://dmis.moto-core.com/web#action=474&menu_id=380`
2. 確認 P2 頁面同時存在以下三張卡：
   - `P2-1 銷售機種×領牌年月（長條圖）`
   - `P2-2 銷售機種明細`
   - `P2-3 銷售車型×領牌年月（長條圖）`
3. 切換 `銷售來源` 篩選，例如選擇 `網路平台`
4. 確認 P2-1、P2-2、P2-3 都會一起重送查詢並套用相同 filter 參數

---

## 實測結果

- `python3 -m py_compile scripts/metabase_setup_dashboards.py`：通過
- `python3 -m py_compile scripts/metabase_add_p2_model_chart.py`：通過
- live dashboard `P2-3` 已存在，card id = `114`
- `parameter_mappings` 已補上：
  - `ds_license_ym`
  - `ds_sales_source`
- 正式站 UI 實測：`銷售來源 = 網路平台` 時，P2-3 會與 P2-1 / P2-2 一樣帶入同組 filter 參數