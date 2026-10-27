# 019-dms-commission 任務清單（03-tasks）

## Milestone 1：模組骨架

- [ ] 建立 `addons/dms_commission/` 完整目錄結構
- [ ] 建立 `__manifest__.py`
- [ ] 建立 `__init__.py` / `models/__init__.py`
- [ ] 建立 `security/ir.model.access.csv`（含全部 model 的 base.group_user 讀取 ACL）
- [ ] 安裝模組（`--install dms_commission`），確認無報錯
- [ ] `docker compose ps` + `smoke_odoo.sh` 通過

## Milestone 2：傭金規則模型

- [ ] `models/commission_rule.py`：`dms.commission.rule`
- [ ] `models/commission_dealer_rule.py`：`dms.commission.dealer.rule`（含 `compute_amount`）
- [ ] `models/commission_volume_rule.py`：`dms.commission.volume.rule`
- [ ] `views/commission_rule_views.xml`（tree/form/action）
- [ ] `views/commission_dealer_rule_views.xml`
- [ ] `views/commission_volume_rule_views.xml`
- [ ] `views/menu_views.xml`（傭金設定子選單）
- [ ] `__manifest__.py` 加入所有 views
- [ ] 升級驗證：CRUD 三個規則模型無報錯

## Milestone 3：激勵設定模型

- [ ] `models/incentive_type.py`：`dms.incentive.type`
- [ ] `models/incentive_rule.py`：`dms.incentive.rule`
- [ ] `views/incentive_type_views.xml`
- [ ] `views/incentive_rule_views.xml`
- [ ] `views/menu_views.xml` 加入激勵設定子選單
- [ ] 升級驗證：CRUD 正常

## Milestone 4：結案機制（核心）

- [ ] `models/commission_record.py`：`dms.commission.record`（含 `closed_month` compute）
- [ ] `models/incentive_delivery.py`：`dms.incentive.delivery`
- [ ] `models/sale_order_ext.py`：`_inherit='sale.order'`
  - [ ] `is_closed`, `closed_date`, `commission_record_id` 欄位
  - [ ] `action_close_order()`：結案 + 計算 + 產生 incentive.delivery
  - [ ] `action_reopen_order()`：撤銷 + voided + 重算
  - [ ] `_recompute_volume_bonus(dealer_id, closed_month)`：批次重算台數獎金
- [ ] `views/sale_order_ext_views.xml`：結案/撤銷按鈕
- [ ] `views/commission_record_views.xml`：唯讀 tree/form
- [ ] `views/incentive_delivery_views.xml`：tree/form，可標記 delivered
- [ ] 升級驗證：
  - [ ] 結案 → commission.record 正確產生
  - [ ] 結案 → incentive.delivery 正確產生
  - [ ] 第 N 台結案後台數獎金正確補算所有當月記錄
  - [ ] 撤銷結案 → record voided + 重算

## Milestone 5：報表

- [ ] `models/report_monthly.py`：月結 wizard
- [ ] `models/report_summary.py`：總報表 wizard
- [ ] `views/report_monthly_views.xml`：wizard form
- [ ] `views/report_summary_views.xml`：wizard form
- [ ] Excel 匯出（xlsxwriter，binary attachment 下載）
- [ ] `views/menu_views.xml` 加入報表子選單
- [ ] 驗證：選月份匯出 Excel，欄位完整

## Milestone 6：權限與 demo 資料

- [ ] `security/dms_commission_security.xml`：群組 `dms_commission.group_manager`
- [ ] `user_management` 繼承加入群組勾選
- [ ] `data/demo_commission_rules.xml`：示範規則（至少 1 條基礎、1 條車行覆蓋、1 條台數獎金）
- [ ] `__manifest__.py` 加入 demo data
- [ ] 更新 `docs/CHANGELOG.md`
- [ ] git commit + push
- [ ] `make smoke` 通過
