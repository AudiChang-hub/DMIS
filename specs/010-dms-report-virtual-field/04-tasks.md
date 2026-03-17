# 04 — Tasks：開發任務清單（dms_report_virtual）

## 模組骨架

- [x] 建立 `addons/dms_report_virtual/__init__.py`
- [x] 建立 `addons/dms_report_virtual/__manifest__.py`

## 資料模型

- [x] `models/__init__.py`
- [x] `models/report_virtual_field.py`（`dms.report.virtual.field`）
  - [x] 定義所有欄位（name/code/model_id/compute_type/rule_ids/default_value/owner_id/public/active/color）
  - [x] `_check_code` constrains（格式驗證）
  - [x] `compute_value(record)` 方法
  - [x] `compute_value_with_log(record)` 方法（包含評估日誌）
  - [x] `action_open_test_wizard()` 方法
- [x] `models/report_virtual_field_rule.py`（`dms.report.virtual.field.rule`）
  - [x] 定義所有欄位
  - [x] `_get_field_value(record)` 安全點號路徑遍歷
  - [x] `_eval_rule(record) → (matched, output)` 三種匹配類型
  - [x] `_check_rule_fields` constrains（contains/regex 必填 field_name；python 必填 expression）
  - [x] `_check_regex` constrains（regex 格式驗證）
- [x] `models/report_rule_extend.py`（`_inherit = 'dms.report.rule'`）
  - [x] `virtual_dimension_ids` Many2many 欄位
  - [x] 覆寫 `action_preview_report()`
  - [x] 實作 `_action_virtual_preview()`

## Wizard

- [x] `wizard/__init__.py`
- [x] `wizard/vf_test_wizard.py`（`dms.report.vf.test.wizard`）
- [x] `wizard/vf_preview_wizard.py`（`dms.report.vf.preview` + `dms.report.vf.preview.line`）

## 安全性

- [x] `security/groups.xml`（user / admin 群組）
- [x] `security/ir.model.access.csv`
- [x] `security/record_rules.xml`

## 視圖

- [x] `views/report_virtual_field_views.xml`
  - [x] Tree / Form / Search 視圖
  - [x] Action + 主選單
- [x] `views/report_rule_extend_views.xml`（繼承 dms.report.rule Form）
- [x] `views/vf_test_wizard_views.xml`
- [x] `views/vf_preview_wizard_views.xml`

## 測試

- [x] `tests/__init__.py`
- [x] `tests/test_report_virtual_field.py`（7 個 TC）
  - [x] TC-01：建立虛擬欄位，驗證預設值
  - [x] TC-02：contains 規則匹配成功
  - [x] TC-03：regex 規則匹配（含 `|` 多關鍵字）
  - [x] TC-04：python 規則返回自訂值
  - [x] TC-05：所有規則未匹配返回 default_value
  - [x] TC-06：action_preview_report 含虛擬維度，返回精靈 action
  - [x] TC-07：record rule — 使用者無法讀取他人私有虛擬欄位

## 規格文件

- [x] `specs/010-dms-report-virtual-field/00-charter.md`
- [x] `specs/010-dms-report-virtual-field/01-spec.md`
- [x] `specs/010-dms-report-virtual-field/02-clarify.md`
- [x] `specs/010-dms-report-virtual-field/04-tasks.md`
- [x] `specs/010-dms-report-virtual-field/05-acceptance.md`

## 驗證

- [x] `-i dms_report_virtual --stop-after-init` → 無 ERROR
- [x] `docker compose restart odoo && docker compose ps` → Up, HTTP 200
