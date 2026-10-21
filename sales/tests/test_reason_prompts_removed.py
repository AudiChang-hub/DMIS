"""不再要求填寫原因（使用者 2026-10-21 T-39 方案 A）。

調整／相異原因整個拿掉；重大動作的原因欄改「備註（選填）」，空白時寫系統摘要；確認步驟與車況描述照舊。
"""
import json
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.forms import (
    AllocationForm, CancellationRequestForm, DealerVolumeBonusAdjustmentForm, DealerVolumeBonusSettlementForm,
    DiscountRequestForm, ExceptionCloseForm, OrderCommissionAttributionForm, OrderEditForm, OverpaymentRefundForm,
    PaymentRecordForm, PaymentReversalForm, ReallocationForm, ReconciliationRecordForm, RefundCompletionForm,
    SubsidyDataForm, VehicleInventoryForm,
)
from sales.historical_date_change import HistoricalDateChangeForm
from sales.historical_replacement import HistoricalReplacementForm
from sales.intake_forms import IntakeOrderForm
from sales.inventory_restore_views import InventoryRestoreForm
from sales.models import OrderChange, OrderEvent, PaymentRecord, SalesOrder, VehicleInventory
from sales.order_deletion_views import DeletionForm
from sales.order_return_views import OrderReturnForm
from sales.permission_workspace import OrderPermissionForm
from sales.print_company_views import CompanyForm
from sales.services.audit_note import SUMMARY_PREFIX, balance_summary, note_or_summary, optional_note, with_note
from sales.services.financial_audit import audit_financial_consistency
from sales.services.order_deletion import change_deletion, review_deletion
from sales.services.payment_ledger import refund_overpayment, reverse_payment
from sales.tests.test_payment_ledger import PaymentLedgerTests
from sales.tests.test_intake_deposit_discount import IntakeFixtures
from sales.tests.test_order_return import ReturnFixtures

GONE_PROMPTS = ("請留下調整原因", "系統會要求記錄原因", "車價調整原因", "優惠原因", "有優惠時必填")


def splits(*rows):
    return json.dumps([{"method": method, "amount": amount} for method, amount in rows])


class AuditNoteTests(SimpleTestCase):
    def test_note_or_summary_prefers_note_and_never_blank(self):
        self.assertEqual(note_or_summary("  客人改口  ", "刪除訂單"), "客人改口")
        self.assertEqual(note_or_summary("", "刪除訂單"), f"{SUMMARY_PREFIX}刪除訂單")
        self.assertEqual(note_or_summary(None, "x" * 600, 300), (SUMMARY_PREFIX + "x" * 600)[:300])
        self.assertEqual(with_note("改回現有庫存", "", "："), "改回現有庫存")
        self.assertEqual(with_note("改回現有庫存", "車在店內", "："), "改回現有庫存：車在店內")
        self.assertEqual(balance_summary("修改訂單資料"), "系統摘要：修改訂單資料時保留人工尾款")

    def test_optional_note_only_limits_length(self):
        self.assertEqual(optional_note("  "), "")
        with self.assertRaisesMessage(ValidationError, "備註最多 5 字"):
            optional_note("123456", 5)


