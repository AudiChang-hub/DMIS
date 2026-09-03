from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from sales.forms import DealerVolumeBonusAdjustmentForm, DealerVolumeBonusSettlementForm, SalesOrderForm
from sales.models import (
    DealerVolumeBonusRule, DealerVolumeBonusTier, OrderChange, OrderDraft,
    OrderOperationsProfile, SalesOrder, SalesSource, SalesSourceBrandPolicy,
    VehicleColor, VehicleModel,
    OrderEvent, PaymentRecord,
)
from sales.services.dealer_commission import (
    apply_order_dealer_commission, create_volume_bonus_settlement,
    preview_volume_bonus, revise_volume_bonus_settlement,
)
from sales.services.order_commission_attribution import change_order_commission_recipient


class OrderCommissionRecipientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("credit-test", password="Test-Only-123")
        cls.a = SalesSource.objects.create(name="A車行", source_type="dealer")
        cls.b = SalesSource.objects.create(name="B車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="測試平台", source_type="platform")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="測試車型", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.policy = SalesSourceBrandPolicy.objects.create(
            source=cls.b, cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS,
            commission_adjustment=300, effective_from=date(2026, 9, 1),
        )
        cls.a_rule = cls.rule(cls.a)
        cls.b_rule = cls.rule(cls.b)

    @classmethod
    def rule(cls, dealer):
        rule = DealerVolumeBonusRule.objects.create(dealer=dealer, brand="SUZUKI", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=3, bonus_per_vehicle=500)
        return rule

    def make_order(self, source=None, recipient=None, **kwargs):
        fields = dict(source_type="dealer", source=source if source is not None else (self.b if kwargs.get("source_type", "dealer") == "dealer" else None), commission_recipient=recipient,
                      order_date=date(2026, 9, 1), owner_type="company", owner_name="測試公司", owner_id_number="83739807",
                      owner_phone="0912345678", owner_address="測試地址", vehicle_model=self.model, color=self.color,
                      vehicle_price=70000, actual_balance=70000, calculated_balance=70000,
                      payment_type="cash", registration_date=date(2026, 9, 2),
                      registration_completed_at=timezone.now(), status=SalesOrder.Status.DELIVERY_PENDING)
        fields.update(kwargs)
        return SalesOrder.objects.create(**fields)

    def post_data(self, **kwargs):
        data = dict(source_type="dealer", source=str(self.b.pk), owner_type="company", owner_name="測試公司",
                    owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", id_verified="on",
                    vehicle_model=str(self.model.pk), color=str(self.color.pk), payment_type="cash", vehicle_price="70000",
                    vehicle_category="new", transaction_type="regular_new", plate_choice="none", delivery_method="store_pickup",
                    deposit_amount="0", plate_insurance_fee="0", installment_opening_fee="0",
                    **{"accessories-TOTAL_FORMS": "0", "accessories-INITIAL_FORMS": "0", "accessories-MIN_NUM_FORMS": "0", "accessories-MAX_NUM_FORMS": "1000",
                       "other_fees-TOTAL_FORMS": "0", "other_fees-INITIAL_FORMS": "0", "other_fees-MIN_NUM_FORMS": "0", "other_fees-MAX_NUM_FORMS": "1000"})
        data.update(kwargs)
        return data

    def test_default_and_single_order_attribution(self):
        self.make_order(self.a)
        self.make_order(self.a)
        credited = self.make_order(self.b, self.a)
        ordinary = self.make_order(self.b)
        self.assertEqual(credited.source, self.b)
        self.assertEqual(credited.effective_commission_recipient, self.a)
        self.assertEqual(ordinary.effective_commission_recipient, self.b)
        self.assertEqual(preview_volume_bonus(self.a_rule)["quantity"], 3)
        self.assertEqual(preview_volume_bonus(self.b_rule)["quantity"], 1)
        self.assertEqual(preview_volume_bonus(self.a_rule)["original_commission_total"], 6300)
        self.assertEqual(preview_volume_bonus(self.a_rule)["total_payable"], 7800)

    def test_form_enable_disable_and_source_switch(self):
        form = SalesOrderForm(data=self.post_data(assign_commission_to_other="True", commission_recipient=self.a.pk))
        self.assertTrue(form.is_valid(), form.errors)
        order = form.save()
        self.assertEqual(order.commission_recipient, self.a)
        order.actual_balance = order.calculated_balance = order.calculate_balance()
        order.save(update_fields=["actual_balance", "calculated_balance"])
        form = SalesOrderForm(data=self.post_data(assign_commission_to_other="False"), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().commission_recipient_id)
        form = SalesOrderForm(data=self.post_data(source_type="store", source="", assign_commission_to_other="True", commission_recipient=self.a.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().commission_recipient_id, self.a.pk)

    def test_store_legacy_form_preserves_attribution(self):
        order = self.make_order(source_type="store", recipient=self.a)
        form = SalesOrderForm(data=self.post_data(source_type="store", source=""), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().commission_recipient_id, self.a.pk)

    def test_completed_store_and_dealer_show_prominent_nojs_entry(self):
        self.client.force_login(self.user)
        for source_type in ("store", "dealer"):
            order = self.make_order(source_type=source_type, status=SalesOrder.Status.COMPLETED)
            page = self.client.get(reverse("order_detail", args=[order.pk]), {"attribution": "1"})
            self.assertContains(page, "data-open-attribution")
            self.assertContains(page, 'class="commission-attribution__editor" open')
            self.assertContains(page, "data-commission-attribution-form")
            if source_type == "store":
                self.assertContains(page, "不指定車行（保留本店來源）")

    def test_completed_store_assign_restore_only_changes_attribution(self):
        self.client.force_login(self.user)
        self.make_order(self.a)
        self.make_order(self.a)
        staff = SalesSource.objects.create(name="本店承辦人", source_type="store")
        for source in (None, staff):
            order = self.make_order(source=source, source_type="store", status=SalesOrder.Status.COMPLETED)
            before = SalesOrder.objects.filter(pk=order.pk).values().get()
            profile_before = OrderOperationsProfile.objects.filter(order=order).values().get()
            payments_before = list(PaymentRecord.objects.filter(order=order).values())
            url = reverse("order_commission_attribution_update", args=[order.pk])
            self.assertEqual(self.client.post(url, self.attribution_data(order, self.a)).status_code, 302)
            order.refresh_from_db()
            after = SalesOrder.objects.filter(pk=order.pk).values().get()
            for field, value in before.items():
                if field not in {"commission_recipient_id", "revision", "updated_at"}:
                    self.assertEqual(after[field], value, field)
            self.assertEqual(OrderOperationsProfile.objects.filter(order=order).values().get(), profile_before)
            self.assertEqual(list(PaymentRecord.objects.filter(order=order).values()), payments_before)
            preview = preview_volume_bonus(self.a_rule)
            self.assertEqual(preview["quantity"], 3)
            self.assertEqual(preview["original_commission_total"], 4000)
            self.assertEqual(preview["expected_amount"], 1500)
            self.assertEqual(order.effective_commission_recipient, self.a)
            self.assertContains(self.client.get(reverse("order_operations", args=[order.pk])), "原來源保留本店")
            self.assertEqual(self.client.post(url, self.attribution_data(order)).status_code, 302)
            order.refresh_from_db()
            self.assertIsNone(order.effective_commission_recipient)
            self.assertEqual(preview_volume_bonus(self.a_rule)["quantity"], 2)
            self.assertEqual(OrderChange.objects.filter(order=order).count(), 2)

    def test_store_settlement_updates_profit_without_new_base_commission(self):
        self.make_order(self.a)
        self.make_order(self.a)
        order = self.make_order(source_type="store", recipient=self.a)
        profile = OrderOperationsProfile.objects.get(order=order)
        profit_before = profile.net_profit
        settlement = create_volume_bonus_settlement(self.a_rule, "test")
        profile.refresh_from_db()
        self.assertEqual(settlement.allocations.get(order=order).original_commission_amount, 0)
        self.assertEqual(profile.dealer_commission_base, 0)
        self.assertEqual(profile.dealer_commission_expense, 500)
        self.assertEqual(profile.net_profit, profit_before - 500)
        revise_volume_bonus_settlement(settlement, "test", 1800, "調整獎金")
        profile.refresh_from_db()
        self.assertEqual(profile.dealer_commission_expense, 600)
        self.assertEqual(profile.net_profit, profit_before - 600)
        order.commission_recipient = None
        with self.assertRaises(ValidationError):
            order.save()
        with self.assertRaises(ValidationError):
            self.make_order(source_type="store", recipient=self.a)

    def test_store_existing_base_and_manual_total_are_preserved(self):
        self.make_order(self.a)
        normal = self.make_order(source_type="store", recipient=self.a)
        manual = self.make_order(source_type="store", recipient=self.a)
        # 歷史本店單若已有明確拆分，不因指定台數覆寫既有金額。
        OrderOperationsProfile.objects.filter(order=normal).update(dealer_commission_base=350, dealer_commission_expense=350)
        OrderOperationsProfile.objects.filter(order=manual).update(dealer_commission_expense=900, manual_financial_fields=["dealer_commission_expense"])
        settlement = create_volume_bonus_settlement(self.a_rule, "test")
        normal_profile = OrderOperationsProfile.objects.get(order=normal)
        manual_profile = OrderOperationsProfile.objects.get(order=manual)
        self.assertEqual(normal_profile.dealer_commission_base, 350)
        self.assertEqual(normal_profile.dealer_commission_expense, 850)
        self.assertEqual(manual_profile.dealer_commission_expense, 900)
        self.assertEqual(settlement.allocations.get(order=normal).original_commission_amount, 350)
        self.assertIsNone(settlement.allocations.get(order=manual).original_commission_amount)

    def test_store_cannot_join_settled_period_through_dedicated_action(self):
        self.client.force_login(self.user)
        for _ in range(3):
            self.make_order(self.a)
        create_volume_bonus_settlement(self.a_rule, "test")
        order = self.make_order(source_type="store", status=SalesOrder.Status.COMPLETED)
        response = self.client.post(reverse("order_commission_attribution_update", args=[order.pk]), self.attribution_data(order, self.a))
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertIsNone(order.commission_recipient_id)

    def test_missing_target_shows_error(self):
        form = SalesOrderForm(data=self.post_data(assign_commission_to_other="True"))
        self.assertFalse(form.is_valid())
        self.assertIn("commission_recipient", form.errors)

    def test_invalid_and_inactive_target(self):
        for recipient in (self.platform,):
            with self.assertRaises(ValidationError):
                self.make_order(recipient=recipient)
            form = SalesOrderForm(data=self.post_data(assign_commission_to_other="True", commission_recipient=recipient.pk))
            self.assertFalse(form.is_valid())
        order = self.make_order(recipient=self.a)
        SalesSource.objects.filter(pk=self.a.pk).update(active=False)
        with self.assertRaises(ValidationError):
            self.make_order(recipient=SalesSource.objects.get(pk=self.a.pk))
        form = SalesOrderForm(data=self.post_data(assign_commission_to_other="True", commission_recipient=self.a.pk), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

    def test_same_dealer_uses_default(self):
        order = self.make_order(self.a, self.a)
        self.assertIsNone(order.commission_recipient_id)

    def test_legacy_form_preserves_saved_override(self):
        order = self.make_order(recipient=self.a)
        form = SalesOrderForm(data=self.post_data(), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().commission_recipient_id, self.a.pk)

    def test_nojs_fallback(self):
        form = SalesOrderForm(data=self.post_data(commission_recipient_nojs="1", assign_commission_to_other="False", commission_recipient=self.a.pk))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().commission_recipient_id, self.a.pk)

    def test_settlement_preserves_original_commission_and_locks_recipient(self):
        orders = [self.make_order(self.a), self.make_order(self.a), self.make_order(self.b, self.a)]
        for order in orders:
            apply_order_dealer_commission(order, lock=True)
        VehicleModel.objects.filter(pk=self.model.pk).update(base_dealer_commission=9999)
        settlement = create_volume_bonus_settlement(self.a_rule, "test")
        self.assertEqual(settlement.qualified_quantity, 3)
        self.assertEqual(sum(a.original_commission_amount for a in settlement.allocations.all()), 6300)
        self.assertEqual(preview_volume_bonus(self.a_rule)["total_payable"], 7800)
        credited = orders[-1]
        profile = OrderOperationsProfile.objects.get(order=credited)
        self.assertEqual(profile.dealer_commission_base, 2000)
        self.assertEqual(profile.dealer_commission_adjustment, 300)
        self.assertEqual(profile.dealer_commission_expense, 2800)
        credited.commission_recipient = None
        with self.assertRaises(ValidationError):
            credited.save()
        credited.refresh_from_db()
        credited.source = self.a
        with self.assertRaises(ValidationError):
            credited.save()
        revise_volume_bonus_settlement(settlement, "test", Decimal(1800), "調整")
        self.assertEqual(sum(a.original_commission_amount for a in settlement.allocations.all()), 6300)
        with self.assertRaises(ValidationError):
            self.make_order(self.a)
        self.assertEqual(preview_volume_bonus(self.a_rule)["quantity"], 3)
        with self.assertRaises(ValueError):
            create_volume_bonus_settlement(self.a_rule, "test")

    def test_excluded_orders_and_next_month(self):
        self.make_order(recipient=self.a, status=SalesOrder.Status.CANCELLED)
        self.make_order(recipient=self.a, registration_completed_at=None)
        self.make_order(recipient=self.a, registration_date=date(2026, 10, 1))
        self.assertEqual(preview_volume_bonus(self.a_rule)["quantity"], 0)
        later = self.make_order(self.b, registration_date=date(2026, 10, 2))
        self.assertEqual(later.effective_commission_recipient, self.b)

    def test_draft_restores_and_create_saves_attribution(self):
        self.client.force_login(self.user)
        data = self.post_data(assign_commission_to_other="True", commission_recipient=str(self.a.pk))
        response = self.client.post(reverse("draft_save"), data)
        self.assertEqual(response.status_code, 200)
        draft = OrderDraft.objects.get(pk=response.json()["id"])
        page = self.client.get(reverse("order_create"), {"draft": draft.pk})
        self.assertEqual(page.context["form"]["commission_recipient"].value(), str(self.a.pk))
        self.assertTrue(page.context["form"]["assign_commission_to_other"].value())
        data["_draft_id"] = str(draft.pk)
        response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        order = SalesOrder.objects.get()
        self.assertEqual(order.source, self.b)
        self.assertEqual(order.commission_recipient, self.a)
        self.assertFalse(OrderDraft.objects.filter(pk=draft.pk).exists())

    def test_edit_records_names_and_reason(self):
        order = self.make_order(registration_completed_at=None)
        self.client.force_login(self.user)
        self.client.get(reverse("order_edit", args=[order.pk]))
        order.refresh_from_db()
        response = self.client.post(reverse("order_edit", args=[order.pk]), self.post_data(
            assign_commission_to_other="True", commission_recipient=self.a.pk,
            change_reason="此台算給A", _order_revision=str(order.revision)))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        order.refresh_from_db()
        self.assertEqual(order.commission_recipient, self.a)
        change = OrderChange.objects.get(order=order)
        self.assertEqual(change.changes["台數與傭金歸屬車行"], {"before": "B車行", "after": "A車行"})

    def test_ui_detail_help_and_export_show_recipient(self):
        order = self.make_order(recipient=self.a)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("order_create")), "這台算給其他車行")
        for form in (DealerVolumeBonusAdjustmentForm(), DealerVolumeBonusSettlementForm()):
            for field in form.fields.values():
                self.assertEqual(field.widget.attrs.get("class"), "form-control")
        preview_page = self.client.get(reverse("dealer_volume_bonus_settle", args=[self.a_rule.pk]))
        self.assertContains(preview_page, "bonus-settlement-layout")
        self.assertContains(preview_page, "dealer-volume-bonus.css")
        self.assertContains(self.client.get(reverse("order_detail", args=[order.pk])), "台數與傭金歸屬")
        self.assertContains(self.client.get(reverse("order_operations", args=[order.pk])), "傭金收款車行")
        response = self.client.get(reverse("operations_report_export"))
        sheet = load_workbook(BytesIO(response.content)).active
        rows = list(sheet.values)
        index = rows[0].index("台數與傭金歸屬車行")
        self.assertEqual(rows[1][index], "A車行")

    def test_credited_dealer_cannot_be_deleted(self):
        from sales.services.sales_source_deletion import sales_source_delete_blockers
        self.make_order(recipient=self.a)
        blockers = sales_source_delete_blockers(self.a)
        self.assertIn("credited_orders", [item.key for item in blockers])

    def test_settled_form_keeps_recipient_even_if_posted_value_is_forged(self):
        self.make_order(self.a)
        self.make_order(self.a)
        order = self.make_order(self.b, self.a)
        create_volume_bonus_settlement(self.a_rule, "test")
        form = SalesOrderForm(data=self.post_data(assign_commission_to_other="False", commission_recipient=self.b.pk), instance=order)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.commission_attribution_locked)
        self.assertEqual(form.save().commission_recipient_id, self.a.pk)

    def test_manual_commission_and_legacy_settlement_snapshot(self):
        order = self.make_order(self.b, self.a)
        profile = apply_order_dealer_commission(order, lock=True)
        profile.manual_financial_fields = ["dealer_commission_expense"]
        profile.dealer_commission_expense = 2600
        profile.save()
        self.make_order(self.a)
        self.make_order(self.a)
        self.assertIsNone(preview_volume_bonus(self.a_rule)["total_payable"])
        settlement = create_volume_bonus_settlement(self.a_rule, "test")
        self.assertIsNone(settlement.allocations.get(order=order).original_commission_amount)
        profile.refresh_from_db()
        self.assertEqual(profile.dealer_commission_expense, 2600)
        settlement.allocations.update(original_commission_amount=None)
        self.assertIsNone(preview_volume_bonus(self.a_rule)["original_commission_total"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dealer_volume_bonus_revise", args=[settlement.pk]))
        self.assertContains(response, "原傭金未留快照")

    def attribution_data(self, order, recipient=None, **overrides):
        data = {
            "attribution-commission_recipient": str(recipient.pk) if recipient else "",
            "attribution-order_revision": str(order.revision),
            "attribution-reason": "車行通知這台另計歸屬",
        }
        data.update(overrides)
        return data

    def test_dedicated_action_supports_saved_and_delivered_without_other_changes(self):
        self.client.force_login(self.user)
        for status in (SalesOrder.Status.DELIVERY_PENDING, SalesOrder.Status.DELIVERED_DOCS_PENDING, SalesOrder.Status.COMPLETED):
            with self.subTest(status=status):
                order = self.make_order(status=status)
                apply_order_dealer_commission(order, lock=True)
                # 歷史資料未留交付時間、證件不完整，也不能因改歸屬而補寫／卡住。
                SalesOrder.objects.filter(pk=order.pk).update(delivered_at=None, owner_id_number="歷史未填")
                before = SalesOrder.objects.filter(pk=order.pk).values().get()
                profile_before = OrderOperationsProfile.objects.filter(order=order).values().get()
                payments_before = list(PaymentRecord.objects.filter(order=order).values())
                response = self.client.post(reverse("order_commission_attribution_update", args=[order.pk]),
                    self.attribution_data(order, self.a, source=self.a.pk, vehicle_price="1", status="cancelled", delivered_at="2020-01-01"))
                self.assertEqual(response.status_code, 302)
                after = SalesOrder.objects.filter(pk=order.pk).values().get()
                for field, value in before.items():
                    if field not in {"commission_recipient_id", "revision", "updated_at"}:
                        self.assertEqual(after[field], value, field)
                self.assertEqual(after["commission_recipient_id"], self.a.pk)
                self.assertEqual(after["revision"], before["revision"] + 1)
                self.assertEqual(OrderOperationsProfile.objects.filter(order=order).values().get(), profile_before)
                self.assertEqual(list(PaymentRecord.objects.filter(order=order).values()), payments_before)
                change = OrderChange.objects.get(order=order)
                self.assertEqual(change.changes, {"台數與傭金歸屬車行": {"before": "B車行", "after": "A車行"}})
                self.assertTrue(change.actor_name)
                self.assertEqual(OrderEvent.objects.filter(order=order, event_type="commission_attribution_updated").count(), 1)
                if status != SalesOrder.Status.DELIVERY_PENDING:
                    self.assertRedirects(self.client.get(reverse("order_edit", args=[order.pk])), reverse("order_detail", args=[order.pk]))
                    page = self.client.get(reverse("order_detail", args=[order.pk]))
                    self.assertContains(page, "調整台數與傭金歸屬")
                    self.assertNotContains(page, f'href="{reverse("order_edit", args=[order.pk])}"')

    def test_dedicated_action_restores_original_and_unchanged_is_noop(self):
        order = self.make_order(recipient=self.a, status=SalesOrder.Status.COMPLETED)
        self.client.force_login(self.user)
        url = reverse("order_commission_attribution_update", args=[order.pk])
        self.assertEqual(self.client.post(url, self.attribution_data(order)).status_code, 302)
        order.refresh_from_db()
        self.assertIsNone(order.commission_recipient_id)
        revision = order.revision
        self.assertEqual(self.client.post(url, self.attribution_data(order)).status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.revision, revision)
        self.assertEqual(OrderChange.objects.filter(order=order).count(), 1)

    def test_dedicated_action_checks_reason_target_and_revision(self):
        order = self.make_order()
        self.client.force_login(self.user)
        url = reverse("order_commission_attribution_update", args=[order.pk])
        for overrides in ({"attribution-reason": "  "}, {"attribution-order_revision": "invalid"},
                          {"attribution-order_revision": str(order.revision + 1)},
                          {"attribution-commission_recipient": self.platform.pk},
                          {"attribution-commission_recipient": "99999999"}):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.client.post(url, self.attribution_data(order, self.a, **overrides)).status_code, 400)
        data = self.attribution_data(order, self.a)
        del data["attribution-commission_recipient"]
        self.assertEqual(self.client.post(url, data).status_code, 400)
        SalesSource.objects.filter(pk=self.a.pk).update(active=False)
        self.assertEqual(self.client.post(url, self.attribution_data(order, self.a)).status_code, 400)
        order.refresh_from_db()
        self.assertIsNone(order.commission_recipient_id)
        self.assertFalse(OrderChange.objects.filter(order=order).exists())

    def test_dedicated_action_blocks_cancelled_nondealer_and_settled(self):
        self.client.force_login(self.user)
        cancelled = self.make_order(status=SalesOrder.Status.CANCELLED)
        platform = self.make_order(source=self.platform, source_type="platform")
        for order in (cancelled, platform):
            response = self.client.post(reverse("order_commission_attribution_update", args=[order.pk]), self.attribution_data(order, self.a))
            self.assertEqual(response.status_code, 302)
            self.assertFalse(OrderChange.objects.filter(order=order).exists())
        self.make_order(self.a)
        self.make_order(self.a)
        settled = self.make_order(self.b, self.a, status=SalesOrder.Status.COMPLETED)
        create_volume_bonus_settlement(self.a_rule, "test")
        url = reverse("order_commission_attribution_update", args=[settled.pk])
        self.assertEqual(self.client.post(url, self.attribution_data(settled)).status_code, 302)
        settled.refresh_from_db()
        self.assertEqual(settled.commission_recipient_id, self.a.pk)
        self.assertNotContains(self.client.get(reverse("order_detail", args=[settled.pk])), "data-commission-attribution-form")

    def test_dedicated_action_blocks_other_editor_and_replayed_post(self):
        order = self.make_order()
        self.client.force_login(self.user)
        url = reverse("order_commission_attribution_update", args=[order.pk])
        data = self.attribution_data(order, self.a)
        SalesOrder.objects.filter(pk=order.pk).update(editing_session="another-session", editing_at=timezone.now())
        self.assertEqual(self.client.post(url, data).status_code, 400)
        SalesOrder.objects.filter(pk=order.pk).update(editing_at=timezone.now() - timezone.timedelta(minutes=3))
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 400)
        self.assertEqual(OrderChange.objects.filter(order=order).count(), 1)

    def test_dedicated_action_requires_login_post_and_csrf(self):
        order = self.make_order()
        url = reverse("order_commission_attribution_update", args=[order.pk])
        self.assertEqual(self.client.post(url, self.attribution_data(order, self.a)).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, self.attribution_data(order, self.a)).status_code, 403)
        client.get(reverse("order_detail", args=[order.pk]))
        csrf = client.cookies["csrftoken"].value
        self.assertEqual(client.post(url, self.attribution_data(order, self.a), HTTP_X_CSRFTOKEN=csrf).status_code, 302)

    def test_dedicated_action_changes_original_period_counts_not_financials(self):
        self.make_order(self.a)
        self.make_order(self.a)
        order = self.make_order(status=SalesOrder.Status.COMPLETED)
        self.client.force_login(self.user)
        self.client.post(reverse("order_commission_attribution_update", args=[order.pk]), self.attribution_data(order, self.a))
        self.assertEqual(preview_volume_bonus(self.a_rule)["quantity"], 3)
        self.assertEqual(preview_volume_bonus(self.a_rule)["total_payable"], 7800)
        self.assertEqual(preview_volume_bonus(self.b_rule)["quantity"], 0)
        self.assertFalse(order.dealer_volume_bonus_allocations.exists())

    def test_cannot_assign_new_order_into_already_settled_target_period(self):
        for _ in range(3):
            self.make_order(self.a)
        create_volume_bonus_settlement(self.a_rule, "test")
        order = self.make_order(status=SalesOrder.Status.COMPLETED)
        self.client.force_login(self.user)
        response = self.client.post(reverse("order_commission_attribution_update", args=[order.pk]), self.attribution_data(order, self.a))
        self.assertContains(response, "不能直接加入已結算清單", status_code=400)
        order.refresh_from_db()
        self.assertIsNone(order.commission_recipient_id)

    def test_audit_failure_rolls_back_attribution(self):
        order = self.make_order(status=SalesOrder.Status.COMPLETED)
        revision = order.revision
        with patch("sales.services.order_commission_attribution.OrderEvent.objects.create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                change_order_commission_recipient(order_id=order.pk, recipient_id=self.a.pk, reason="歸給 A",
                    expected_revision=order.revision, actor_name="test", editing_session=None)
        order.refresh_from_db()
        self.assertIsNone(order.commission_recipient_id)
        self.assertEqual(order.revision, revision)
        self.assertFalse(OrderChange.objects.filter(order=order).exists())
