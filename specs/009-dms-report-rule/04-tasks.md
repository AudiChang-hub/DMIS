# 04 — Tasks：開發任務清單（dms_report_rule）

## 模組骨架

- [x] 建立 `addons/dms_report_rule/__init__.py`
- [x] 建立 `addons/dms_report_rule/__manifest__.py`

## 資料模型

- [x] 建立 `models/__init__.py`
- [x] 建立 `models/report_rule.py`（`dms.report.rule`）
  - [x] 定義 8 個欄位
  - [x] 定義 Many2many 關聯表命名
  - [x] 實作 `action_preview_report()` 方法
  - [x] 使用 `safe_eval` 解析 `filter_domain`

## 安全性

- [x] 建立 `security/groups.xml`（user / admin 群組）
- [x] 建立 `security/record_rules.xml`（user-read / user-write record rules）
- [x] 建立 `security/ir.model.access.csv`

## 視圖

- [x] 建立 `views/report_rule_views.xml`
  - [x] Tree 視圖
  - [x] Form 視圖（含「預覽報表」按鈕）
  - [x] Search 視圖（Filter + GroupBy）
  - [x] 選單（報表分析 → 報表規則，sequence=40）

## 測試

- [x] 建立 `tests/__init__.py`
- [x] 建立 `tests/test_report_rule.py`
  - [x] TC-01：建立規則，驗證欄位預設值
  - [x] TC-02：預覽報表回傳正確 action dict（pivot 模式）
  - [x] TC-03：預覽報表回傳正確 action dict（graph 模式，bar）
  - [x] TC-04：非法 filter_domain 不崩潰，視為空 domain
  - [x] TC-05：record rule — 使用者不可讀取他人私有規則
  - [x] TC-06：record rule — 使用者可讀取他人公開規則

## 規格文件

- [x] `specs/009-dms-report-rule/00-charter.md`
- [x] `specs/009-dms-report-rule/01-spec.md`
- [x] `specs/009-dms-report-rule/02-clarify.md`
- [x] `specs/009-dms-report-rule/04-tasks.md`
- [x] `specs/009-dms-report-rule/05-acceptance.md`

## 驗證

- [x] `docker compose exec odoo ... -i dms_report_rule --stop-after-init` → 無 ERROR
- [x] `docker compose restart odoo` → Up，HTTP 200
