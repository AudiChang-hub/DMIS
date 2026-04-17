# PR: Metabase Dashboard 改善 — 車種分類 + 全幅排版 + 中文化 + Crossfilter

**分支**: `feat/015-dms-product-rebuild` → `main`

---

## 變更摘要

### 1. 車種分類修正 (`ds_sales_report` SQL View)
- `motor_type` CASE WHEN 改為 `~*`（case-insensitive）
- 補齊遺漏的車型歸類：
  - **白牌電車**：新增 `e-moving EV0xx` 系列（含前綴匹配）、`Gogoro`、`Pulse`
  - **綠牌電車**：新增 `eReady` 系列
  - **速克達**：新增 `SUI`、`Saluto`、`NEX`、`SWISH`、`Address`
  - **擋車**：新增 `GIXXER`、`V-STROM`、`Burgman`、`T-MAX`
- **修正前**：「其他」佔 94%（1,487/1,582）
- **修正後**：速克達 573、白牌電車 483、綠牌電車 456、擋車 49、微型電車 13、其他 8

### 2. Dashboard 全幅排版
- 所有 21 個 Dashboard 從 18 欄擴展至 24 欄（Metabase grid 滿版）
- 消除右側 25% 空白浪費
- 腳本：`scripts/metabase_widen_dashboards.py`

### 3. 欄位中文化
- 42 個 `ds_sales_report` 欄位 display_name 全部改為繁體中文
- 例如：license_date→領牌日期、motor_type→車種類型、sales_source→銷售來源
- 腳本：`scripts/metabase_i18n_zh.py`

### 4. Crossfilter 互動
- 47 個 dashcard 加入 `click_behavior: crossfilter` 設定
- 腳本：`scripts/metabase_apply_crossfilter.py`

---

## 變更檔案

| 檔案 | 說明 |
|---|---|
| `addons/dms_report_ds/models/ds_sales_report.py` | motor_type + energy_type CASE WHEN regex 修正 |
| `scripts/metabase_widen_dashboards.py` | (新增) Dashboard 排版擴展腳本 |
| `scripts/metabase_i18n_zh.py` | (新增) 欄位中文化腳本 |
| `scripts/metabase_apply_crossfilter.py` | (新增) Crossfilter 設定腳本 |

---

## 驗證步驟

```bash
# 1. 確認服務正常
make up
docker compose ps

# 2. Smoke test
make smoke

# 3. 驗證 SQL View（車種分類）
docker compose exec db psql -U odoo -d dmis_dev -c "
  SELECT motor_type, COUNT(*) 
  FROM ds_sales_report 
  GROUP BY motor_type 
  ORDER BY count DESC;
"
# 預期：速克達/白牌電車/綠牌電車 各數百筆，其他 < 10 筆

# 4. 驗證 Metabase Dashboard
# 開啟 https://dmis.moto-core.com/metabase/dashboard/2
# 確認：
#   - P1-3 車種類型長條圖顯示 6 種分類
#   - 圖表佔滿全寬（無右側空白）
#   - 軸標籤/圖例均為中文

# 5. 如需重新套用 Metabase 設定（新環境）
python3 scripts/metabase_widen_dashboards.py --apply
python3 scripts/metabase_i18n_zh.py --apply
python3 scripts/metabase_apply_crossfilter.py --apply
```

---

## 截圖驗證

已於瀏覽器逐頁確認 P1~P22 共 21 個 Dashboard：
- ✅ 全部 24 欄全寬排版
- ✅ 42 個欄位中文化
- ✅ 車種分類 6 類正確顯示（速克達、白牌電車、綠牌電車、擋車、微型電車、其他）
