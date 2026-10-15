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


class AgencyFeeTests(FinanceLedgerTestBase):
    """牌險不含選號；規費／強制險／選號收入等於支出，溢收（可為負）記代辦費收入（使用者 2026-10-15）。"""

    # 規費 300＋150＋200＋450＋700＝1,800；兩年強制險 1,200；試算合計 3,000（不含選號）。
    REGISTERED = dict(
        registration_date=date(2026, 9, 10), compulsory_insurance_period=2,
        registration_plate_fee=300, registration_license_fee=150, registration_inspection_fee=200,
        road_maintenance_fee=450, license_tax_fee=700, compulsory_insurance_fee=1200,
        registration_calculated_total=3000,
    )

    def synced(self, order):
        sync_order_operations(order.pk)
        return self.profile(order)

    def test_plate_and_selection_surplus_go_to_agency_fee(self):
        order = self.make_order(plate_insurance_fee=3200, plate_selection_fee=1200, plate_choice="preference", **self.REGISTERED)
        profile = self.synced(order)
        self.assertEqual((profile.registration_tax_expense, profile.registration_tax_income), (1800, 1800))
        self.assertEqual((profile.compulsory_insurance_expense, profile.compulsory_insurance_income), (1200, 1200))
        self.assertEqual((profile.plate_selection_expense, profile.plate_selection_income), (1000, 1000))
        self.assertEqual(profile.agency_fee_income, 200 + 200)
        self.assertFalse(order.plate_fee_shortfall)
        # 總價另加選號：79,800＋3,200＋1,200。
        self.assertEqual(order.calculate_balance(), 84200)

    def test_agent_selection_expense_removes_selection_surplus(self):
        order = self.make_order(plate_insurance_fee=3200, plate_selection_fee=1200, plate_choice="preference", **self.REGISTERED)
        profile = self.synced(order)
        profile.plate_selection_expense = 1200
        profile.manual_financial_fields = ["plate_selection_expense"]
        profile.save()
        profile = self.synced(order)
        self.assertEqual((profile.plate_selection_expense, profile.plate_selection_income), (1200, 1200))
        self.assertEqual(profile.agency_fee_income, 200)

    def test_plate_shortfall_is_negative_and_flagged_even_with_selection_surplus(self):
        order = self.make_order(plate_insurance_fee=2700, plate_selection_fee=1200, plate_choice="preference", **self.REGISTERED)
        profile = self.synced(order)
        self.assertEqual(profile.agency_fee_income, -300 + 200)
        order.refresh_from_db()
        self.assertTrue(order.plate_fee_shortfall)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("order_list")).content.decode()
        self.assertIn("order-plate-shortfall", page)

    def test_unregistered_gas_order_counts_only_selection_surplus(self):
        order = self.make_order(plate_insurance_fee=3200, plate_selection_fee=1200, plate_choice="preference",
                                compulsory_insurance_fee=1200)
        profile = self.synced(order)
        self.assertEqual(profile.agency_fee_income, 200)
        self.assertIsNone(order.plate_fee_surplus)
        self.assertFalse(order.plate_fee_shortfall)

    def test_manual_agency_fee_survives_sync(self):
        order = self.make_order(plate_insurance_fee=3200, **self.REGISTERED)
        profile = self.synced(order)
        profile.agency_fee_income = 900
        profile.manual_financial_fields = ["agency_fee_income"]
        profile.save()
        self.assertEqual(self.synced(order).agency_fee_income, 900)

    def test_installment_fee_expense_defaults_to_opening_fee(self):
        order = self.make_order(payment_type="installment", installment_company="和潤", installment_amount=79800,
                                installment_periods=24, installment_monthly=3600, installment_opening_fee=1500)
        profile = self.synced(order)
        self.assertEqual((profile.installment_fee_income, profile.installment_fee_expense), (1500, 1500))

    def test_completed_order_finance_is_not_recalculated(self):
        order = self.make_order(plate_insurance_fee=3200, **self.REGISTERED)
        profile = self.profile(order)
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(registration_tax_income=1400, agency_fee_income=0)
        SalesOrder.objects.filter(pk=order.pk).update(status=SalesOrder.Status.COMPLETED)
        profile = self.synced(order)
        self.assertEqual((profile.registration_tax_income, profile.agency_fee_income), (1400, 0))


    def electric_order(self, energy_type, registration_class="", **extra):
        model = VehicleModel.objects.create(brand="GOGORO", name=f"電動 {energy_type}{registration_class}",
                                            energy_type=energy_type, electric_registration_class=registration_class)
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        return self.make_order(vehicle_model=model, color=color, **extra)

    def test_electric_costs_use_fixed_fee_and_equivalent_gas_insurance(self):
        # 規則填的是向客人收的總額；成本：規費 650，強制險重型比照 125cc、輕型比照 50cc（使用者 2026-10-15）。
        heavy = self.electric_order("electric", "heavy", plate_insurance_fee=2263, compulsory_insurance_period=1)
        profile = self.synced(heavy)
        self.assertEqual((profile.registration_tax_expense, profile.compulsory_insurance_expense), (650, 658))
        self.assertEqual((profile.registration_tax_income, profile.compulsory_insurance_income), (650, 658))
        self.assertEqual(profile.agency_fee_income, 2263 - 650 - 658)
        light = self.electric_order("light_electric", plate_insurance_fee=2340, compulsory_insurance_period=2)
        profile = self.synced(light)
        self.assertEqual((profile.registration_tax_expense, profile.compulsory_insurance_expense), (650, 1200))
        self.assertEqual(profile.agency_fee_income, 2340 - 650 - 1200)

    def test_micro_electric_costs_are_three_year_fixed(self):
        micro = self.electric_order("micro_electric", plate_insurance_fee=2300, compulsory_insurance_period=3)
        profile = self.synced(micro)
        self.assertEqual((profile.registration_tax_expense, profile.compulsory_insurance_expense), (450, 1358))
        self.assertEqual(profile.agency_fee_income, 2300 - 450 - 1358)
        # 微電車沒收牌險：建單就看得出牌險少收。
        unpaid = self.electric_order("micro_electric", plate_insurance_fee=0, plate_selection_fee=1200, plate_choice="watch")
        profile = self.synced(unpaid)
        self.assertEqual(profile.agency_fee_income, -450 - 1358 + 200)
        self.assertTrue(unpaid.plate_fee_shortfall)

    def test_migration_moves_selection_out_of_existing_plate_fee(self):
        from importlib import import_module

        from django.db import connection
        from django.db.migrations.loader import MigrationLoader

        migration = import_module("sales.migrations.0185_plate_fee_excludes_selection")
        apps = MigrationLoader(connection).project_state(("sales", "0185_plate_fee_excludes_selection")).apps
        order = self.make_order(plate_insurance_fee=2606, plate_selection_fee=1200, plate_choice="watch",
                                registration_calculated_total=2606)
        # 牌險本來就沒有併入選號（例如微電車手填 0）：進行中訂單尾款補上選號。
        missing = self.make_order(plate_insurance_fee=0, plate_selection_fee=1200, plate_choice="watch")
        SalesOrder.objects.filter(pk=missing.pk).update(calculated_balance=79800, actual_balance=79800)
        profile = self.profile(order)
        profile.plate_selection_income = 1200
        profile.manual_financial_fields = ["plate_selection_income", "registration_tax_income"]
        profile.save()
        migration.forwards(apps, None)
        order.refresh_from_db()
        missing.refresh_from_db()
        self.assertEqual((order.plate_insurance_fee, order.registration_calculated_total), (1406, 1406))
        # 舊口徑總價 79,800＋2,606（含選號）＝新口徑 79,800＋1,406＋1,200。
        self.assertEqual(order.calculate_balance(), 79800 + 2606)
        self.assertEqual(missing.plate_insurance_fee, 0)
        self.assertEqual((missing.calculated_balance, missing.actual_balance), (81000, 81000))
        self.assertEqual(missing.calculate_balance(), missing.actual_balance)
        self.assertEqual(self.profile(order).manual_financial_fields, ["registration_tax_income"])


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

    def test_store_order_hides_dealer_receipt_fields(self):
        _page, finance = self.finance_panel(self.make_order(source_type="store", source=self.staff))
        self.assertNotIn('name="operations-dealer_name"', finance)
        self.assertNotIn('name="operations-payment_confirmed"', finance)
        _page, finance = self.finance_panel(self.make_order())
        self.assertIn('name="operations-dealer_name"', finance)
        self.assertIn('name="operations-payment_confirmed"', finance)

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
