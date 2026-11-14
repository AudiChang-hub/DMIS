"""T-147（使用者 2026-11-11）：領牌完成後任何人都能改，改日期重算系統值、人工值保留。

2026-11-14 T-172 A′：存檔不再自動完成，按「確認完成」才完成（見 test_registration_confirm_t172）；
完成後仍是所有人都能改（第 2 題選 (2)），本檔其餘行為不變。
- 按「確認完成」完成領牌，帶入規費、成本、獎勵、傭金，訂單轉待交車；文件選填。
- 任何人、任何狀態（含已交車、已完成）都能改；改日期依新日期重算，人工值保留；只改車牌不重算。
- 每次修改都寫 OrderChange（改前、改後）。
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    OrderChange,
    OrderOperationsProfile,
    SalesOrder,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
    VehicleSettlementCostRule,
)
from sales.services.dealer_commission import create_volume_bonus_settlement
from sales.services.order_steps import order_step_url
from sales.tests import test_volume_bonus_conditions as bonus_fixtures
from sales.tests.campaign_helpers import legacy_incentive_rule

STATIC = Path(settings.BASE_DIR) / "static"


class RegistrationEditTests(TestCase):
    def setUp(self):
        from sales.services.print_company import initialize_company

        self.admin = get_user_model().objects.create_superuser("admin", "", "test-pass-123")
        self.client.force_login(self.admin)
        store = Store.objects.create(name="總店", code="HQ")
        self.model = VehicleModel.objects.create(brand="SUZUKI", name="SUI 125", energy_type=VehicleModel.EnergyType.GAS,
                                                 displacement_cc=125)
        color = VehicleColor.objects.create(vehicle_model=self.model, name="灰")
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"),
                                                 effective_from=date(2026, 1, 1), effective_to=date(2026, 10, 31))
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("62000"),
                                                 effective_from=date(2026, 11, 1))
        legacy_incentive_rule(vehicle_model=self.model, sales_bonus=Decimal("1000"),
                                            effective_from=date(2026, 1, 1), effective_to=date(2026, 10, 31))
        legacy_incentive_rule(vehicle_model=self.model, sales_bonus=Decimal("1500"),
                                            effective_from=date(2026, 11, 1))
        self.order = SalesOrder(
            owner_name="測試車主", owner_phone="0900000000", owner_address="測試地址", owner_id_number="A100000001",
            vehicle_model=self.model, color=color, vehicle_price=Decimal("75000"), deposit_amount=Decimal("5000"),
            actual_balance=Decimal("70000"), id_verified=True, status=SalesOrder.Status.ALLOCATION_PENDING,
        )
        initialize_company(self.order, self.admin)
        self.order.save()
        vehicle = VehicleInventory.objects.create(
            vehicle_model=self.model, color=color, engine_number="ENG-T147", ownership_store=store, location_store=store,
        )
        self.order.allocate(vehicle)
        self.save_url = reverse("registration_save", args=[self.order.pk])

    def autosave(self, client=None, **data):
        response = (client or self.client).post(self.save_url, data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.order.refresh_from_db()
        return response.json()

    def profile(self):
        return OrderOperationsProfile.objects.get(order=self.order)

    def complete(self, registration_date="2026-10-29", plate="ABC-1234"):
        """填好日期與車牌（自動儲存），再按「確認完成」（T-172 A′）。回傳自動儲存的回應。"""
        payload = self.autosave(registration_date=registration_date, final_plate_number=plate)
        self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()
        return payload

    def test_date_and_plate_autosave_waits_for_confirm_then_completes(self):
        payload = self.autosave(registration_date="2026-10-29", final_plate_number="ABC-1234")
        self.assertFalse(self.order.is_registration_complete, "存檔不自動完成，要按確認完成（T-172 A′）")
        self.assertFalse(payload["reload"])
        self.assertIn('data-lock-confirm="確認領牌完成"', payload["registration_html"])
        self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)
        self.assertEqual(self.order.status, SalesOrder.Status.DELIVERY_PENDING)
        profile = self.profile()
        self.assertEqual(profile.vehicle_cost, Decimal("60000"))
        self.assertIsNotNone(profile.vehicle_cost_locked_at)
        self.assertEqual(profile.sales_bonus, Decimal("1000"))
        self.assertFalse(self.order.registration_documents.exists(), "文件選填")
        page = self.client.get(order_step_url(self.order.pk, "registration")).content.decode()
        self.assertNotIn("data-lock-auto", page)
        self.assertNotIn('data-lock-confirm="確認領牌完成"', page, "確認後不再顯示確認按鈕")

    def test_date_only_saves_as_planned_and_does_not_complete(self):
        payload = self.autosave(registration_date="2026-10-29", final_plate_number="")
        self.assertTrue(payload["ok"], "日期與車牌可以分別事先填（T-172 A′）")
        self.assertEqual(self.order.registration_date, date(2026, 10, 29))
        self.assertFalse(self.order.is_registration_complete)

    def test_non_admin_can_edit_on_delivered_order(self):
        from sales.access.models import ScreenAccessGrant, UserAccessState

        self.complete()
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=timezone.now())
        staff = get_user_model().objects.create_user("staff147", password="test-pass-123")
        UserAccessState.objects.update_or_create(user=staff, defaults={"configured": True})
        ScreenAccessGrant.objects.create(user=staff, screen_key="work", view=True, operate=True)
        client = self.client_class()
        client.force_login(staff)
        payload = self.autosave(client=client, registration_date="2026-11-10", final_plate_number="abd-5678")
        self.assertTrue(payload["ok"])
        self.assertEqual((self.order.registration_date, self.order.final_plate_number), (date(2026, 11, 10), "ABD-5678"))
        self.assertEqual(self.order.status, SalesOrder.Status.COMPLETED, "狀態不變")
        self.assertFalse(payload["reload"])

    def test_date_change_recalculates_system_values_and_keeps_manual(self):
        self.complete()
        profile = self.profile()
        before_tax = profile.registration_tax_expense
        # 人工改過的強制險支出與牌險費保留不動。
        profile.compulsory_insurance_expense = Decimal("777")
        profile.manual_financial_fields = sorted(set(profile.manual_financial_fields or []) | {"compulsory_insurance_expense"})
        profile.save(update_fields=["compulsory_insurance_expense", "manual_financial_fields", "updated_at"])
        SalesOrder.objects.filter(pk=self.order.pk).update(plate_insurance_auto=False, plate_insurance_fee=Decimal("4321"))
        SalesOrder.objects.filter(pk=self.order.pk).update(status=SalesOrder.Status.COMPLETED, delivered_at=timezone.now())

        self.autosave(registration_date="2026-11-10", final_plate_number="ABC-1234")
        profile = self.profile()
        self.assertEqual(profile.vehicle_cost, Decimal("62000"), "成本依新領牌日重算")
        self.assertIsNotNone(profile.vehicle_cost_locked_at, "重算後仍固定，不隨主檔調價")
        self.assertEqual(profile.sales_bonus, Decimal("1500"), "獎勵依新領牌日重算")
        self.assertIsNotNone(profile.incentive_locked_at)
        self.assertNotEqual(profile.registration_tax_expense, before_tax, "已完成的單規費也依新日期重算")
        self.assertEqual(profile.compulsory_insurance_expense, Decimal("777"))
        self.assertEqual(self.order.plate_insurance_fee, Decimal("4321"))

    def test_manual_vehicle_cost_kept_on_date_change(self):
        self.complete()
        OrderOperationsProfile.objects.filter(order=self.order).update(vehicle_cost=Decimal("55555"), vehicle_cost_manual=True)
        self.autosave(registration_date="2026-11-10", final_plate_number="ABC-1234")
        self.assertEqual(self.profile().vehicle_cost, Decimal("55555"))

    def test_plate_only_change_does_not_recalculate(self):
        self.complete()
        VehicleSettlementCostRule.objects.filter(amount=Decimal("60000")).update(amount=Decimal("61000"))
        before = self.profile()
        self.autosave(registration_date="2026-10-29", final_plate_number="ABC-9999")
        after = self.profile()
        self.assertEqual(self.order.final_plate_number, "ABC-9999")
        for field in ("vehicle_cost", "sales_bonus", "registration_tax_expense", "dealer_commission_expense"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)

    def test_order_change_records_before_and_after(self):
        self.complete()
        self.autosave(registration_date="2026-11-10", final_plate_number="ABD-5678")
        change = OrderChange.objects.filter(order=self.order).latest("pk")
        self.assertEqual(change.changes["實際領牌日期"], {"before": "2026/10/29", "after": "2026/11/10"})
        self.assertEqual(change.changes["車牌號碼"], {"before": "ABC-1234", "after": "ABD-5678"})
        first = OrderChange.objects.filter(order=self.order, changes__has_key="車牌號碼").order_by("pk").first()
        self.assertEqual(first.changes["車牌號碼"], {"before": "未填", "after": "ABC-1234"})
        self.assertEqual(first.changes["預計領牌日期"], {"before": "未填", "after": "2026/10/29"}, "確認前改的是預計日")

    def test_completion_waits_for_cost_rule_then_button_finishes(self):
        VehicleSettlementCostRule.objects.all().delete()
        payload = self.complete()
        self.assertFalse(self.order.is_registration_complete, "找不到成本規則時不完成")
        self.assertIn("找不到成本規則，請先補建", payload["registration_html"])
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"), effective_from=date(2026, 1, 1))
        response = self.client.post(reverse("registration_complete", args=[self.order.pk]))
        self.assertEqual(response["Location"], order_step_url(self.order.pk, "registration"))
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_registration_complete)

    def test_other_confirm_cards_unchanged(self):
        self.complete()
        page = self.client.get(order_step_url(self.order.pk, "delivery")).content.decode()
        self.assertIn('data-lock-confirm="確認完成交車"', page)
        script = (STATIC / "js" / "lock-confirm.js").read_text(encoding="utf-8")
        self.assertIn("window.DMISLockConfirm = {ask, fromElement, rowsFor};", script)
        self.assertIn("document.addEventListener('submit'", script)
        self.assertNotIn("data-lock-auto", script)


class SettledVolumeBonusUnchangedTests(TestCase):
    """已結算台數獎金的訂單維持原本的阻擋，不新增跨期處理（使用者 2026-11-11：台數獎金流程另由 T-148 重新設計）。"""
    order = bonus_fixtures.VolumeBonusConditionsTests.order
    rule = bonus_fixtures.VolumeBonusConditionsTests.rule

    @classmethod
    def setUpTestData(cls):
        bonus_fixtures.VolumeBonusConditionsTests.setUpTestData.__func__(cls)

    def test_settled_order_date_change_still_blocked(self):
        from sales.forms import RegistrationStageForm

        order = self.order(final_plate_number="ABC-1234")
        create_volume_bonus_settlement(self.rule(500, minimum=1), "test", dealer=self.a)
        form = RegistrationStageForm({"registration_date": "2026-10-02", "final_plate_number": "ABC-1234"}, instance=order)
        self.assertFalse(form.is_valid())
        self.assertIn("已結算台數獎金", " ".join(form.non_field_errors()))
        self.assertEqual(SalesOrder.objects.get(pk=order.pk).registration_date, date(2026, 9, 3))
        self.client.force_login(get_user_model().objects.create_superuser("admin", "", "test-pass-123"))
        response = self.client.post(reverse("registration_save", args=[order.pk]),
                                    {"registration_date": "2026-10-02", "final_plate_number": "ABC-1234"},
                                    HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 400, "擋下並顯示原因，不是 500")
        self.assertIn("已結算台數獎金", " ".join(response.json()["errors"]["__all__"]))
        self.assertEqual(SalesOrder.objects.get(pk=order.pk).registration_date, date(2026, 9, 3))
