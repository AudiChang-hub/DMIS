from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    DealerVolumeBonusAllocation, DealerVolumeBonusRule, DealerVolumeBonusSettlement,
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderChange, OrderEvent,
    OrderOperationsProfile, PaymentRecord, RegistrationDocument, SalesOrder, SalesSource,
    VehicleInventory, VehicleSettlementCostRule,
)
from sales.services.historical_date_change import date_change_preview, date_preview_token, change_historical_date, EVENT
from sales.services.legacy_import import revalidate_import_batch
from sales.tests.test_historical_replacement import ReplacementFixture


class DateChangeFixture(ReplacementFixture):
    def setUp(self):
        super().setUp()
        self.row.source_row = 1754
        self.row.mapped_data.update(owner_name=self.order.owner_name, owner_id_number=self.order.owner_id_number,
            registration_date=str(timezone.localdate() + timedelta(days=5)))
        self.row.save()
        self.url = reverse("historical_date_change", args=[self.batch.pk, self.row.pk, self.order.pk])

    def data(self):
        self.row.refresh_from_db()
        self.order.refresh_from_db()
        preview = date_change_preview(self.row, self.order)
        return dict(preview_token=date_preview_token(preview, self.admin), date_kind="planned",
            same_buyer_confirmed=True, facts_confirmed=True, impact_confirmed=True, reason="同一買家改預計領牌日期")

    def execute(self, data=None, user=None):
        return change_historical_date(row_id=self.row.pk, order_id=self.order.pk, user=user or self.admin,
            data=self.data() if data is None else data)

    def correction_data(self, **changes):
        return {**{key: value if value is not None else "" for key, value in self.row.mapped_data.items()},
            "decision": "correct", "reason": "同一買家改預計領牌日期", **changes}


