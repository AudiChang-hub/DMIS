# 01 — Spec：虛擬欄位模組（dms_report_virtual）

## 模組基本資訊

| 項目 | 值 |
|------|----|
| 模組名稱 | `dms_report_virtual` |
| 顯示名稱 | 報表虛擬欄位 |
| 版本 | `16.0.1.0.0` |
| 依賴 | `dms_report_rule` |
| application | `True` |

---

## 資料模型 `dms.report.virtual.field`

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `name` | `Char` | ✓ | 虛擬欄位名稱（translate=True） |
| `code` | `Char` | ✓ | 系統代碼（unique，格式：`^[a-zA-Z][a-zA-Z0-9_]*$`） |
| `model_id` | `Many2one('ir.model')` | ✓ | 作用模型（domain: transient=False, model like dms.） |
| `model_name` | `Char` | | related='model_id.model'，store=True |
| `compute_type` | `Selection` | ✓ | `rule`（規則匹配），預設 `rule`，預留擴充 |
| `rule_ids` | `One2many` | | → `dms.report.virtual.field.rule`，依 sequence 排序 |
| `rule_count` | `Integer` | | 計算欄位（len of rule_ids） |
| `default_value` | `Char` | | 所有規則未匹配時回傳值（translate=True） |
| `owner_id` | `Many2one('res.users')` | ✓ | 建立者（default=env.user） |
| `public` | `Boolean` | | 公開共享，預設 False |
| `active` | `Boolean` | | 啟用，預設 True |
| `color` | `Integer` | | 顏色標籤 |

### SQL Constraints
- `('code_unique', 'UNIQUE(code)', '代碼必須唯一。')`

### 方法

| 方法 | 說明 |
|------|------|
| `compute_value(record)` | 遍歷 rule_ids（依 sequence），回傳第一個匹配的輸出值；未匹配回傳 default_value |
| `compute_value_with_log(record)` | 同上，額外回傳評估日誌文字（tuple: value, log_str） |
| `action_open_test_wizard()` | 開啟測試精靈視窗 |

---

## 資料模型 `dms.report.virtual.field.rule`

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| `virtual_field_id` | `Many2one('dms.report.virtual.field')` | ✓ | 隸屬的虛擬欄位 |
| `sequence` | `Integer` | | 匹配順序，預設 10 |
| `match_type` | `Selection` | ✓ | `contains`（包含字串）/ `regex`（正則）/ `python`（Python 表達式） |
| `field_name` | `Char` | | 比對欄位路徑（如 dealer_id.name）；contains/regex 必填 |
| `condition` | `Char` | | 條件值 — contains 包含字串，regex 正則表達式 |
| `python_expression` | `Text` | | Python match_type 時的表達式（safe_eval，可用 record、re、math） |
| `value` | `Char` | ✓ | 匹配成功的輸出值（translate=True） |
| `description` | `Text` | | 規則說明 |

### 匹配邏輯（`_eval_rule(record)` → `(matched: bool, output: str)`）

- **contains**：`condition in _get_field_value(record)` → True, value
- **regex**：`re.search(condition, _get_field_value(record))` → True, value
- **python**：`safe_eval(python_expression, {'record': record, 're': re, 'math': math})`
  - 若結果 truthy 且非 `True`：輸出即為結果（str 轉換）
  - 若結果為 `True`：使用 `value` 欄位
  - 若結果 falsy：未匹配

### Constraints（api.constrains）

- `contains / regex`：`field_name` 必填
- `python`：`python_expression` 必填
- `condition` 正則格式：`match_type=regex` 時於儲存前驗證 `re.compile(condition)` 不崩潰

---

## 擴充 `dms.report.rule`（_inherit）

新增欄位：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `virtual_dimension_ids` | `Many2many('dms.report.virtual.field')` | 關聯表 `dms_report_rule_vf_rel`（rule_id, vf_id） |

覆寫方法：

- `action_preview_report()`：若有 `virtual_dimension_ids`，改呼叫 `_action_virtual_preview()`；否則呼叫 super()
- `_action_virtual_preview()`：計算虛擬分組並建立 `dms.report.vf.preview`，回傳開啟精靈的 action

---

## 精靈模型

### `dms.report.vf.test.wizard`（TransientModel）

| 欄位 | 說明 |
|------|------|
| `virtual_field_id` | 測試的虛擬欄位 |
| `model_name` | related from virtual_field_id.model_id.model |
| `record_id` | Integer：要測試的記錄 ID |
| `result_value` | Char readonly：計算結果 |
| `computation_log` | Text readonly：評估日誌 |
| `computation_done` | Boolean |

方法：`action_compute() → 重新開啟精靈展示結果`

### `dms.report.vf.preview`（TransientModel）

精靈容器，儲存預覽報表的彙整結果：

| 欄位 | 說明 |
|------|------|
| `rule_id` | 報表規則 |
| `virtual_field_id` | 虛擬欄位 |
| `truncated` | Boolean：結果是否已截斷（>1000 筆） |
| `measure_label_1/2/3` | 指標欄位顯示名稱（最多 3 個） |
| `line_ids` | → dms.report.vf.preview.line |

### `dms.report.vf.preview.line`（TransientModel）

| 欄位 | 說明 |
|------|------|
| `preview_id` | → dms.report.vf.preview |
| `virtual_value` | 虛擬欄位值（分組名稱） |
| `record_count` | 該分組記錄數 |
| `measure_total_1/2/3` | 各指標合計（Float） |

---

## 選單結構

```
報表分析（dms_report）
├── 銷售報表                    seq=10
├── 利潤報表                    seq=20
├── 傭金報表                    seq=30
├── 報表規則（dms_report_rule）  seq=40
└── 虛擬欄位（dms_report_virtual）  seq=50 ← 新增
```

---

## 安全性設定

### 群組

| 群組 | ID | 說明 |
|------|----|------|
| 虛擬欄位使用者 | `group_dms_report_virtual_user` | 建立/管理自己的虛擬欄位；讀取公開欄位 |
| 虛擬欄位管理員 | `group_dms_report_virtual_admin` | 管理所有虛擬欄位（implied_ids includes user） |

### Record Rules（`dms.report.virtual.field`）

| 規則 | 群組 | 條件 |
|------|------|------|
| user-read | user | `['|', ('owner_id','=',user.id), ('public','=',True)]` |
| user-write | user | `[('owner_id','=',user.id)]` |
| admin-all-read | admin | `[(1,'=',1)]` |
| admin-all-write | admin | `[(1,'=',1)]` |

同樣的規則也適用於 `dms.report.virtual.field.rule`（透過 `virtual_field_id.owner_id` 關聯）。
