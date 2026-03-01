# 開發任務（04-tasks）— dms_pricelist

## Spec
- [x] 00-charter.md ✅
- [x] 01-spec.md ✅
- [x] 04-tasks.md ✅
- [x] 05-acceptance.md ✅

## 模型
- [ ] `dms.vehicle.price`（vehicle_price.py）
- [ ] `dms.installment.plan`（installment_plan.py）—新增
- [ ] `dms.accessory`（accessory.py）—合併精品品項+售價
- [ ] `dms.ev.fee.schedule`（fee_schedule.py）—重命名+欄位改寫
- [ ] `dms.commission.rule`（commission_rule.py）

## 視圖
- [ ] `views/vehicle_price_views.xml`（tree/form含分期O2m/search）
- [ ] `views/accessory_views.xml`（tree/form/search，重命名為精品售價）
- [ ] `views/fee_schedule_views.xml`（tree/form含油車提示/search）
- [ ] `views/commission_rule_views.xml`（tree/form/search）

## 安全性
- [ ] `security/ir.model.access.csv`（5 個模型全員讀寫）

## 模組骨架
- [x] `__init__.py`
- [ ] `__manifest__.py`（移除 accessory_price_views.xml）
- [ ] `models/__init__.py`（加 installment_plan，移 accessory_price）

## 安裝驗證
- [ ] `--stop-after-init -i dms_pricelist` 無錯誤
- [ ] `/web/login` HTTP 200
- [ ] 4 個選單項目顯示正常