class HistoricalDateChangeTests(DateChangeFixture, TestCase):
    def test_regular_correction_goes_to_date_review_without_changing_orders(self):
        before = list(SalesOrder.objects.values())
        response = self.client.post(reverse("legacy_import_row_decide", args=[self.batch.pk, self.row.pk]), self.correction_data())
        self.assertRedirects(response, self.url)
        self.assertEqual(before, list(SalesOrder.objects.values()))
        page = self.client.get(self.url)
        self.assertEqual(page.context["form"]["reason"].value(), "同一買家改預計領牌日期")
        self.assertFalse(page.context["form"]["date_kind"].value())
        for key in ("same_buyer_confirmed", "facts_confirmed", "impact_confirmed"):
            self.assertFalse(page.context["form"][key].value())
        editor = self.client.get(reverse("legacy_import_detail", args=[self.batch.pk]), {"edit": self.row.pk})
        self.assertContains(editor, 'name="date_order"')
        self.assertContains(editor, "儲存並核對改期")
        self.assertNotContains(editor, 'name="replacement_order"')

    def test_planned_date_keeps_order_vehicle_payments_and_financials(self):
        PaymentRecord.objects.create(order=self.order, item_name="已有收款", expected_amount=5000, received_amount=5000)
        financial_before = list(OrderOperationsProfile.objects.filter(order=self.order).values())
        payments_before = list(PaymentRecord.objects.filter(order=self.order).values())
        snapshot_before = list(LegacySalesSnapshot.objects.filter(order=self.order).values())
        before_order = SalesOrder.objects.values().get(pk=self.order.pk)
        old_errors = self.batch.result_summary.get("errors", 0)
        self.row.mapped_data.update(cash_received="99999", owner_phone="0999999999")
        self.row.save()
        response = self.client.post(self.url, self.data())
        self.assertRedirects(response, reverse("order_detail", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.row.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertEqual(self.order.status, SalesOrder.Status.ALLOCATED)
        self.assertEqual(str(self.order.registration_date), self.row.mapped_data["registration_date"])
        self.assertIsNone(self.order.registration_completed_at)
        self.assertIsNone(self.order.delivered_at)
        self.assertEqual(self.order.allocated_vehicle_id, self.vehicle_id)
        self.assertEqual(VehicleInventory.objects.get(pk=self.vehicle_id).status, VehicleInventory.Status.RESERVED)
        self.assertEqual(payments_before, list(PaymentRecord.objects.filter(order=self.order).values()))
        self.assertEqual(financial_before, list(OrderOperationsProfile.objects.filter(order=self.order).values()))
        self.assertEqual(snapshot_before, list(LegacySalesSnapshot.objects.filter(order=self.order).values()))
        self.assertEqual(self.row.action, LegacyImportRow.Action.UPDATE)
        self.assertEqual(self.row.committed_pk, str(self.order.pk))
        self.assertEqual(self.batch.result_summary["errors"], max(old_errors - 1, 0))
        self.assertEqual(self.batch.result_summary["updated"], 1)
        after_order = SalesOrder.objects.values().get(pk=self.order.pk)
        allowed = {"registration_date", "registration_completed_at", "registration_completed_by", "delivered_at", "delivered_by", "status", "revision", "updated_at"}
        self.assertEqual({k:v for k,v in before_order.items() if k not in allowed}, {k:v for k,v in after_order.items() if k not in allowed})
        self.assertTrue(OrderEvent.objects.filter(order=self.order, event_type=EVENT).exists())
        self.assertTrue(OrderChange.objects.filter(order=self.order, reason__contains="歷史領牌改期").exists())

    def test_actual_future_or_after_delivery_date_is_blocked(self):
        data = self.data()
        data["date_kind"] = "actual"
        with self.assertRaisesMessage(ValidationError, "未來日期"):
            self.execute(data)
        self.row.mapped_data["registration_date"] = str(timezone.localdate())
        self.row.save()
        with self.assertRaisesMessage(ValidationError, "晚於既有交付"):
            self.execute({**self.data(), "date_kind": "actual"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SalesOrder.Status.COMPLETED)

    def test_actual_past_date_preserves_delivery_and_uses_existing_order(self):
        self.row.mapped_data["registration_date"] = str(self.order.registration_date - timedelta(days=1))
        self.row.save()
        delivered_at = self.order.delivered_at
        changed = self.execute({**self.data(), "date_kind": "actual"})
        self.assertEqual(changed.status, SalesOrder.Status.COMPLETED)
        self.assertEqual(changed.delivered_at, delivered_at)
        self.assertEqual(timezone.localtime(changed.registration_completed_at).date(), changed.registration_date)
        self.assertEqual(changed.allocated_vehicle_id, self.vehicle_id)
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_pending_order_can_reschedule_again_but_not_bypass_normal_registration(self):
        self.execute()
        followup = LegacyImportRow.objects.create(batch=self.batch, sheet_name="銷貨", source_row=1755, action="error",
            fingerprint="followup", natural_key="followup", mapped_data={**self.row.mapped_data, "registration_date": str(timezone.localdate()+timedelta(days=7))})
        self.row = followup
        self.execute()
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_all_confirmations_required_and_service_revalidates(self):
        for key in ("date_kind", "same_buyer_confirmed", "facts_confirmed", "impact_confirmed", "reason"):
            data = self.data()
            data.pop(key)
            with self.assertRaises(ValidationError):
                self.execute(data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SalesOrder.Status.COMPLETED)

    def test_wrong_buyer_identifier_evidence_and_manual_completion_block(self):
        original_mapping = deepcopy(self.row.mapped_data)
        for mapping in ({"owner_name":"其他買家"}, {"owner_id_number":"OTHER-ID"}, {"identifier":"OTHER"}, {"registration_date":"invalid"}):
            self.row.mapped_data = {**original_mapping, **mapping}
            self.row.save()
            with self.assertRaises(ValidationError):
                self.execute()
        self.row.mapped_data = original_mapping
        self.row.save()
        for fields in ({"final_plate_number":"ABC-1234"}, {"delivered_by":"正式交付"}, {"registration_completed_by":"admin"}):
            self.order.refresh_from_db()
            before = {key:getattr(self.order,key) for key in fields}
            SalesOrder.objects.filter(pk=self.order.pk).update(**fields)
            with self.assertRaises(ValidationError):
                self.execute()
            SalesOrder.objects.filter(pk=self.order.pk).update(**before)
        RegistrationDocument.objects.create(order=self.order, document_type="new_license", file="synthetic.jpg")
        with self.assertRaisesMessage(ValidationError, "領牌文件"):
            self.execute()

    def test_permissions_csrf_and_forged_candidate(self):
        staff = get_user_model().objects.create_user("other-admin", is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.execute(user=staff)
        decide = reverse("legacy_import_row_decide", args=[self.batch.pk, self.row.pk])
        self.assertEqual(self.client.post(decide, self.correction_data(date_order=self.order.pk)).status_code, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        self.assertEqual(csrf_client.post(self.url, self.data()).status_code, 403)
        self.client.force_login(self.admin)
        before = dict(self.row.mapped_data)
        response = self.client.post(decide, self.correction_data(date_order=self.order.pk, identifier_raw="OTHER"))
        self.assertEqual(response.status_code, 302)
        self.row.refresh_from_db()
        self.assertEqual(self.row.mapped_data, before)

    def test_stale_financials_rules_and_expired_or_forged_token(self):
        data = self.data()
        OrderOperationsProfile.objects.filter(order=self.order).update(vehicle_cost=123)
        with self.assertRaisesMessage(ValidationError, "資料已變更"):
            self.execute(data)
        data = self.data()
        VehicleSettlementCostRule.objects.create(vehicle_model=self.order.vehicle_model, effective_from=timezone.localdate(), amount=999)
        with self.assertRaisesMessage(ValidationError, "資料已變更"):
            self.execute(data)
        data = self.data()
        with patch("django.core.signing.time.time", return_value=99999999999):
            with self.assertRaises(ValidationError):
                self.execute(data)
        with self.assertRaises(ValidationError):
            self.execute({**self.data(), "preview_token":"bad"})

    def test_failure_after_update_rolls_back_everything(self):
        before = list(SalesOrder.objects.values())
        vehicles = list(VehicleInventory.objects.values())
        with patch("sales.services.historical_date_change.OrderChange.objects.create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                self.execute()
        self.assertEqual(before, list(SalesOrder.objects.values()))
        self.assertEqual(vehicles, list(VehicleInventory.objects.values()))
        self.row.refresh_from_db()
        self.assertEqual(self.row.action, "error")
        self.assertFalse(self.row.committed_pk)

    def test_double_submit_and_reimport_do_not_create_order(self):
        data = self.data()
        self.execute(data)
        with self.assertRaises(ValidationError):
            self.execute(data)
        batch = LegacyImportBatch.objects.create(import_type="operations", status="preview", original_filename="repeat.xlsx", file_size=0)
        repeated = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=1754, fingerprint="repeat",
            natural_key="repeat", mapped_data=dict(self.row.mapped_data))
        revalidate_import_batch(batch)
        repeated.refresh_from_db()
        self.assertEqual(repeated.action, "skip")
        self.assertEqual(SalesOrder.objects.count(), 1)

    def test_original_allocation_and_target_settled_period_are_protected(self):
        dealer = SalesSource.objects.create(name="改期驗收車行", source_type="dealer")
        SalesOrder.objects.filter(pk=self.order.pk).update(source=dealer, source_type="dealer")
        day = timezone.localdate() + timedelta(days=5)
        rule = DealerVolumeBonusRule.objects.create(dealer=dealer, starts_on=day, ends_on=day+timedelta(days=20))
        settlement = DealerVolumeBonusSettlement.objects.create(rule=rule, period=rule.periods.first(), dealer=dealer)
        with self.assertRaisesMessage(ValidationError, "已結算"):
            self.execute()
        DealerVolumeBonusAllocation.objects.create(order=self.order, settlement=settlement, amount=500)
        with self.assertRaisesMessage(ValidationError, "已結算"):
            self.execute()


@skipUnless(connection.vendor == "postgresql", "PostgreSQL 列鎖驗證")
class HistoricalDateChangeConcurrencyTests(DateChangeFixture, TransactionTestCase):
    def test_double_submit_only_updates_once(self):
        data, barrier = self.data(), Barrier(2)
        def submit():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                barrier.wait(timeout=10)
                try:
                    self.execute(data)
                    return "updated"
                except ValidationError:
                    return "blocked"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:submit(), range(2)))
        self.assertCountEqual(results, ["updated", "blocked"])
        self.assertEqual(SalesOrder.objects.count(), 1)
        self.assertEqual(OrderEvent.objects.filter(event_type=EVENT).count(), 1)
