"""訂購單收款資料（使用者 2026-10-20，SO20261020-FDD722）：總價－車價分期金額＝分期外應收，分期外應收－已收訂金＝尾款。"""
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from sales.models import AccessoryLine, OrderChange, PaymentRecord, SalesOrder, SalesOrderSearchIndex
from sales.services.customer_receivable import customer_receivable_total, installment_customer_part
from sales.services.operations_sync import sync_order_operations
from sales.services.order_contract_pdf import build_order_contract_pdf
from sales.tests import test_order_flow as flow


def pdf_text(order):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(build_order_contract_pdf(order))).pages)


def payment_section(text):
    """訂購單第一聯「收款資料」表的文字（兩聯內容相同）。"""
    start = text.index("收款資料")
    return text[start:text.index("確認事項", start)].replace(chr(10), " ")


def assert_in_order(test, text, parts):
    positions = [text.index(part) for part in parts]
    test.assertEqual(positions, sorted(positions), parts)


class InstallmentReceivableTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def fdd722(self, **overrides):
        """依 SO20261020-FDD722 的金額：車價 79,800 全額分期；牌險 1,500、選號 1,200、配件 6,500＋0＋2,100、配件金折抵 −1,000、訂金 7,000。"""
        order = self.make_order()
        fields = {
            "payment_type": SalesOrder.PaymentType.INSTALLMENT, "cash_receivable_v2": True,
            "vehicle_price": Decimal("79800"), "plate_insurance_fee": Decimal("1500"), "plate_insurance_auto": False,
            "plate_selection_fee": Decimal("1200"), "approved_discount_amount": Decimal("1000"), "discount_reason": "配件金折抵",
            "deposit_amount": Decimal("7000"), "installment_company": "和潤", "installment_periods": 24,
            "installment_monthly": Decimal("3325"), "installment_amount": Decimal("79800"), "payment_splits": [],
        }
        fields.update(overrides)
        SalesOrder.objects.filter(pk=order.pk).update(**fields)
        for name, amount in (("MS206行車紀錄器", 6500), ("五匹手機架", 0), ("原廠踩發桿", 2100)):
            AccessoryLine.objects.create(order=order, name=name, quantity=1, amount=Decimal(amount), labor_fee=0)
        sync_order_operations(order.pk, update_receivables=True)
        return SalesOrder.objects.get(pk=order.pk)

    def test_fdd722_receivable_is_total_minus_vehicle_and_balance_minus_deposit(self):
        order = self.fdd722()
        # 總價 90,100（車價 79,800＋牌險 1,500＋選號 1,200＋配件 8,600－折抵 1,000）－車價 79,800＝10,300。
        self.assertEqual(installment_customer_part(order), Decimal("10300"))
        self.assertEqual(order.customer_receivable_total, Decimal("10300"))
        self.assertEqual(order.customer_balance_due, Decimal("3300"))

        text = pdf_text(order)
        section = payment_section(text)
        assert_in_order(self, section, ["總價 $90,100", "車價分期金額 $79,800", "分期外應收 $10,300",
                                        "已收訂金 $7,000", "尾款 $3,300"])
        self.assertNotIn("分期還款總額", text)
        self.assertNotIn("預估尾款", text)
        # 總價等於「車價與費用明細」逐列合計，不需要補調整列。
        self.assertNotIn("應收調整", text)
        self.assertEqual(len(PdfReader(BytesIO(build_order_contract_pdf(order))).pages), 2)

    def test_order_page_and_overview_show_receivable_then_deposit_then_balance(self):
        order = self.fdd722()
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only"))
        detail = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(detail, '<span>分期外應收</span><strong data-customer-receivable>$10,300</strong>', html=False)
        self.assertContains(detail, "<span>− 訂金</span><strong>$7,000</strong>", html=False)
        self.assertContains(detail, '<span>尾款</span><strong data-customer-balance>$3,300', html=False)
        overview = self.client.get(reverse("order_overview", args=[order.pk])).content.decode()
        self.assertIn("分期外應收", overview)
        self.assertIn("10,300", overview)
        self.assertIn("3,300", overview)

    def test_zero_deposit_receivable_equals_balance(self):
        order = self.fdd722(deposit_amount=Decimal("0"))
        self.assertEqual(order.customer_receivable_total, Decimal("10300"))
        self.assertEqual(order.customer_balance_due, Decimal("10300"))
        assert_in_order(self, payment_section(pdf_text(order)),
                        ["總價 $90,100", "車價分期金額 $79,800", "分期外應收 $10,300", "已收訂金 $0", "尾款 $10,300"])

    def test_deposit_over_customer_part_keeps_receivable_at_customer_part(self):
        # 訂金多於客人自付部分：尾款停在 0，分期外應收仍是自付部分，不把多收的訂金當應收。
        order = self.fdd722(deposit_amount=Decimal("12000"))
        self.assertEqual(order.customer_balance_due, Decimal("0"))
        self.assertEqual(order.customer_receivable_total, Decimal("10300"))

    def test_opening_fee_is_paid_by_customer_outside_installment(self):
        # 只有車價可以分期（使用者 2026-10-20）：開辦費列在明細、算進總價，也由客人自付。
        order = self.fdd722(installment_opening_fee=Decimal("1500"))
        self.assertEqual(order.customer_receivable_total, Decimal("11800"))
        self.assertEqual(order.customer_balance_due, Decimal("4800"))
        text = pdf_text(order)
        self.assertIn("分期開辦費", text)
        self.assertNotIn("應收調整", text)
        assert_in_order(self, payment_section(text), ["總價 $91,600", "車價分期金額 $79,800", "分期外應收 $11,800",
                                                      "已收訂金 $7,000", "尾款 $4,800"])

    def test_custom_installment_and_cash_split_count_customer_vehicle_part(self):
        # 自訂分期（不套車型方案）＋客人先付現金 20,000、其餘 59,800 分期：自付車款算進分期外應收。
        order = self.fdd722(
            installment_company="自訂分期公司", installment_plan_snapshot={}, installment_amount=Decimal("59800"),
            payment_splits=[{"method": "cash", "amount": "20000"}, {"method": "installment", "amount": "59800"}],
        )
        self.assertEqual(order.customer_vehicle_split_amount, Decimal("20000"))
        self.assertEqual(order.customer_receivable_total, Decimal("30300"))
        self.assertEqual(order.customer_balance_due, Decimal("23300"))
        assert_in_order(self, payment_section(pdf_text(order)),
                        ["總價 $90,100", "車價分期金額 $59,800", "分期外應收 $30,300", "已收訂金 $7,000", "尾款 $23,300"])

    def test_saved_receivable_override_carries_into_receivable_total(self):
        # 收支頁人工調整過應收：分期外應收跟著保存的尾款加回訂金，兩個數字對得起來。
        order = self.fdd722()
        order.payment_records.filter(system_key="balance").update(expected_amount=2800, expected_amount_overridden=True)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.customer_balance_due, Decimal("2800"))
        self.assertEqual(order.customer_receivable_total, Decimal("9800"))
        # 差額列成「應收調整」，明細合計仍等於收款資料的總價。
        text = pdf_text(order)
        self.assertIn("應收調整", text)
        self.assertIn("-500", text)
        assert_in_order(self, payment_section(text), ["總價 $89,600", "分期外應收 $9,800", "尾款 $2,800"])

    def test_cash_order_reads_total_then_deposit_then_balance(self):
        order = self.make_order()  # 車價 79,800、訂金 4,600、尾款 75,200
        self.assertEqual(order.customer_receivable_total, order.customer_balance_due + order.deposit_amount)
        text = pdf_text(order)
        section = payment_section(text)
        assert_in_order(self, section, ["付款方式", "總價 $79,800", "已收訂金 $4,600", "訂金收款日", "收款方式", "尾款 $75,200"])
        self.assertNotIn("車價分期金額", section)
        self.assertNotIn("分期外應收", section)
        self.assertNotIn("預估尾款", text)

    def test_signed_contract_file_and_fingerprint_untouched(self):
        order = self.make_order(signed=True)
        SalesOrder.objects.filter(pk=order.pk).update(signed_contract_fingerprint="a" * 64)
        order = SalesOrder.objects.get(pk=order.pk)
        with order.signed_contract.open("rb") as handle:
            before = handle.read()
        pdf_text(order)
        customer_receivable_total(order)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.signed_contract_fingerprint, "a" * 64)
        with order.signed_contract.open("rb") as handle:
            self.assertEqual(handle.read(), before)


