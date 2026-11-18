"""T-232 第 2 版：抽出訂單儲存服務前後的對照測試。

第 2 版把 `order_edit`、`order_operations`、`subsidy_data_update` 三個自動儲存端點「驗證通過後」的儲存流程搬到
`sales/services/order_save.py`，畫面行為必須完全不變。這裡用重構前的程式跑一組代表性情境，把結果（訂單與收支欄位、
收款列、配件、OrderChange、OrderEvent、庫存車狀態、回應）存成基準檔 `fixtures/order_save_parity_t232.json`；
重構後同一組情境必須得到一模一樣的結果。

重新產生基準檔（只在重構前的程式上做）：`ORDER_SAVE_PARITY_RECORD=1 python manage.py test sales.tests.test_order_save_parity_t232`
"""
import datetime
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import FileField, ForeignKey
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    AccessoryLine, OrderChange, OrderEvent, OrderOperationsProfile, OtherFeeLine, PaymentRecord, SalesOrder,
    VehicleColor, VehicleInventory, VehicleInventoryHistory,
)
from sales.tests import test_order_lifecycle as lifecycle
from sales.tests.test_order_workspace import form_data, formset_data

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "order_save_parity_t232.json"
RECORD = os.environ.get("ORDER_SAVE_PARITY_RECORD") == "1"
FROZEN = timezone.make_aware(datetime.datetime(2026, 8, 10, 10, 0))
SKIP_FIELDS = {"id", "number", "created_at", "updated_at", "editing_session", "editing_by", "editing_at"}
RESPONSE_KEYS = ("ok", "error", "errors", "message", "revision", "reload", "delivery_ready", "delivery_blockers",
                 "customer_balance_due", "customer_receivable_total", "discount", "subsidy_trade_in")
_recorded = {}


def _plain(value):
    if isinstance(value, datetime.datetime):
        return "<datetime>"
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _row(instance, skip=()):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in SKIP_FIELDS or field.name in skip:
            continue
        if isinstance(field, ForeignKey):
            related = getattr(instance, field.name)
            data[field.name] = None if related is None else str(related)
        elif field.name.endswith("_encrypted"):
            # 加密結果每次不同（含隨機 IV 與時間），只比有沒有存。
            data[field.name] = "<set>" if getattr(instance, field.attname) else ""
        elif isinstance(field, FileField):
            data[field.name] = getattr(instance, field.name).name or ""
        else:
            data[field.name] = _plain(getattr(instance, field.attname))
    return data


