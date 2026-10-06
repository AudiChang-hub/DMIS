"""收入與支出分欄、傭金預先帶入（車行／本店人員）與車行結算。"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import (
    AccessoryLine, OrderOperationsProfile, PrintCompany, SalesOrder, SalesSource, SalesSourceBrandPolicy,
    VehicleColor, VehicleModel,
)
from sales.services.dealer_commission import apply_order_dealer_commission
from sales.services.dealer_settlement import dealer_settlement
from sales.services.finance_ledger import finance_totals, ledger_fields
from sales.services.operations_sync import sync_order_operations
from sales.tests.profit_helpers import unlock_profit


class FinanceLedgerTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", password="Test-Only-123")
        cls.dealer = SalesSource.objects.create(name="結算車行", source_type="dealer")
        cls.other_dealer = SalesSource.objects.create(name="歸屬車行", source_type="dealer")
        cls.staff = SalesSource.objects.create(name="馭盛 王小明", source_type="store", staff_commission=1500)
        cls.platform = SalesSource.objects.create(name="測試平台", source_type="platform")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="結算車型", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        SalesSourceBrandPolicy.objects.create(
            source=cls.dealer, cooperation_scope=SalesSourceBrandPolicy.CooperationScope.SUZUKI_GAS,
            commission_adjustment=300, effective_from=date(2026, 1, 1),
        )

    def make_order(self, **kwargs):
        fields = dict(
            source_type="dealer", source=self.dealer, order_date=date(2026, 9, 1), owner_type="company",
            owner_name="測試公司", owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址",
            vehicle_model=self.model, color=self.color, vehicle_price=Decimal("79800"), plate_insurance_fee=Decimal("2350"),
            payment_type="cash", delivery_method="store_pickup",
        )
        fields.update(kwargs)
        order = SalesOrder(**fields)
        order.calculated_balance = order.calculate_balance()
        order.actual_balance = order.calculated_balance
        order.save()
        return order

    def profile(self, order):
        return OrderOperationsProfile.objects.get(order=order)


class CommissionPrefillTests(FinanceLedgerTestBase):
    def test_new_dealer_order_gets_configured_commission(self):
        order = self.make_order()
        profile = self.profile(order)
        self.assertEqual(profile.dealer_commission_expense, 2300)
        self.assertEqual((profile.dealer_commission_base, profile.dealer_commission_adjustment), (2000, 300))

    def test_order_create_view_prefills_commission(self):
        company = PrintCompany.objects.create(
            key=f"dealer:{self.dealer.pk}", source=self.dealer, legal_name="結算車行有限公司",
            tax_id="12345678", address="測試地址", phone="02-12345678",
        )
        self.client.force_login(self.admin)
        data = dict(
            source_type="dealer", source=str(self.dealer.pk), owner_type="company", owner_name="測試公司",
            owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", id_verified="on",
            vehicle_model=str(self.model.pk), color=str(self.color.pk), payment_type="cash", vehicle_price="70000",
            vehicle_category="new", transaction_type="regular_new", plate_choice="none", delivery_method="store_pickup",
            deposit_amount="0", plate_insurance_fee="0", installment_opening_fee="0",
            assisted_company_confirmed="on", assisted_company_revision=str(company.revision),
            **{"accessories-TOTAL_FORMS": "0", "accessories-INITIAL_FORMS": "0", "accessories-MIN_NUM_FORMS": "0",
               "accessories-MAX_NUM_FORMS": "1000", "other_fees-TOTAL_FORMS": "0", "other_fees-INITIAL_FORMS": "0",
               "other_fees-MIN_NUM_FORMS": "0", "other_fees-MAX_NUM_FORMS": "1000"},
        )
        response = self.client.post(reverse("order_create"), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.assertEqual(self.profile(SalesOrder.objects.get()).dealer_commission_expense, 2300)

    def test_manual_override_survives_later_saves(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            dealer_commission_expense=999, manual_financial_fields=["dealer_commission_expense"],
        )
        order.refresh_from_db()
        order.owner_name = "改名公司"
        order.save()
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).dealer_commission_expense, 999)

    def test_store_staff_commission_is_prefilled(self):
        order = self.make_order(source_type="store", source=self.staff)
        profile = self.profile(order)
        self.assertEqual(profile.dealer_commission_expense, 1500)
        self.assertEqual(profile.dealer_commission_base, 1500)

    def test_store_order_assigned_to_dealer_keeps_existing_no_base_rule(self):
        order = self.make_order(source_type="store", source=self.staff, commission_recipient=self.other_dealer)
        self.assertEqual(self.profile(order).dealer_commission_expense, 0)

    def test_store_without_staff_source_and_platform_have_no_commission(self):
        self.assertEqual(self.profile(self.make_order(source_type="store", source=None)).dealer_commission_expense, 0)
        platform = self.make_order(source_type="platform", source=self.platform)
        self.assertEqual(self.profile(platform).dealer_commission_expense, 0)

    def test_registration_lock_freezes_staff_commission(self):
        order = self.make_order(source_type="store", source=self.staff)
        apply_order_dealer_commission(order, lock=True)
        self.assertIsNotNone(self.profile(order).dealer_commission_locked_at)
        SalesSource.objects.filter(pk=self.staff.pk).update(staff_commission=4000)
        order.refresh_from_db()
        apply_order_dealer_commission(order)
        self.assertEqual(self.profile(order).dealer_commission_expense, 1500)

    def test_registered_orders_are_not_recomputed_by_sync(self):
        order = self.make_order(registration_date=date(2026, 9, 2), registration_completed_at=timezone.now(),
                                status=SalesOrder.Status.DELIVERY_PENDING)
        OrderOperationsProfile.objects.filter(order=order).update(dealer_commission_expense=1234)
        VehicleModel.objects.filter(pk=self.model.pk).update(base_dealer_commission=9000)
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).dealer_commission_expense, 1234)

    def test_sync_without_changes_keeps_financial_revision(self):
        order = self.make_order()
        before = self.profile(order).updated_at
        sync_order_operations(order.pk)
        self.assertEqual(self.profile(order).updated_at, before)


class DealerSettlementTests(FinanceLedgerTestBase):
    def settle(self, order):
        return dealer_settlement(order, self.profile(order))

    def test_cash_uses_original_price_despite_discount(self):
        order = self.make_order(approved_discount_amount=Decimal("5000"), discount_status="approved",
                                discount_reason="測試優惠", balance_adjustment_reason="")
        AccessoryLine.objects.create(order=order, name="置物箱", amount=1200, labor_fee=300)
        result = self.settle(order)
        # 79800 − 2300 + 2350 + 1500
        self.assertEqual(result["total"], 81350)
        self.assertEqual((result["direction"], result["label"], result["amount"]), ("collect", "向車行收", 81350))
        self.assertEqual([term["key"] for term in result["terms"]], ["vehicle_price", "commission", "plate_insurance", "accessories"])
        self.assertEqual(result["terms"][0]["amount"], 79800)

    def test_installment_only_accessories_minus_commission(self):
        order = self.make_order(payment_type="installment", installment_company="和潤", installment_amount=79800,
                                installment_periods=24, installment_monthly=3600, plate_insurance_fee=0)
        result = self.settle(order)
        self.assertEqual(result["total"], -2300)
        self.assertEqual((result["direction"], result["label"], result["amount"]), ("pay", "付給車行", 2300))

    def test_installment_positive_when_accessories_exceed_commission(self):
        order = self.make_order(payment_type="installment", installment_company="和潤", installment_amount=79800,
                                installment_periods=24, installment_monthly=3600, plate_insurance_fee=0)
        AccessoryLine.objects.create(order=order, name="後架", amount=3000, labor_fee=500)
        self.assertEqual(self.settle(order)["total"], 1200)

    def test_zero_needs_no_settlement(self):
        order = self.make_order(payment_type="installment", installment_company="和潤", installment_amount=79800,
                                installment_periods=24, installment_monthly=3600, plate_insurance_fee=0)
        AccessoryLine.objects.create(order=order, name="後架", amount=2300)
        result = self.settle(order)
        self.assertEqual((result["total"], result["direction"], result["label"]), (0, "none", "無需收付"))

    def test_non_dealer_orders_have_no_settlement(self):
        self.assertIsNone(self.settle(self.make_order(source_type="store", source=self.staff)))
        self.assertIsNone(self.settle(self.make_order(source_type="platform", source=self.platform)))


class FinanceStepPageTests(FinanceLedgerTestBase):
    def setUp(self):
        self.client.force_login(self.admin)

    def finance_panel(self, order):
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        return page, page.split('id="panel-finance"', 1)[1].split('id="panel-delivery"', 1)[0]

    def test_ledger_covers_every_profit_field_once(self):
        income, expense = ledger_fields()
        expected_income = {"actual_disbursement", *OrderOperationsProfile.INCOME_FIELDS, *OrderOperationsProfile.INCENTIVE_FIELDS}
        expected_expense = {"vehicle_cost", *OrderOperationsProfile.EXPENSE_FIELDS}
        self.assertEqual(sorted(income), sorted(expected_income))
        self.assertEqual(sorted(expense), sorted(expected_expense))
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_cost=60000, sales_bonus=800, gift_expense=500)
        profile = self.profile(order)
        totals = finance_totals(profile)
        self.assertEqual(totals["net"], profile.net_profit)

    def test_step_renders_income_and_expense_blocks_with_same_post_names(self):
        order = self.make_order()
        _page, finance = self.finance_panel(order)
        income = finance.split('data-ledger-block="income"', 1)[1].split('data-ledger-block="expense"', 1)[0]
        expense = finance.split('data-ledger-block="expense"', 1)[1].split('finance-ledger__legend', 1)[0]
        for name in ("actual_disbursement", *OrderOperationsProfile.INCOME_FIELDS, *OrderOperationsProfile.INCENTIVE_FIELDS):
            self.assertEqual(income.count(f'name="operations-{name}"'), 1, name)
        for name in ("vehicle_cost", *OrderOperationsProfile.EXPENSE_FIELDS):
            self.assertEqual(expense.count(f'name="operations-{name}"'), 1, name)
        self.assertIn("傭金支出（車行／本店人員）", expense)
        self.assertIn("獎勵與補助", income)
        self.assertIn('name="_section" value="finance"', finance)
        self.assertIn('data-workspace-save="operations"', finance)
        self.assertIn("收款與分期對帳", finance)
        self.assertIn("沖銷與退款", finance)
        self.assertIn("系統帶入", expense)

    def test_manual_tag_follows_manual_fields(self):
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(
            dealer_commission_expense=999, manual_financial_fields=["dealer_commission_expense"],
        )
        _page, finance = self.finance_panel(order)
        row = finance.split('name="operations-dealer_commission_expense"', 1)[0].rsplit("data-ledger-row", 1)[1]
        self.assertIn("已人工調整", row)

    def test_dealer_order_shows_settlement_in_finance_and_delivery(self):
        order = self.make_order()
        page, finance = self.finance_panel(order)
        self.assertIn("data-dealer-settlement", finance)
        self.assertIn("向車行收", finance)
        self.assertIn("$79,800", finance)
        delivery = page.split('id="panel-delivery"', 1)[1]
        self.assertIn('id="dealer-settlement"', delivery)

    def test_plate_variance_confirm_lives_in_strip_once(self):
        order = self.make_order()
        SalesOrder.objects.filter(pk=order.pk).update(registration_calculated_total=2000)
        _page, finance = self.finance_panel(order)
        self.assertIn("牌險差異", finance)
        self.assertEqual(finance.count(reverse("registration_fee_variance_confirm", args=[order.pk])), 1)

    def test_non_dealer_order_has_no_settlement(self):
        page, _finance = self.finance_panel(self.make_order(source_type="store", source=self.staff))
        self.assertNotIn("data-dealer-settlement", page)

    def test_net_profit_stays_gated(self):
        order = self.make_order()
        _page, finance = self.finance_panel(order)
        self.assertNotIn("data-profit-value", finance)
        self.assertNotIn("data-ledger-net-card", finance)
        self.assertIn("收入合計", finance)
        unlock_profit(self, self.admin)
        _page, finance = self.finance_panel(order)
        self.assertIn("data-profit-value", finance)
        self.assertIn("data-ledger-net-card", finance)
