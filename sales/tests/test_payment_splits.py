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

    def test_contract_pdf_lists_each_payment_on_its_own_line(self):
        # 使用者 2026-10-16：訂購單 PDF 的付款方式每筆各占一行，不在金額中間斷行。
        from io import BytesIO
        from pypdf import PdfReader
        order = self.create(payment_splits=splits(("cash", 50000), ("card", 20000), ("transfer", 9800)))
        response = self.client.get(reverse("contract_print", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(BytesIO(b"".join(response.streaming_content)))
        lines = [line.strip() for page in reader.pages for line in page.extract_text().splitlines()]
        for expected in ("現金 $50,000", "刷卡 $20,000", "匯款 $9,800"):
            # 兩聯各一次：付款方式只列在「訂單與車主資料」，收款資料不再重複（使用者 2026-10-20）。
            self.assertEqual(sum(expected in line for line in lines), 2, expected)
        self.assertFalse([line for line in lines if "＋" in line and "$" in line])

    def test_wizard_draft_keeps_every_payment_split(self):
        # 回歸（1.85.1）：草稿保存的付款明細是 JSON 字串，下一步不可再編碼一次而退回單筆。
        import html
        import re
        import uuid
        from sales.models import OrderDraft
        self.client.force_login(self.root)
        key = str(uuid.uuid4())
        two_rows = splits(("cash", 20000), ("installment", 55000))
        extra = dict(payment_splits=two_rows, vehicle_price_adjustment_reason="部分付現",
                     installment_custom="on", installment_company="分期甲", installment_periods="24",
                     installment_monthly="3000")
        draft = None
        for step in ("vehicle", "owner", "tradein", "delivery", "accessories", "deposit"):
            data = {**self.complete_data(), **extra, "_wizard_step": step, "_wizard_action": "next", "_submission_key": key}
            if draft:
                data.update(_draft_id=str(draft.pk), _draft_revision=str(draft.revision))
            response = self.client.post(reverse("order_create"), data)
            self.assertEqual(response.status_code, 302, response.content.decode()[:300])
            draft = OrderDraft.objects.get()
            page = self.client.get(response.url).content.decode()
            value = re.search(r'name="payment_splits"[^>]*value="([^"]*)"|value="([^"]*)"[^>]*name="payment_splits"', page)
            rendered = json.loads(html.unescape(value.group(1) or value.group(2)))
            self.assertEqual(rendered, json.loads(two_rows), step)
            extra["payment_splits"] = json.dumps(rendered)  # 瀏覽器下一步送回的是畫面上的值
        # 確認頁與訂購單 PDF 一致：每筆各占一行（1.85.2）。
        confirm = self.client.get(f"{reverse('order_create')}?draft={draft.pk}&step=confirm")
        self.assertContains(confirm, "<dd>現金 $20,000<br>分期 $55,000</dd>", html=False)
        data = {**self.complete_data(), **extra, "_wizard_step": "confirm", "_wizard_action": "submit",
                "_submission_key": key, "_draft_id": str(draft.pk), "_draft_revision": str(draft.revision)}
        response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 302, response.content.decode()[:300])
        order = SalesOrder.objects.get()
        self.assertEqual(order.payment_splits, json.loads(two_rows))
        self.assertEqual((order.installment_split_amount, order.customer_vehicle_split_amount), (55000, 20000))
        detail = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(detail, "<dt>付款方式</dt><dd><span>現金 $20,000</span><span>分期 $55,000</span></dd>", html=False)

    def test_form_initial_from_draft_string_is_not_double_encoded(self):
        from sales.forms import SalesOrderForm
        form = SalesOrderForm(initial={"payment_splits": splits(("cash", 20000), ("card", 5000))})
        self.assertEqual(json.loads(form["payment_splits"].value() if isinstance(form["payment_splits"].value(), str)
                                    else json.dumps(form["payment_splits"].value())),
                         [{"method": "cash", "amount": 20000}, {"method": "card", "amount": 5000}])
        self.assertIn("&quot;method&quot;: &quot;cash&quot;", str(form["payment_splits"]))

    def test_user_guide_explains_multi_payment_like_manual(self):
        # 線上使用說明與使用手冊第 1 步一致（1.85.4）。
        from pathlib import Path
        self.client.force_login(self.root)
        guide = self.client.get(reverse("user_guide"))
        self.assertContains(guide, 'id="multi-payment-current"')
        self.assertContains(guide, 'href="#multi-payment-current"')
        manual = Path("docs/USER_MANUAL.md").read_text(encoding="utf-8")
        for phrase in ("＋ 新增付款方式", "尚餘 $60,000", "車價合計", "每期金額與開辦費會直接帶入", "現金 $50,000", "刷卡 $22,000",
                       "現金 $20,000＋分期 $60,000", "只剩一筆時不能移除"):
            self.assertContains(guide, phrase)
            self.assertIn(phrase, manual)
        self.assertContains(guide, "第一筆付款方式的預設")
