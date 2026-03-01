# 任務清單（04-tasks）— dms_customer

## Step 1：Spec
- [x] 00-charter.md
- [x] 01-spec.md
- [x] 04-tasks.md
- [x] 05-acceptance.md

## Step 2：模組骨架
- [ ] `addons/dms_customer/__init__.py`
- [ ] `addons/dms_customer/__manifest__.py`
- [ ] `addons/dms_customer/models/__init__.py`

## Step 3：模型
- [ ] `models/res_partner.py`：繼承 res.partner，新增 is_dms_customer / id_number / dms_birthday / dms_birthday_roc / address_registered / old_vehicle_ids
- [ ] `models/old_vehicle.py`：dms.old.vehicle

## Step 4：視圖
- [ ] `views/customer_views.xml`：res.partner list/form/search + action + menu（頂層 App）
- [ ] form 含 3 頁籤：基本資料 / 地址 / 舊車資訊
- [ ] old_vehicle embedded tree in form

## Step 5：ACL
- [ ] `security/ir.model.access.csv`：dms.old.vehicle 全員讀寫

## Step 6：升級驗證
- [ ] restart odoo
- [ ] CLI upgrade dms_customer
- [ ] HTTP 200
