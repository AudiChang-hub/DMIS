"""付款方式可多筆（使用者 2026-10-16）：預設一筆現金帶現金價，可再新增刷卡、匯款、分期；車價＝各筆合計。"""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import InstallmentCompany, InstallmentPlanOption, InstallmentPlanVersion, SalesOrder
from sales.services.customer_receivable import default_customer_balance
from sales.services.installment_plan import apply_order_installment_snapshot
from sales.tests import test_order_intake as intake_fixtures


def splits(*rows):
    return json.dumps([{"method": method, "amount": amount} for method, amount in rows])


class PaymentSplitTests(TestCase):
    setUp = intake_fixtures.OrderIntakeTests.setUp
    image = intake_fixtures.OrderIntakeTests.image
    complete_data = intake_fixtures.OrderIntakeTests.complete_data
    submit = intake_fixtures.OrderIntakeTests.submit

    def create(self, **changes):
        self.client.force_login(self.root)
        response = self.submit(**changes)
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        return SalesOrder.objects.latest("pk")

    def errors(self, **changes):
        self.client.force_login(self.root)
        response = self.submit(**changes)
        self.assertEqual(response.status_code, 200)
        return response.context["form"].errors

    def test_form_shows_payment_methods_not_primary_payment(self):
        self.client.force_login(self.root)
        page = self.client.get(reverse("order_create"))
        self.assertContains(page, 'id="id_payment_splits"')
        self.assertContains(page, "＋ 新增付款方式")
        self.assertContains(page, "付款方式<em>必填</em>", html=False)
        self.assertNotContains(page, "主要付款方式")
        methods = json.loads(page.context["form"].fields["payment_splits"].widget.attrs["data-split-methods"])
        self.assertEqual([m["label"] for m in methods], ["現金", "刷卡", "匯款", "分期"])

    def test_single_cash_row_without_amount_defaults_to_cash_price(self):
        order = self.create(payment_splits=splits(("cash", None)), vehicle_price="")
        self.assertEqual((order.payment_type, order.vehicle_price), ("cash", 79800))
        self.assertEqual(order.payment_splits, [{"method": "cash", "amount": 79800}])

    def test_multiple_methods_sum_to_vehicle_price_and_derive_basis(self):
        order = self.create(payment_splits=splits(("cash", 50000), ("card", 20000), ("transfer", 9800)))
        self.assertEqual((order.payment_type, order.vehicle_price), ("cash", 79800))
        self.assertEqual(order.payment_split_display, "現金 $50,000＋刷卡 $20,000＋匯款 $9,800")
        self.assertEqual(order.payment_method_labels, "現金＋刷卡＋匯款")
        order = self.create(payment_splits=splits(("card", 40000), ("card", 39800)))
        self.assertEqual(order.payment_type, "card")
        self.assertEqual(order.payment_method_labels, "刷卡")

    def test_changed_total_still_requires_adjustment_reason(self):
        errors = self.errors(payment_splits=splits(("cash", 50000), ("card", 20000)))
        self.assertIn("vehicle_price_adjustment_reason", errors)

    def test_multiple_rows_need_amounts_and_known_methods(self):
        self.assertIn("payment_splits", self.errors(payment_splits=splits(("cash", 1000), ("card", None))))
        self.assertIn("payment_splits", self.errors(payment_splits=splits(("bitcoin", 79800))))
        self.assertIn("payment_splits", self.errors(payment_splits=splits(("cash", -1), ("card", 79801))))
        self.assertFalse(SalesOrder.objects.exists())

    def test_installment_with_cash_part_bills_customer_and_scales_disbursement(self):
        company = InstallmentCompany.objects.create(name="分期甲")
        version = InstallmentPlanVersion.objects.create(
            vehicle_model=self.model, effective_from=timezone.localdate() - timedelta(days=30))
        InstallmentPlanOption.objects.create(
            version=version, company=company, periods=24, monthly_amount=3000, opening_fee=0,
            expected_disbursement_method="rate", expected_disbursement_rate=Decimal("90"))
        order = self.create(
            payment_splits=splits(("cash", 20000), ("installment", 59800)),
            installment_company="分期甲", installment_periods="24", installment_monthly="3000",
        )
        self.assertEqual(order.payment_type, "installment")
        self.assertEqual((order.installment_split_amount, order.customer_vehicle_split_amount), (59800, 20000))
        self.assertEqual(order.installment_plan_snapshot["expected_disbursement_amount"], 53820)
        mixed_balance = default_customer_balance(order)
        order.payment_splits = [{"method": "installment", "amount": 79800}]
        self.assertEqual(mixed_balance - default_customer_balance(order), 20000)
        apply_order_installment_snapshot(order)
        self.assertEqual(order.installment_plan_snapshot["expected_disbursement_amount"], 71820)

    def test_legacy_order_without_splits_reads_as_one_row(self):
        order = SalesOrder(payment_type="installment", vehicle_price=Decimal("50000"))
        self.assertEqual([(row["label"], row["amount"]) for row in order.payment_split_rows], [("分期", 50000)])
        self.assertEqual((order.installment_split_amount, order.customer_vehicle_split_amount), (50000, 0))
        self.assertEqual(order.payment_split_display, "分期")

    def test_requests_without_splits_keep_single_payment_type(self):
        order = self.create(payment_type="card", vehicle_price="79800")
        self.assertEqual(order.payment_type, "card")
        self.assertEqual(order.payment_splits, [{"method": "card", "amount": 79800}])
