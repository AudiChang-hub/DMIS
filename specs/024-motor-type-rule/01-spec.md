# Spec 024 — 車種類型規則（dms.motor.type.rule）

## 背景

`ds.sales.report` SQL view 中的 `motor_type` 欄位原本以硬編碼 CASE/regex 判斷
車款類型（白牌電車、綠牌電車、微型電車、速克達、擋車、其他）。新增車款時需修改
Python 原始碼並重新部署，維運成本高，且容易誤分類（例：先前 `eReady` 兜底規則導致
`eReady Fun` 誤判為綠牌電車）。

## 目標

將 motor_type 判斷改為 UI 可維護的資料表，由業務或管理員自行維護分類規則。

## 模型 — `dms.motor.type.rule`

放在 `addons/dms_report_ds/models/motor_type_rule.py`。

| 欄位 | 型別 | 說明 |
|------|------|------|
| name | Char (required) | 規則名稱（顯示用，例：`電車-eReady 系列`）|
| sequence | Integer (default 10) | 評估順序，數字越小越先比對 |
| pattern | Char (required) | PostgreSQL POSIX 正則（套用於 `pname` 並使用 `~*` 不區分大小寫）|
| result | Selection (required) | `白牌電車`/`綠牌電車`/`微型電車`/`速克達`/`擋車`/`其他` |
| active | Boolean (default True) | 停用後不參與比對 |
| note | Text | 備註 |

## SQL view 套用方式

`ds.sales.report.init()` 啟動時：

1. 查詢 `dms_motor_type_rule` 表（active=true，依 sequence、id 排序）。
2. 若有規則，動態組合 `CASE WHEN s.pname ~* '<pattern>' THEN '<result>' ... ELSE '其他' END`。
3. 若資料表尚未存在或無規則，使用內建預設規則（與現行 hardcoded 相同）。
4. 規則 create/write/unlink 後自動呼叫 `ds.sales.report.init()` 重建 view。

## 預設規則（migration 安裝時載入）

| seq | name | pattern | result |
|-----|------|---------|--------|
| 10 | 白牌-eReady 系列 | `eReady` | 白牌電車 |
| 20 | 白牌-Gogoro 系列 | `Gogoro\|Pulse\|S2.?ABS` | 白牌電車 |
| 30 | 綠牌電車 | `JEGO\|VIVA\|EZ1\|EZZY\|Ur2` | 綠牌電車 |
| 40 | 微型電車 | `BOBE\|SHINE\|TSV57` | 微型電車 |
| 50 | 速克達 | `SUI\|Saluto\|NEX\|SWISH\|UQ\|UC\|UG\|UT\|Address` | 速克達 |
| 60 | 擋車 | `DR-?Z\|GSX\|GIXXER\|V-?STROM\|Burgman\|T-?MAX\|DS\d` | 擋車 |

未匹配 → `其他`。

## UI

選單：`銷售分析 → 設定 → 車種類型規則`。
List/Form 視圖含 sequence 拖曳排序、active toggle、pattern/result 編輯、
以及「重新套用規則」按鈕（手動觸發 view 重建，搭配自動 hook 雙保險）。

## 權限

- `base.group_system` 與 `dms_core.group_dms_manager`：完整 CRUD。
- 其他使用者：唯讀。

## 驗證

1. `make smoke` 通過。
2. `SELECT motor_type, COUNT(*) FROM ds_sales_report GROUP BY 1` 結果與重構前一致。
3. UI 新增一條測試規則 → 自動重建 view → 對應車款 motor_type 即時改變。