class AdjustmentReasonFieldsRemovedTests(SimpleTestCase):
    """(a) 調整／相異原因：表單上不再有欄位。"""

    def test_adjustment_reason_fields_are_gone(self):
        for form_class, name in (
            (OrderEditForm, "vehicle_price_adjustment_reason"),
            (IntakeOrderForm, "vehicle_price_adjustment_reason"),
            (IntakeOrderForm, "intake_discount_reason"),
            (DiscountRequestForm, "reason"),
            (PaymentRecordForm, "expected_amount_override_reason"),
            (ReconciliationRecordForm, "expected_amount_override_reason"),
            (AllocationForm, "skip_reason"),
            (OrderCommissionAttributionForm, "reason"),
            (DealerVolumeBonusSettlementForm, "adjustment_reason"),
            (DealerVolumeBonusAdjustmentForm, "reason"),
            (OrderEditForm, "change_reason"),
            (SubsidyDataForm, "change_reason"),
            (VehicleInventoryForm, "change_reason"),
        ):
            with self.subTest(form=form_class.__name__, field=name):
                self.assertNotIn(name, form_class.base_fields)

    def test_major_action_notes_are_optional(self):
        """(b) 重大動作：原因欄改「備註（選填）」。"""
        for form_class in (
            DeletionForm, OrderReturnForm, InventoryRestoreForm, CancellationRequestForm, ExceptionCloseForm,
            PaymentReversalForm, OverpaymentRefundForm, ReallocationForm, HistoricalDateChangeForm,
            HistoricalReplacementForm, CompanyForm, OrderPermissionForm,
        ):
            with self.subTest(form=form_class.__name__):
                field = form_class.base_fields["reason"]
                self.assertFalse(field.required)
                self.assertEqual(field.label, "備註（選填）")
        for form_class in (OrderReturnForm, ExceptionCloseForm, RefundCompletionForm):
            with self.subTest(form=form_class.__name__, field="forfeit_reason"):
                self.assertFalse(form_class.base_fields["forfeit_reason"].required)
                self.assertNotIn("原因", form_class.base_fields["forfeit_reason"].label)


class IntakeWithoutReasonTests(IntakeFixtures):
    def test_price_differs_from_recommendation_saves_without_reason(self):
        self.client.force_login(self.root)
        response = self.submit(payment_splits=splits(("cash", 50000), ("card", 20000)))
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        order = SalesOrder.objects.latest("pk")
        self.assertEqual(order.vehicle_price, 70000)
        self.assertEqual(order.vehicle_price_adjustment_reason, "")
        self.assertNotIn("adjustment_reason", order.price_snapshot)

    def test_intake_discount_needs_no_reason_and_contract_says_approved(self):
        from sales.services.document_signing import contract_terms
        self.client.force_login(self.root)
        response = self.submit(intake_discount_mode="amount", intake_discount_amount="1800")
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        order = SalesOrder.objects.latest("pk")
        self.assertEqual((order.approved_discount_amount, order.discount_reason), (1800, ""))
        self.assertEqual(contract_terms(order)["approved_discount_amount"], "1800")
        event = OrderEvent.objects.get(order=order, event_type="discount_decided")
        self.assertNotIn("原因", event.description)

    def test_order_form_has_no_reason_prompts(self):
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_create"))
        self.assertEqual(page.status_code, 200)
        for text in (*GONE_PROMPTS, "vehicle_price_adjustment_reason", "intake_discount_reason"):
            with self.subTest(text=text):
                self.assertNotContains(page, text)
        self.assertContains(page, "成交價不同時直接修改即可")

    def test_old_price_reason_is_still_shown(self):
        self.client.force_login(self.root)
        self.submit()
        order = SalesOrder.objects.latest("pk")
        SalesOrder.objects.filter(pk=order.pk).update(vehicle_price_adjustment_reason="舊資料的調價說明")
        page = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(page, "舊資料的調價說明")


class WorkspaceWithoutReasonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 與收款帳本測試同一張單（總價 70,000 以 v2 應收計算）。
        PaymentLedgerTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)
        self.order.refresh_from_db()

    def receipt(self, amount, **kwargs):
        return PaymentRecord.objects.create(
            order=self.order, item_name=kwargs.pop("item_name", "客戶匯款"), received_amount=Decimal(amount),
            received_on=date(2026, 9, 21), payment_method="匯款", confirmed=True, **kwargs,
        )

    def test_reversal_and_refund_without_note_write_summary(self):
        paid = self.receipt(20000)
        reversal = reverse_payment(order_id=self.order.pk, payment_id=paid.pk, actor_name="測試", reason=" ")
        self.assertEqual(reversal.adjustment_reason, "系統摘要：沖銷 客戶匯款 20,000 元")
        self.assertTrue(OrderChange.objects.filter(order=self.order, reason=reversal.adjustment_reason).exists())
        with_note_reversal = reverse_payment(order_id=self.order.pk, payment_id=self.receipt(1000).pk,
                                             actor_name="測試", reason="重複登記")
        self.assertEqual(with_note_reversal.adjustment_reason, "重複登記")
        event = OrderEvent.objects.filter(order=self.order, event_type="payment_reversed").latest("pk")
        self.assertIn("備註：重複登記", event.description)

    def test_overpayment_refund_without_note_writes_summary(self):
        from sales.services.payment_ledger import refundable_overpayment
        self.receipt(75000)
        limit = refundable_overpayment(self.order, "customer")
        self.assertEqual(limit, 5000)
        record = refund_overpayment(order_id=self.order.pk, kind="customer", amount=limit, actor_name="測試", reason="",
                                    method_label="匯款", refunded_on=date(2026, 9, 22))
        self.assertTrue(record.adjustment_reason.startswith(SUMMARY_PREFIX + "退還溢收"))

    def test_balance_differs_without_reason_passes_validation_and_audit(self):
        order = SalesOrder.objects.get(pk=self.order.pk)
        order.actual_balance = order.calculated_balance + 300
        order.balance_adjustment_reason = ""
        order.full_clean()
        # 舊資料可能有人工尾款卻沒有原因：完整性報告不再列出這一項。
        SalesOrder.objects.filter(pk=order.pk).update(actual_balance=order.actual_balance, balance_adjustment_reason="")
        self.assertNotIn("balance_reason_missing", audit_financial_consistency()["finding_counts"])

    def test_deletion_request_and_delete_without_note(self):
        order = SalesOrder.objects.get(pk=self.order.pk)
        review_deletion(user=self.admin, order_id=order.pk, action="request", reason="",
                        expected_updated_at=order.updated_at.isoformat())
        order.refresh_from_db()
        self.assertEqual(order.deletion_request_reason, "")
        self.assertTrue(OrderEvent.objects.filter(order=order, event_type="deletion_request",
                                                  description="申請刪除，等待 admin 確認").exists())
        from sales.services.order_deletion import confirmation_token
        change_deletion(user=self.admin, order_id=order.pk, restore=False, reason="",
                        expected_updated_at=order.updated_at.isoformat(), editing_session="",
                        force=True, confirmation=confirmation_token(order, self.admin))
        deleted = SalesOrder.all_objects.get(pk=order.pk)
        self.assertTrue(deleted.deletion_reason.startswith(f"{SUMMARY_PREFIX}刪除訂單 {order.number}"))


class ReturnWithoutReasonTests(ReturnFixtures, TestCase):
    def test_return_without_notes_still_checks_identifier(self):
        order = self.delivered_order(self.vehicle())
        self.receipt(order, "50000")
        with self.assertRaisesMessage(ValidationError, "末 4 碼"):
            self.do_return(order, reason="", confirm_identifier="9999")
        self.do_return(order, reason="", forfeited_amount=5000, forfeit_reason="",
                       method=SalesOrder.PaymentMethod.TRANSFER)
        self.assertEqual(order.exception_reason, "交車後退車")
        self.assertEqual(order.forfeit_reason, "系統摘要：交車後退車沒收 5,000 元")
        change = OrderChange.objects.get(order=order)
        self.assertTrue(change.reason.startswith(SUMMARY_PREFIX + "交車後退車"))
        vehicle = VehicleInventory.objects.get(pk=order.exception_vehicle_id)
        self.assertFalse(vehicle.history_entries.get().reason.endswith("："))

    def test_return_page_has_no_required_reason(self):
        order = self.delivered_order(self.vehicle())
        page = self.client.get(reverse("order_return", args=[order.pk]))
        self.assertContains(page, "備註（選填）")
        self.assertNotContains(page, "退車原因")
        self.assertContains(page, "末 4 碼")
