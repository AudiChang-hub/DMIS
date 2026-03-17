# 01 — Spec：報表規則設定模組（dms_report_rule）

## 模組基本資訊

| 項目 | 值 |
|------|----|
| 模組名稱 | `dms_report_rule` |
| 顯示名稱 | 報表規則設定 |
| 版本 | `16.0.1.0.0` |
| 依賴 | `dms_report` |
| application | `True` |

---

## 資料模型 `dms.report.rule`

| 欄位名稱 | 型別 | 必填 | 說明 |
|----------|------|------|------|
| `name` | `Char` | ✓ | 報表名稱 |
| `model_id` | `Many2one('ir.model')` | ✓ | 指定分析的資料模型（限 `dms.` 開頭非暫存模型） |
| `dimension_ids` | `Many2many('ir.model.fields')` | | 維度欄位（group by）；`ttype` 限 `date/datetime/many2one/selection/char` |
| `measure_ids` | `Many2many('ir.model.fields')` | | 指標欄位（聚合）；`ttype` 限 `float/integer/monetary` |
| `chart_type` | `Selection` | ✓ | `pivot`／`bar`／`line`／`pie`，預設 `bar` |
| `filter_domain` | `Text` | | Odoo domain 字串，使用 `safe_eval` 解析 |
| `active` | `Boolean` | | 啟用，預設 `True` |
| `owner_id` | `Many2one('res.users')` | ✓ | 建立者，預設當前使用者 |
| `public` | `Boolean` | | 是否公開，預設 `False` |

### Many2many 關聯表命名

- `dimension_ids`：關聯表 `dms_report_rule_dimension_rel`（含 `rule_id`, `field_id`）
- `measure_ids`：關聯表 `dms_report_rule_measure_rel`（含 `rule_id`, `field_id`）

---

## 方法

### `action_preview_report()`

回傳 `dict`（`ir.actions.act_window`）：

```python
{
    'type': 'ir.actions.act_window',
    'name': self.name,
    'res_model': self.model_id.model,
    'view_mode': 'pivot,tree' if chart_type == 'pivot' else 'graph,tree',
    'domain': safe_eval(self.filter_domain or '[]'),
    'context': {
        'group_by': [f.name for f in self.dimension_ids],
        'pivot_measures': [f.name for f in self.measure_ids],  # pivot 用
        'graph_type': chart_type if chart_type != 'pivot' else None,
    },
}
```

> `filter_domain` 不合法時，記錄警告並視為空 domain `[]`，不應崩潰。

---

## 視圖

### Tree / List 視圖（`view_report_rule_tree`）

顯示欄位：`name`、`model_id`、`chart_type`、`public`、`owner_id`、`active`

### Form 視圖（`view_report_rule_form`）

- 上方資訊：`name`（必填），`active`、`public`、`owner_id`
- 第一頁（General）：
  - `model_id`（必填，選擇後清空 dimension/measure）
  - `dimension_ids`（Many2many widget，domain 依 `model_id` 動態篩選）
  - `measure_ids`（同上，限數值型態欄位）
  - `chart_type`
  - `filter_domain`（text area，附提示說明）
- 底部按鈕：「預覽報表」（呼叫 `action_preview_report`）

### Search 視圖（`view_report_rule_search`）

- 搜尋欄位：`name`、`model_id`、`owner_id`
- Filter：「我的規則」（`owner_id = uid`）、「公開規則」（`public = True`）、「已停用」（`active = False`）
- GroupBy：`model_id`、`chart_type`、`owner_id`

---

## 選單

| 項目 | 位置 | sequence |
|------|------|----------|
| 報表規則 | 報表分析 → 子選單 | 40 |

---

## 安全性設定

### 群組

| 群組 | 識別碼 | 說明 |
|------|--------|------|
| 報表規則使用者 | `group_dms_report_rule_user` | 建立並管理自己的規則；瀏覽公開規則 |
| 報表規則管理員 | `group_dms_report_rule_admin` | 新增、編輯、刪除所有規則 |

### ir.model.access.csv

| model | group | R | W | C | D |
|-------|-------|---|---|---|---|
| `dms.report.rule` | user | 1 | 1 | 1 | 1 |
| `dms.report.rule` | admin | 1 | 1 | 1 | 1 |

> record rules 負責實例層级的存取控制。

### Record Rules

| 規則 | 對象 | 條件 |
|------|------|------|
| user-read | User 群組 read | `owner_id == user OR public == True` |
| user-write | User 群組 write/unlink | `owner_id == user` |