class OrderSaveParityTests(TestCase):
    setUp_base = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if RECORD and _recorded:
            existing = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
            existing.update(_recorded)
            GOLDEN.parent.mkdir(exist_ok=True)
            GOLDEN.write_text(json.dumps(existing, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=FIXED_NOW())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.setUp_base()
        admin = get_user_model().objects.create_superuser("admin", password="Parity-test-232!")
        self.client.force_login(admin)

    # ---- 送出內容：跟訂單頁一樣，從同一份表單的現值組出整張表單 ----
    def edit_payload(self, order, **changes):
        from sales.forms import OrderEditForm, OrderPageAccessoryFormSet, OrderPageOtherFeeFormSet
        order = SalesOrder.objects.get(pk=order.pk)
        data = form_data(OrderEditForm(instance=order))
        data.update(formset_data(OrderPageAccessoryFormSet(instance=order, form_kwargs={"allow_manual": True})))
        data.update(formset_data(OrderPageOtherFeeFormSet(instance=order, prefix="other_fees")))
        data.update({"_order_revision": str(order.revision), "_workspace": "1"})
        data.update({key: str(value) for key, value in changes.items()})
        return data

    def operations_payload(self, order, section, payments=False, **changes):
        from sales.forms import OrderOperationsForm
        from sales.services.order_workspace import payment_formset_for
        profile = OrderOperationsProfile.objects.get(order=order)
        data = form_data(OrderOperationsForm(instance=profile, prefix="operations", section=section))
        if payments:
            data.update(formset_data(payment_formset_for(SalesOrder.objects.get(pk=order.pk))))
        data.update({"_section": section, **{f"operations-{key}": str(value) for key, value in changes.items()}})
        return data

    def subsidy_payload(self, order, items=False, **changes):
        from sales.forms import SubsidyDataForm, SubsidyItemFormSet
        order = SalesOrder.objects.get(pk=order.pk)
        data = form_data(SubsidyDataForm(instance=order))
        if items:
            data.update(formset_data(SubsidyItemFormSet(instance=order, prefix="subsidy_items")))
        data.update({"_order_revision": str(order.revision), **{key: str(value) for key, value in changes.items()}})
        return data

    def post(self, name, order, data, workspace=True):
        headers = {"HTTP_X_ORDER_WORKSPACE": "1"} if workspace else {}
        return self.client.post(reverse(name, args=[order.pk]), data, **headers)

    # ---- 結果快照 ----
    def snapshot(self, order, response, vehicles=()):
        order = SalesOrder.objects.get(pk=order.pk)
        number = order.number
        profile = OrderOperationsProfile.objects.filter(order=order).first()
        result = {
            "status_code": response.status_code,
            "redirect": response.get("Location", "").replace(str(order.pk), "<pk>") if response.status_code in (301, 302) else "",
            "order": _row(order),
            "profile": _row(profile) if profile else None,
            "payments": [_row(row, skip={"order"}) for row in PaymentRecord.objects.filter(order=order).order_by("system_key", "entry_type", "item_name", "pk")],
            "accessories": [_row(row, skip={"order"}) for row in AccessoryLine.objects.filter(order=order).order_by("pk")],
            "other_fees": [_row(row, skip={"order"}) for row in OtherFeeLine.objects.filter(order=order).order_by("pk")],
            "changes": [{"reason": row.reason, "changes": _plain(row.changes), "actor": row.actor_name}
                        for row in OrderChange.objects.filter(order=order).order_by("pk")],
            "events": [{"type": row.event_type, "description": row.description, "actor": row.actor_name}
                       for row in OrderEvent.objects.filter(order=order).order_by("pk")],
            "vehicles": [{"status": vehicle.status, "history": list(VehicleInventoryHistory.objects.filter(vehicle=vehicle).order_by("pk").values_list("event_type", flat=True))}
                         for vehicle in VehicleInventory.objects.filter(pk__in=[v.pk for v in vehicles]).order_by("pk")],
        }
        if response.get("Content-Type", "").startswith("application/json"):
            payload = response.json()
            result["response"] = {key: _plain(payload[key]) for key in RESPONSE_KEYS if key in payload}
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        # 訂單編號含亂數、測試車引擎號碼含訂單 pk（PostgreSQL 序號不會隨測試回復），一律換成代號。
        return json.loads(text.replace(number, "<number>").replace(f"ENG-{order.pk}", "ENG-<pk>"))

    def check(self, name, order, response, vehicles=()):
        outcome = self.snapshot(order, response, vehicles)
        if RECORD:
            _recorded[name] = outcome
            return
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertIn(name, golden, "基準檔沒有這個情境，請在重構前的程式上重新產生。")
        self.assertEqual(outcome, golden[name])

    # ---- 訂車與配件（order_edit） ----
    def test_edit_owner_contact(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, owner_phone="0922000111", owner_email="parity@example.com",
                                 owner_address="臺北市中正區對照路 1 號", note="對照備註")
        self.check("edit_owner_contact", order, self.post("order_edit", order, data))

    def test_edit_price_and_plate_choice(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, vehicle_price="80000", plate_choice=SalesOrder.PlateChoice.NONE,
                                 plate_selection_fee="1000", plate_insurance_fee="")
        self.check("edit_price_and_plate_choice", order, self.post("order_edit", order, data))

    def test_edit_dealer_order(self):
        order, _vehicle = self.make_order(dealer=True)
        data = self.edit_payload(order, vehicle_price="72000", delivery_destination="對照託運站",
                                 delivery_method=SalesOrder.DeliveryMethod.CARRIER)
        self.check("edit_dealer_order", order, self.post("order_edit", order, data))

    def test_edit_completed_order_correction(self):
        order, _vehicle = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=FIXED_NOW(),
                                                      registration_date=datetime.date(2026, 8, 4),
                                                      registration_completed_at=FIXED_NOW(), final_plate_number="PAR-0001")
        data = self.edit_payload(order, vehicle_price="76000", note="完成後修正", confirm_completed_correction="on")
        self.check("edit_completed_order_correction", order, self.post("order_edit", order, data))

    def test_edit_change_color_unallocates(self):
        order, vehicle = self.make_order()
        other = VehicleColor.objects.create(vehicle_model=self.model, name="白")
        data = self.edit_payload(order, color=str(other.pk), _confirm_unallocate="1")
        self.check("edit_change_color_unallocates", order, self.post("order_edit", order, data), vehicles=(vehicle,))

    def test_edit_stale_revision(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, owner_phone="0922000111")
        SalesOrder.objects.filter(pk=order.pk).update(revision=order.revision + 5)
        self.check("edit_stale_revision", order, self.post("order_edit", order, data))

    def test_edit_invalid_email(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, owner_email="not-an-email")
        self.check("edit_invalid_email", order, self.post("order_edit", order, data))

    def test_edit_cancelled_order_is_locked(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, owner_phone="0922000111")
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.CANCELLED)
        self.check("edit_cancelled_order_is_locked", order, self.post("order_edit", order, data))

    def test_edit_without_workspace_header_redirects(self):
        order, _vehicle = self.make_order()
        data = self.edit_payload(order, owner_name="王大明")
        data.pop("_workspace")
        self.check("edit_without_workspace_header_redirects", order, self.post("order_edit", order, data, workspace=False))

    # ---- 收支、舊車、車控電池（order_operations） ----
    def test_operations_old_vehicle(self):
        order, _vehicle = self.make_order()
        data = self.operations_payload(order, "old_vehicle", old_vehicle_engine_number="PAR-ENG-1",
                                       old_vehicle_brand="山葉", old_vehicle_displacement_cc="49",
                                       old_vehicle_manufactured_on="201309", scrapped_on="2026-08-01")
        self.check("operations_old_vehicle", order, self.post("order_operations", order, data))

    def test_operations_fulfillment_with_password(self):
        order, _vehicle = self.make_order()
        data = self.operations_payload(order, "fulfillment", vehicle_control_account="parity-account",
                                       vehicle_control_password="secret-1234", battery_plan="對照方案")
        response = self.post("order_operations", order, data)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertTrue(profile.vehicle_control_password_encrypted)
        self.check("operations_fulfillment_with_password", order, response)

    def test_operations_finance_manual_amounts(self):
        order, _vehicle = self.make_order()
        data = self.operations_payload(order, "finance", payments=True, gift_expense="1200", shipping_expense="800",
                                       vehicle_cost="50000", other_income="300")
        self.check("operations_finance_manual_amounts", order, self.post("order_operations", order, data))

    def test_operations_stale_financial_revision(self):
        order, _vehicle = self.make_order()
        data = self.operations_payload(order, "old_vehicle", old_vehicle_brand="山葉")
        data["operations-financial_revision"] = "2000-01-01T00:00:00+00:00"
        self.check("operations_stale_financial_revision", order, self.post("order_operations", order, data))

    def test_operations_standalone_page(self):
        order, _vehicle = self.make_order()
        data = self.operations_payload(order, "standalone", payments=True, old_vehicle_brand="光陽", gift_expense="500")
        data.pop("_section")
        self.check("operations_standalone_page", order, self.post("order_operations", order, data, workspace=False))

    # ---- 汰舊補助資料（subsidy_data_update） ----
    def test_subsidy_old_owner(self):
        order, _vehicle = self.make_order()
        data = self.subsidy_payload(order, trade_in_plate="OLD-1234", old_owner_name="舊車主",
                                    old_owner_id_number="B123456789", old_owner_phone="0933000111")
        self.check("subsidy_old_owner", order, self.post("subsidy_data_update", order, data))

    def test_subsidy_with_item_formset(self):
        order, _vehicle = self.make_order()
        data = self.subsidy_payload(order, items=True, trade_in_plate="OLD-5678")
        self.check("subsidy_with_item_formset", order, self.post("subsidy_data_update", order, data))

    def test_subsidy_stale_revision(self):
        order, _vehicle = self.make_order()
        data = self.subsidy_payload(order, trade_in_plate="OLD-1234")
        SalesOrder.objects.filter(pk=order.pk).update(revision=order.revision + 3)
        self.check("subsidy_stale_revision", order, self.post("subsidy_data_update", order, data))

    def test_subsidy_exception_closed_is_locked(self):
        order, _vehicle = self.make_order()
        data = self.subsidy_payload(order, trade_in_plate="OLD-1234")
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.EXCEPTION_CLOSED)
        self.check("subsidy_exception_closed_is_locked", order, self.post("subsidy_data_update", order, data))


def FIXED_NOW():
    return FROZEN
