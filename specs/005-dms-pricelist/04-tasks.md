# 開發任務（04-tasks）— dms_pricelist

## Spec
- [ ] 00-charter.md ✅
- [ ] 01-spec.md ✅
- [ ] 04-tasks.md ✅
- [ ] 05-acceptance.md ✅

## 模型
- [ ] `dms.vehicle.price`（vehicle_price.py）
- [ ] `dms.accessory`（accessory.py）
- [ ] `dms.accessory.price`（accessory_price.py）
- [ ] `dms.fee.schedule`（fee_schedule.py）
- [ ] `dms.commission.rule`（commission_rule.py）

## 視圖
- [ ] `views/vehicle_price_views.xml`（tree/form/search）
- [ ] `views/accessory_views.xml`（tree/form/search）
- [ ] `views/accessory_price_views.xml`（tree/form/search）
- [ ] `views/fee_schedule_views.xml`（tree/form/search）
- [ ] `views/commission_rule_views.xml`（tree/form/search）

## 安全性
- [ ] `security/ir.model.access.csv`（5 個模型全員讀寫）

## 模組骨架
- [ ] `__init__.py`
- [ ] `__manifest__.py`
- [ ] `models/__init__.py`

## 安裝驗證
- [ ] `--stop-after-init -i dms_pricelist` 無錯誤
- [ ] `/web/login` HTTP 200
- [ ] 5 個選單項目顯示正常
