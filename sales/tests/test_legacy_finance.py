from datetime import date
from decimal import Decimal
from io import StringIO
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase

from sales.models import LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderChange, OrderOperationsProfile, SalesOrder, SalesSource, VehicleColor, VehicleModel
from sales.services.legacy_finance import BASE_MAPPING, FINANCIAL_FIELDS, import_financials, reconcile_source
from sales.services.operations_sync import sync_order_operations


class LegacyFinanceMappingTests(SimpleTestCase):
    def test_missing_disbursement_and_fractional_fee(self):
        raw = {"收款價": 74980, "成本": 71500, "信用卡手續費支出": "426.064", "其他收入": 4257, "單筆淨利": "7310.936"}
        audit, values = reconcile_source(raw)
        self.assertEqual(audit["status"], "matched")
        self.assertEqual(OrderOperationsProfile(**values).net_profit, Decimal("7310.936"))

    def test_original_formula_variants(self):
        for reference, expected, bonus in (("900", "L:V", "100"), ("1000", "L:S", "0")):
            with self.subTest(expected):
                audit, values = reconcile_source({"收款價": 70000, "成本": 69000, "首賣獎金支出": 100, "單筆淨利": reference})
                self.assertEqual(audit["expense_scope"], expected)
                self.assertEqual(values["first_sale_bonus_expense"], Decimal(bonus))

    def test_no_profit_plug_or_invalid_zero(self):
        for raw, status in (({"收款價": 70000, "成本": 69000, "單筆淨利": 5000}, "mismatch"),
                            ({"收款價": "#VALUE!", "成本": 0, "單筆淨利": 0}, "invalid"),
                            ({"成本": 1, "單筆淨利": -1}, "missing"),
                            ({"收款價": "NaN", "成本": 1, "單筆淨利": -1}, "invalid")):
            audit, values = reconcile_source(raw)
            self.assertEqual(audit["status"], status)
            self.assertFalse(values)

    def test_zero_and_real_negative_are_valid(self):
        for reference in (0, -500):
            audit, values = reconcile_source({"收款價": 0, "成本": -reference, "單筆淨利": reference})
            self.assertEqual(audit["status"], "matched")
            self.assertEqual(OrderOperationsProfile(**values).net_profit, reference)


class LegacyFinanceRepairTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dealer = SalesSource.objects.create(name="財務核對測試", source_type="dealer")
        cls.vehicle_model = VehicleModel.objects.create(brand="SYM", name="核對機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.vehicle_model, name="白")

    def setUp(self):
        self.order = SalesOrder.objects.create(source_type="dealer", source=self.dealer, vehicle_model=self.vehicle_model,
            color=self.color, owner_name="合成資料", owner_type="local", owner_id_number="A123456789", owner_phone="0912345678",
            owner_address="測試", vehicle_price=0, actual_balance=0, payment_type="cash", delivery_method="store_pickup",
            order_date=date(2020, 1, 1), registration_date=date(2020, 1, 2), status=SalesOrder.Status.COMPLETED)
        self.raw = {"收款價": 70000, "成本": 60000, "信用卡手續費支出": "426.064", "單筆淨利": "9573.936"}
        batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="synthetic.xlsx", file_size=0)
        row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=4, raw_data=self.raw, mapped_data={})
        self.snapshot = LegacySalesSnapshot.objects.create(order=self.order, import_row=row, raw_financials=self.raw)
        self.profile = self.order.operations
        for field in FINANCIAL_FIELDS:
            setattr(self.profile, field, Decimal(str(self.raw.get(BASE_MAPPING.get(field), 0))))
        self.profile.save()

    def preview(self, **kwargs):
        out = StringIO()
        call_command("reconcile_legacy_finance", stdout=out, **kwargs)
        return json.loads(out.getvalue())

    def test_repair_is_audited_idempotent_and_preserves_payment_and_snapshots(self):
        payments = list(self.order.payment_records.values())
        price_snapshot = self.order.installment_plan_snapshot
        preview = self.preview()
        self.assertEqual(preview["counts"], {"ready": 1})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.actual_disbursement, 0)
        self.preview(apply=True, expected_digest=preview["digest"])
        self.profile.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.profile.net_profit, Decimal("9573.936"))
        self.assertEqual(list(self.order.payment_records.values()), payments)
        self.assertEqual(self.order.installment_plan_snapshot, price_snapshot)
        self.assertEqual(self.order.order_date, date(2020, 1, 1))
        self.assertEqual(self.order.changes.count(), 1)
        self.assertEqual(self.preview()["counts"], {"already_reconciled": 1})
        sync_order_operations(self.order.pk)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.net_profit, Decimal("9573.936"))

    def test_manual_zero_and_changed_fields_preserved(self):
        self.profile.manual_financial_fields = ["actual_disbursement"]
        self.profile.save()
        self.assertEqual(self.preview()["counts"], {"preserved_changes": 1})
        self.profile.manual_financial_fields = []
        self.profile.other_income = 10
        self.profile.save()
        self.assertEqual(self.preview()["counts"], {"preserved_changes": 1})

    def test_stale_preview_refused_and_transaction_rolls_back(self):
        preview = self.preview()
        self.profile.other_income = 1
        self.profile.save()
        with self.assertRaises(CommandError):
            self.preview(apply=True, expected_digest=preview["digest"])
        self.profile.other_income = 0
        self.profile.save()
        preview = self.preview()
        with patch.object(OrderChange.objects, "create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.preview(apply=True, expected_digest=preview["digest"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.actual_disbursement, 0)

    def test_formation_date_is_first_save_date_not_pricing_date(self):
        from django.utils import timezone
        self.assertEqual(self.order.established_on, timezone.localdate())
        original = self.order.established_on
        with patch("sales.models.timezone.localdate", return_value=date(2030, 1, 1)):
            self.order.note = "後續修改"
            self.order.save(update_fields=["note"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.established_on, original)

    def test_missing_imported_date_is_only_filled_when_registration_is_known(self):
        SalesOrder.objects.filter(pk=self.order.pk).update(established_on=None, registration_date=None)
        self.order.refresh_from_db()
        self.order.save(update_fields=["note"])
        self.assertIsNone(self.order.established_on)
        self.order.registration_date = date(2021, 4, 3)
        self.order.save(update_fields=["registration_date"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.established_on, date(2021, 4, 3))

    def test_date_backfill_does_not_reprice_and_keeps_missing_dates_empty(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        backfill = import_module("sales.migrations.0131_backfill_established_on").backfill
        schema = SimpleNamespace(connection=connection)
        before = self.profile.net_profit
        backfill(apps, schema)
        self.order.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.order.established_on, date(2020, 1, 2))
        self.assertEqual(self.order.order_date, date(2020, 1, 1))
        self.assertEqual(self.profile.net_profit, before)
        SalesOrder.objects.filter(pk=self.order.pk).update(registration_date=None)
        backfill(apps, schema)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.established_on)

    def test_manual_review_requires_reason_and_preserves_payment_confirmation(self):
        from django import forms
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from sales.forms import OrderOperationsForm
        user = get_user_model().objects.create_superuser("admin", password="test-only-password")
        self.client.force_login(user)
        self.profile.legacy_finance_reconciliation = {"status": "preserved_changes", "reason": "已有修改"}
        self.profile.save()
        form = OrderOperationsForm(instance=self.profile, prefix="operations")
        payload = {}
        for field in form:
            if isinstance(field.field, forms.FileField):
                continue
            if isinstance(field.field, forms.BooleanField):
                if field.value():
                    payload[field.html_name] = "on"
            else:
                payload[field.html_name] = "" if field.value() is None else str(field.value())
        payload.update({"operations-confirm_legacy_finance": "on", "payments-TOTAL_FORMS": "0", "payments-INITIAL_FORMS": "0"})
        response = self.client.post(reverse("order_operations", args=[self.order.pk]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("change_reason", response.context["form"].errors)
        before = list(self.order.payment_records.values())
        payload["operations-change_reason"] = "已逐項核對原始憑證"
        response = self.client.post(reverse("order_operations", args=[self.order.pk]), payload)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legacy_finance_reconciliation["status"], "reviewed")
        self.assertTrue(self.profile.profit_is_ready)
        self.assertEqual(list(self.order.payment_records.values()), before)
        self.assertEqual(self.preview()["counts"], {"already_reconciled": 1})
