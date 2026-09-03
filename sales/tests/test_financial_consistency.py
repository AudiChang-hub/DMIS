from datetime import date
from decimal import Decimal
from unittest.mock import patch
from threading import Event, Thread

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from sales.forms import OrderOperationsForm, PaymentRecordForm, SalesOrderForm
from sales.models import (
    DealerVolumeBonusRule, DealerVolumeBonusTier, OrderOperationsProfile, PaymentRecord,
    SalesOrder, SalesSource, VehicleColor, VehicleModel, VehicleSettlementCostRule,
)
from sales.services.dealer_commission import (
    apply_order_dealer_commission, create_volume_bonus_settlement,
    revise_volume_bonus_settlement,
)
from sales.services.financial_audit import audit_financial_consistency
from sales.services.financial_refresh import refresh_unlocked_financials
from sales.services.operations_sync import sync_order_operations


class FinancialConsistencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("financial-audit", password="test-pass-123")
        cls.dealer = SalesSource.objects.create(name="盤點車行", source_type="dealer")
        cls.other = SalesSource.objects.create(name="其他車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="盤點平台", source_type="platform")
        cls.model = VehicleModel.objects.create(brand="SYM", name="盤點車型", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def order(self, **overrides):
        data = dict(source_type="dealer", source=self.dealer, order_date=date(2026, 9, 1),
                    owner_type="company", owner_name="測試公司", owner_id_number="83739807",
                    owner_phone="0912345678", owner_address="測試地址", vehicle_model=self.model, color=self.color,
                    vehicle_price=70000, actual_balance=70000, calculated_balance=70000,
                    payment_type="cash", registration_date=date(2026, 9, 2))
        data.update(overrides)
        return SalesOrder.objects.create(**data)

    def rule(self):
        rule = DealerVolumeBonusRule.objects.create(dealer=self.dealer, brand="SYM",
                    starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30))
        DealerVolumeBonusTier.objects.create(rule=rule, minimum_quantity=1, bonus_per_vehicle=500)
        return rule

    def profile(self, order):
        return OrderOperationsProfile.objects.get(order=order)

    def test_payment_confirmation_from_any_entry_updates_profit_and_reversal(self):
        order = self.order(source_type="platform", source=self.platform)
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount = 65000
        payment.confirmed = True
        payment.save()
        self.assertEqual(self.profile(order).actual_disbursement, 65000)
        self.assertEqual(self.profile(order).net_profit, 65000)
        payment.received_amount = 66000
        payment.save()
        self.assertEqual(self.profile(order).net_profit, 66000)
        payment.confirmed = False
        payment.save()
        self.assertEqual(self.profile(order).net_profit, 0)
        self.assertEqual(self.profile(order).payment_disbursement_snapshot, {})

    def test_payment_reversal_restores_manual_value(self):
        order = self.order(source_type="platform", source=self.platform)
        profile = self.profile(order)
        profile.actual_disbursement = 63000
        profile.manual_financial_fields = ["actual_disbursement"]
        profile.save()
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount = 65000
        payment.confirmed = True
        payment.save()
        payment.delete()
        self.assertEqual(self.profile(order).actual_disbursement, 63000)
        self.assertIn("actual_disbursement", self.profile(order).manual_financial_fields)

    def test_read_sync_does_not_adopt_old_confirmed_manual_disbursement(self):
        order = self.order(source_type="platform", source=self.platform)
        OrderOperationsProfile.objects.filter(order=order).update(actual_disbursement=61234)
        order.payment_records.filter(system_key="balance").update(received_amount=62000, confirmed=True)
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).actual_disbursement, 61234)
        self.assertEqual(self.profile(order).payment_disbursement_snapshot, {})

    def test_confirmed_disbursement_is_readonly_in_operations_form(self):
        order = self.order(source_type="platform", source=self.platform)
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount, payment.confirmed = 65000, True
        payment.save()
        self.assertTrue(OrderOperationsForm(instance=self.profile(order)).fields["actual_disbursement"].disabled)

    def test_card_fees_sync_on_create_update_delete(self):
        order = self.order()
        payment = PaymentRecord.objects.create(order=order, item_name="刷卡", card_fee_charged=100, bank_card_fee=70)
        self.assertEqual(self.profile(order).card_fee_income, 100)
        self.assertEqual(self.profile(order).card_fee_expense, 70)
        payment.bank_card_fee = 90
        payment.save()
        self.assertEqual(self.profile(order).card_fee_expense, 90)
        payment.delete()
        self.assertEqual(self.profile(order).card_fee_income, 0)
        self.assertEqual(self.profile(order).card_fee_expense, 0)

    def test_one_overpayment_cannot_cover_another_unpaid_record(self):
        order = self.order()
        balance = order.payment_records.get(system_key="balance")
        balance.received_amount, balance.confirmed = 80000, True
        balance.save()
        PaymentRecord.objects.create(order=order, item_name="另筆", expected_amount=1000)
        self.assertFalse(self.profile(order).payment_confirmed)

    def test_receivable_change_preserves_receipt_and_updates_shortage(self):
        order = self.order()
        payment = order.payment_records.get(system_key="balance")
        payment.received_amount, payment.confirmed = 70000, True
        payment.save()
        order.vehicle_price = order.actual_balance = 80000
        order.save()
        payment.refresh_from_db()
        self.assertEqual(payment.expected_amount, 80000)
        self.assertEqual(payment.received_amount, 70000)
        self.assertEqual(payment.outstanding_amount, 10000)
        self.assertFalse(self.profile(order).payment_confirmed)

    def test_manual_receivable_remains_protected(self):
        order = self.order()
        payment = order.payment_records.get(system_key="balance")
        payment.expected_amount, payment.expected_amount_overridden = 60000, True
        payment.save()
        order.vehicle_price = order.actual_balance = 80000
        order.save()
        payment.refresh_from_db()
        self.assertEqual(payment.expected_amount, 60000)

    def test_payment_and_financial_sync_rollback_together(self):
        order = self.order()
        with patch("sales.signals.sync_payment_financials", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                PaymentRecord.objects.create(order=order, item_name="不可殘留", received_amount=100)
        self.assertFalse(order.payment_records.filter(item_name="不可殘留").exists())

    def test_rate_refresh_preserves_locked_commission(self):
        order = self.order()
        apply_order_dealer_commission(order, lock=True)
        self.model.base_dealer_commission = 9999
        self.model.save()
        apply_order_dealer_commission(order)
        self.assertEqual(self.profile(order).dealer_commission_expense, 2000)

    def test_pending_cost_refreshes_but_registered_snapshot_does_not(self):
        pending = self.order()
        registered = self.order(registration_completed_at=timezone.now())
        rule = VehicleSettlementCostRule.objects.create(vehicle_model=self.model, effective_from=date(2026, 9, 1), amount=50000)
        self.assertEqual(self.profile(pending).vehicle_cost, 50000)
        self.assertEqual(self.profile(registered).vehicle_cost, 0)
        rule.amount = 51000
        rule.save()
        self.assertEqual(self.profile(pending).vehicle_cost, 51000)

    def test_operations_form_does_not_expose_snapshot_metadata(self):
        form = OrderOperationsForm(instance=self.profile(self.order()))
        for name in ("dealer_commission_base", "dealer_commission_adjustment", "dealer_commission_locked_at", "payment_disbursement_snapshot"):
            self.assertNotIn(name, form.fields)

    def test_settled_order_cannot_change_model_period_or_registration(self):
        rule = self.rule()
        order = self.order(registration_completed_at=timezone.now())
        create_volume_bonus_settlement(rule, "test")
        for field, value in (("registration_date", date(2026, 9, 5)), ("registration_completed_at", None), ("status", "cancelled")):
            order.refresh_from_db()
            setattr(order, field, value)
            with self.assertRaises(ValidationError):
                order.save()

    def test_settled_rule_cannot_rewrite_payee(self):
        rule = self.rule()
        self.order(registration_completed_at=timezone.now())
        create_volume_bonus_settlement(rule, "test")
        rule.dealer = self.other
        with self.assertRaises(ValidationError):
            rule.save()

    def test_bonus_rejects_negative_fraction_and_nan_without_partial_writes(self):
        rule = self.rule()
        order = self.order(registration_completed_at=timezone.now())
        for amount in (Decimal("-1"), Decimal("1.5"), Decimal("NaN")):
            with self.assertRaises(ValueError):
                create_volume_bonus_settlement(rule, "test", amount, "測試")
            self.assertFalse(order.dealer_volume_bonus_allocations.exists())
        settlement = create_volume_bonus_settlement(rule, "test")
        for amount in (Decimal("-1"), Decimal("1.5")):
            with self.assertRaises(ValueError):
                revise_volume_bonus_settlement(settlement, "test", amount, "測試")
        settlement.refresh_from_db()
        self.assertEqual(settlement.actual_amount, 500)

    def test_audit_reports_differences_without_writes(self):
        order = self.order()
        OrderOperationsProfile.objects.filter(order=order).update(card_fee_income=123)
        before = self.profile(order).updated_at
        audit = audit_financial_consistency()
        self.assertTrue(audit["read_only"])
        self.assertIn("card_fee_mismatch", audit["finding_counts"])
        self.assertEqual(self.profile(order).card_fee_income, 123)
        self.assertEqual(self.profile(order).updated_at, before)

    def test_reconciliation_confirm_and_revoke_updates_profit(self):
        order = self.order(source_type="platform", source=self.platform)
        payment = order.payment_records.get(system_key="balance")
        self.client.force_login(self.user)
        data = dict(expected_amount="70000", received_amount="68000", received_on="2026-09-03", confirmed="on")
        self.client.post(reverse("reconciliation_update", args=[payment.pk]), data)
        self.assertEqual(self.profile(order).actual_disbursement, 68000)
        data.pop("confirmed")
        self.client.post(reverse("reconciliation_update", args=[payment.pk]), data)
        self.assertEqual(self.profile(order).actual_disbursement, 0)

    def test_missing_or_stale_financial_revision_is_rejected(self):
        order = self.order()
        profile = self.profile(order)
        for value in ("", "stale"):
            form = OrderOperationsForm(data={"financial_revision": value}, instance=profile)
            self.assertFalse(form.is_valid())
            self.assertIn("重新載入", str(form.non_field_errors()))

    def test_operations_actual_browser_payload_skips_blank_payment_row(self):
        order = self.order()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_operations", args=[order.pk]))
        form, formset = page.context["form"], page.context["payment_formset"]
        payload = {}
        for field in form:
            if not field.field.disabled:
                value = field.value()
                payload[field.html_name] = "on" if value is True else "" if value is False or value is None else str(value)
        for field in formset.management_form:
            payload[field.html_name] = field.value()
        for row in formset:
            for field in row:
                if not field.field.disabled:
                    value = field.value()
                    payload[field.html_name] = "on" if value is True else "" if value is False or value is None else str(value)
        payload["operations-actual_disbursement"] = "71000"
        response = self.client.post(reverse("order_operations", args=[order.pk]), payload)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.assertEqual(self.profile(order).actual_disbursement, 71000)
        self.assertEqual(order.payment_records.count(), 2)
        payload["operations-actual_disbursement"] = "72000"
        response = self.client.post(reverse("order_operations", args=[order.pk]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "重新載入")
        self.assertEqual(self.profile(order).actual_disbursement, 71000)
        self.assertEqual(response.context["profile"].actual_disbursement, 71000)


class FinancialPostgresConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update_nowait")
    def test_order_save_rejects_in_progress_bonus_settlement_without_deadlock(self):
        FinancialConsistencyTests.setUpTestData.__func__(type(self))
        order = FinancialConsistencyTests.order(self)
        rule = FinancialConsistencyTests.rule(self)
        acquired, release = Event(), Event()
        errors = []

        def lock_rule():
            close_old_connections()
            try:
                with transaction.atomic():
                    DealerVolumeBonusRule.objects.select_for_update().get(pk=rule.pk)
                    acquired.set()
                    release.wait(10)
            except Exception as exc:
                errors.append(exc)
                acquired.set()
            finally:
                connection.close()

        worker = Thread(target=lock_rule, daemon=True)
        worker.start()
        try:
            self.assertTrue(acquired.wait(5))
            self.assertEqual(errors, [])
            order.registration_completed_at = timezone.now()
            with self.assertRaisesMessage(ValidationError, "正在結算"):
                order.save()
        finally:
            release.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        order.refresh_from_db()
        self.assertIsNone(order.registration_completed_at)
