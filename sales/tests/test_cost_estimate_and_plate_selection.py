"""1.63.0：領牌前以訂單日預估車輛成本；選號費在訂車時填寫並計入總價與收支（2026-10-15 起不併入牌險）。"""
from datetime import date
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from sales.forms import OrderEditForm
from sales.models import OrderOperationsProfile, OtherFeeLine, SalesOrder, VehicleSettlementCostRule
from sales.services.customer_receivable import default_customer_balance
from sales.services.operations_sync import sync_order_operations
from sales.services.settlement_cost import apply_order_settlement_cost
from sales.tests import test_completed_order_corrections as correction_tests


class CostEstimateAndPlateSelectionTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order
    payload = correction_tests.CompletedOrderCorrectionTests.payload
    post = correction_tests.CompletedOrderCorrectionTests.post
    assert_saved = correction_tests.CompletedOrderCorrectionTests.assert_saved

    def pending(self, **overrides):
        data = dict(status=SalesOrder.Status.ALLOCATION_PENDING, registration_date=None, order_date=date(2026, 9, 10),
                    actual_balance=70000, plate_insurance_fee=0, registration_plate_fee=0, registration_calculated_total=0)
        data.update(overrides)
        return self.order(**data)

    def test_cost_is_estimated_by_order_date_then_follows_registration_date(self):
        VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("60000"), effective_from=date(2026, 9, 1))
        later = VehicleSettlementCostRule.objects.create(vehicle_model=self.model, amount=Decimal("61000"), effective_from=date(2026, 10, 1))
        order = self.pending()
        sync_order_operations(order.pk)
        profile = OrderOperationsProfile.objects.get(order=order)
        self.assertEqual(profile.vehicle_cost, Decimal("60000"), "領牌前依訂單日預估")
        self.assertIsNone(profile.vehicle_cost_locked_at)
        order.registration_date = date(2026, 10, 5)
        order.save(update_fields=["registration_date", "updated_at"])
        profile = apply_order_settlement_cost(order, "tester", lock=True)
        self.assertEqual(profile.vehicle_cost, Decimal("61000"), "領牌後依領牌日重新帶入")
        self.assertEqual(profile.vehicle_cost_rule, later)
        self.assertIsNotNone(profile.vehicle_cost_locked_at)

    def test_estimate_without_rule_keeps_existing_cost(self):
        order = self.pending()
        profile, _ = OrderOperationsProfile.objects.get_or_create(order=order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(vehicle_cost=Decimal("55555"))
        sync_order_operations(order.pk)
        self.assertEqual(OrderOperationsProfile.objects.get(pk=profile.pk).vehicle_cost, Decimal("55555"))

    def test_switching_from_watch_clears_plate_selection_fee(self):
        # 使用者 2026-10-17：只有指定號碼有選號費。原本指定號碼已填 1,200，改成一般領牌偏好後
        # 欄位隱藏但表單仍帶著舊值，送出要歸零。
        order = self.pending(plate_choice="watch", plate_selection_fee=1200, watched_numbers="ABC-1234", actual_balance=71200)
        response = self.post(order, plate_choice="preference", watched_numbers="", plate_preference_note="尾數要大",
                             plate_insurance_fee="0", registration_date="", confirm_completed_correction="")
        self.assert_saved(response, order)
        self.assertEqual(order.plate_choice, "preference")
        self.assertEqual(order.plate_selection_fee, Decimal("0"))
        self.assertEqual(order.calculate_balance(), Decimal("70000"))

    def test_detail_and_contract_pdf_show_plate_selection_fee_only_for_watch(self):
        # 使用者 2026-10-17：訂單明細頁與訂購單 PDF 只有「指定號碼」才列選號費；
        # 其他選號方式沒有選號費欄位可填，照實際畫面不填選號費送出。
        from io import BytesIO

        from django.urls import reverse
        from pypdf import PdfReader

        from sales.services.order_contract_pdf import build_order_contract_pdf

        cases = (
            ("watch", {"watched_numbers": "ABC-1234", "plate_selection_fee": "1200"}, True),
            ("preference", {"plate_preference_note": "尾數要大", "plate_selection_fee": ""}, False),
            ("none", {"plate_selection_fee": ""}, False),
            ("pending", {"plate_selection_fee": ""}, False),
        )
        for choice, fields, shown in cases:
            with self.subTest(plate_choice=choice):
                order = self.pending(plate_choice=choice)
                response = self.post(order, plate_choice=choice, plate_insurance_fee="0", registration_date="",
                                     confirm_completed_correction="", **fields)
                self.assert_saved(response, order)
                self.assertEqual(order.plate_selection_fee, Decimal("1200" if shown else "0"))
                page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
                order.print_company_snapshot = {"legal_name": "測試機車行", "tax_id": "12345678",
                                                "address": "測試地址", "phone": "02-1234"}
                pdf = PdfReader(BytesIO(build_order_contract_pdf(order)))
                pdf_text = "".join(item.extract_text() for item in pdf.pages)
                self.assertEqual("<dt>選號</dt>" in page, shown)
                self.assertEqual("＋ 選號" in page, shown)
                self.assertEqual("選號費" in pdf_text, shown)

    def test_plate_selection_fee_counts_before_registration_date(self):
        order = self.pending(plate_choice="watch")
        response = self.post(order, plate_choice="watch", plate_selection_fee="1200", plate_insurance_fee="0",
                             registration_date="", confirm_completed_correction="")
        self.assert_saved(response, order)
        self.assertEqual(order.plate_selection_fee, Decimal("1200"))
        self.assertEqual(order.plate_insurance_fee, Decimal("0"))
        self.assertEqual(order.calculate_balance(), Decimal("71200"))
        profile = OrderOperationsProfile.objects.get(order=order)
        # 選號收入＝客人付的選號費，支出預設監理站 1,000；差額留在選號，不併入代辦費。
        self.assertEqual(profile.plate_selection_income, Decimal("1200"))
        self.assertEqual(profile.plate_selection_expense, Decimal("1000"))
        self.assertEqual(profile.agency_fee_income, Decimal("0"))
        page = self.client.get(f"/orders/{order.pk}/?tab=order")
        self.assertContains(page, 'data-conditional="plate-selection"')

    def test_installment_customer_balance_includes_plate_selection(self):
        order = self.pending(payment_type="installment", installment_company="測試分期", installment_periods=24,
                             installment_monthly=Decimal("2917"), installment_amount=70000, cash_receivable_v2=True,
                             plate_selection_fee=1200, plate_insurance_fee=0, registration_calculated_total=0,
                             actual_balance=71200)
        self.assertEqual(default_customer_balance(order), Decimal("1200"))

    def test_migration_moves_plate_selection_other_fee(self):
        order = self.pending(plate_choice="watch")
        OtherFeeLine.objects.create(order=order, name="選號", amount=1200)
        before_total = SalesOrder.objects.get(pk=order.pk).calculate_balance()
        import_module("sales.migrations.0174_move_plate_selection_other_fee").move(django_apps, None)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.plate_selection_fee, Decimal("1200"))
        self.assertEqual(order.plate_insurance_fee, Decimal("1200"))
        self.assertFalse(order.other_fees.exists())
        # 0185 再把選號從牌險移出、另列總價（2026-10-15）：兩步合計客人應付總額不變。
        from django.db import connection
        from django.db.migrations.loader import MigrationLoader
        state_apps = MigrationLoader(connection).project_state(("sales", "0185_plate_fee_excludes_selection")).apps
        import_module("sales.migrations.0185_plate_fee_excludes_selection").forwards(state_apps, None)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(order.plate_insurance_fee, Decimal("0"))
        self.assertEqual(order.calculate_balance(), before_total, "客人應付總額不變")
        self.assertTrue(order.events.filter(actor_name__contains="選號費搬移").exists())