class BalancePaymentLabelTests(TestCase):
    """收支頁系統收款列：扣訂金後的金額一律叫「尾款」；既有「分期外應收」由指令回填（只改名稱）。"""
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order
    fdd722 = InstallmentReceivableTests.fdd722

    def balance_row(self, order):
        return order.payment_records.get(system_key="balance")

    def test_sync_names_installment_balance_row_tail_payment(self):
        order = self.fdd722()
        row = self.balance_row(order)
        self.assertEqual(row.item_name, "尾款")
        self.assertEqual(row.expected_amount, Decimal("3300"))

    def run_command(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("rename_balance_payment_label", *args, stdout=out)
        return out.getvalue()

    def legacy_rows(self):
        """模擬正式站：分期單尾款列仍叫「分期外應收」，其中一筆已收款確認。"""
        from django.utils import timezone
        first, second = self.fdd722(), self.fdd722(deposit_amount=Decimal("0"))
        PaymentRecord.objects.filter(order__in=[first, second], system_key="balance").update(item_name="分期外應收")
        PaymentRecord.objects.filter(order=second, system_key="balance").update(
            received_amount=Decimal("10300"), received_on=timezone.localdate(), confirmed=True)
        return first, second

    def snapshot(self):
        return list(PaymentRecord.objects.filter(system_key="balance").order_by("pk").values_list(
            "pk", "expected_amount", "received_amount", "received_on", "confirmed", "payment_method"))

    def test_dry_run_lists_rows_without_writing(self):
        first, second = self.legacy_rows()
        output = self.run_command()
        self.assertIn("符合：2 筆（其中已收款或已確認 1 筆，只改名稱）", output)
        self.assertIn(f"{first.number}｜收款列 #{self.balance_row(first).pk}｜分期外應收 → 尾款", output)
        self.assertIn("dry-run：未寫入", output)
        self.assertEqual(PaymentRecord.objects.filter(item_name="分期外應收").count(), 2)
        self.assertFalse(OrderChange.objects.filter(actor_name__startswith="系統資料整理").exists())

    def test_apply_renames_only_label_with_audit_and_search_index_then_rollback(self):
        first, second = self.legacy_rows()
        before = self.snapshot()
        self.run_command("--apply")
        self.assertEqual(self.snapshot(), before, "金額、實收、日期、確認狀態都不能變")
        self.assertFalse(PaymentRecord.objects.filter(item_name="分期外應收").exists())
        self.assertEqual(self.balance_row(second).item_name, "尾款")
        changes = OrderChange.objects.filter(actor_name="系統資料整理（依使用者 2026-10-20）")
        self.assertEqual(changes.count(), 2)
        self.assertEqual(changes.first().changes, {"收款項目": {"before": "分期外應收", "after": "尾款"}})
        payload = str(SalesOrderSearchIndex.objects.get(order=first).match_payload)
        self.assertNotIn("分期外應收", payload)
        # 已改名再跑一次不會重複寫入。
        self.assertIn("符合：0 筆", self.run_command("--apply"))
        self.assertEqual(changes.count(), 2)

        self.run_command("--rollback")
        self.assertEqual(PaymentRecord.objects.filter(item_name="分期外應收").count(), 2)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("分期外應收", str(SalesOrderSearchIndex.objects.get(order=first).match_payload))

    def test_order_page_and_overview_call_it_tail_payment(self):
        order = self.fdd722()
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="test-only"))
        detail = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertNotIn("預估尾款", detail)
        overview = self.client.get(reverse("order_overview", args=[order.pk])).content.decode()
        self.assertNotIn("尾款（應收）", overview)
        self.assertNotIn("預估尾款", overview)
