"""T-332 A 案：訂單收支的支出加「牌險手續費支出」。

使用者 2026-11-28 選 A：欄位人工填寫、系統不自動算也不帶差額；所有品牌與交易類型都顯示，預設 0；
算進支出合計與訂單淨利（含營運總表、淨利排序、匯出與回匯）。舊單、匯入單都是 0，淨利不變；
牌險計算、成本規則與傭金不動。
"""
from decimal import Decimal

from django.urls import reverse

from sales.models import OrderOperationsProfile, SalesOrder, SalesSource
from sales.order_exchange import columns as cols
from sales.order_exchange import reimport
from sales.services.finance_ledger import EXPENSE_GROUPS, finance_ledger, finance_totals
from sales.services.legacy_finance import MAPPING, reconcile_source
from sales.services.order_sorting import sort_orders
from sales.services.sales_metrics import summarize_sales
from sales.tests.test_finance_ledger import FinanceLedgerTestBase
from sales.tests.test_order_workspace import form_data, formset_data

FIELD = "plate_insurance_fee_expense"
# 改版前（2.42.x）的支出欄位：用來證明既有訂單的淨利改版前後相同。
EXPENSE_FIELDS_BEFORE = (
    "legacy_card_fee_expense",
    "installment_fee_expense", "used_vehicle_expense", "gift_shipping_expense",
    "friendly_dealer_bonus_expense", "first_sale_bonus_expense", "volume_bonus_expense",
    "registration_tax_expense",
    "compulsory_insurance_expense", "plate_selection_expense",
    "gift_expense", "shipping_expense", "dealer_commission_expense",
    "card_fee_expense",
)
# 改版前的淨利算法（車價收入－車輛成本－支出＋收入＋獎勵與補助），逐欄照舊相加。
def profit_before(profile):
    amount = lambda name: getattr(profile, name) or Decimal("0")  # noqa: E731
    return (amount("actual_disbursement") - amount("vehicle_cost")
            - sum((amount(name) for name in EXPENSE_FIELDS_BEFORE), Decimal("0"))
            + sum((amount(name) for name in OrderOperationsProfile.INCOME_FIELDS), Decimal("0"))
            + sum((amount(name) for name in OrderOperationsProfile.INCENTIVE_FIELDS), Decimal("0")))


class PlateInsuranceFeeExpenseTests(FinanceLedgerTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.store = SalesSource.objects.create(name="測試本店", source_type="store")

    def setUp(self):
        self.client.force_login(self.admin)

    def filled_profile(self, order):
        """填一組明顯虛構的收支，讓淨利不是 0。"""
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=79800, vehicle_cost=60000, gift_expense=500, shipping_expense=300,
            installment_fee_expense=1500, other_income=200, sales_bonus=800,
        )
        return self.profile(order)

    # ---- 欄位與計算 ----
    def test_field_definition_matches_other_expense_fields(self):
        field = OrderOperationsProfile._meta.get_field(FIELD)
        reference = OrderOperationsProfile._meta.get_field("installment_fee_expense")
        self.assertEqual(str(field.verbose_name), "牌險手續費支出")
        self.assertEqual((field.max_digits, field.decimal_places, field.default),
                         (reference.max_digits, reference.decimal_places, reference.default))
        self.assertEqual(field.db_default, 0)
        self.assertIn(FIELD, OrderOperationsProfile.EXPENSE_FIELDS)
        # 純人工欄位：不是系統帶入、也不會被訂單同步覆蓋。
        self.assertNotIn(FIELD, OrderOperationsProfile.MANUAL_PROTECTABLE_FINANCIAL_FIELDS)

    def test_existing_order_profit_is_unchanged(self):
        order = self.make_order(plate_insurance_fee=Decimal("2340"))
        profile = self.filled_profile(order)
        self.assertEqual(getattr(profile, FIELD), 0)
        self.assertEqual(profile.net_profit, profit_before(profile))
        self.assertEqual(finance_totals(profile)["net"], profit_before(profile))

    def test_filled_amount_reduces_profit_by_exactly_that_amount(self):
        order = self.make_order(plate_insurance_fee=Decimal("2340"))
        profile = self.filled_profile(order)
        before_profit, before_expense = profile.net_profit, profile.total_expense
        before_commission = profile.dealer_commission_expense
        before_tax = (profile.registration_tax_expense, profile.compulsory_insurance_expense, profile.agency_fee_income)
        OrderOperationsProfile.objects.filter(order=order).update(**{FIELD: 375})
        profile = self.profile(order)
        self.assertEqual(profile.net_profit, before_profit - 375)
        self.assertEqual(profile.total_expense, before_expense + 375)
        self.assertEqual(finance_totals(profile)["net"], profile.net_profit)
        # 牌險計算與傭金不動。
        self.assertEqual(profile.dealer_commission_expense, before_commission)
        self.assertEqual((profile.registration_tax_expense, profile.compulsory_insurance_expense,
                          profile.agency_fee_income), before_tax)

    def test_operations_summary_and_profit_sort_include_the_expense(self):
        first = self.make_order()
        second = self.make_order()
        for order in (first, second):
            self.filled_profile(order)
        OrderOperationsProfile.objects.filter(order=first).update(**{FIELD: 2000})
        orders = SalesOrder.objects.filter(pk__in=[first.pk, second.pk]).select_related("operations")
        summary = summarize_sales(orders)
        expected = sum((self.profile(order).net_profit for order in (first, second)), Decimal("0"))
        self.assertEqual(summary["net_profit"], expected)
        self.assertEqual(self.profile(first).net_profit, self.profile(second).net_profit - 2000)
        ranked = list(sort_orders(SalesOrder.objects.filter(pk__in=[first.pk, second.pk]), ["profit"]))
        self.assertEqual([order.pk for order in ranked], [first.pk, second.pk])

    def test_imported_finance_never_fills_the_field(self):
        self.assertNotIn(FIELD, MAPPING)
        reconciliation, values = reconcile_source({"收款價": "80000", "成本": "60000", "單筆淨利": "20000"})
        self.assertEqual(reconciliation["status"], "matched")
        self.assertNotIn(FIELD, values)
        self.assertEqual(getattr(OrderOperationsProfile(**values), FIELD), 0)

    # ---- 訂單頁「收入與支出」 ----
    def expense_block(self, order):
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        finance = page.split('id="panel-finance"', 1)[1].split('id="panel-delivery"', 1)[0]
        return finance.split('data-ledger-block="expense"', 1)[1].split("finance-ledger__legend", 1)[0]

    def test_field_sits_with_card_and_installment_fee_expenses(self):
        group = next(names for title, _hint, names in EXPENSE_GROUPS if title == "手續費")
        self.assertEqual(group, ("card_fee_expense", "installment_fee_expense", FIELD))
        expense = self.expense_block(self.make_order())
        self.assertEqual(expense.count(f'name="operations-{FIELD}"'), 1)
        self.assertLess(expense.index('name="operations-installment_fee_expense"'), expense.index(f'name="operations-{FIELD}"'))
        self.assertIn("牌險手續費支出", expense)
        self.assertIn("自行填寫，系統不自動算", expense)

    def test_every_transaction_type_shows_an_editable_field(self):
        orders = {
            "dealer": self.make_order(),
            "store": self.make_order(source_type="store", source=self.store),
            "installment": self.make_order(payment_type="installment", installment_company="測試分期", installment_amount=79800,
                                           installment_periods=24, installment_monthly=3600),
            "proxy_delivery": self.make_order(source_type="store", source=self.store, transaction_type="proxy_delivery"),
            "prize": self.make_order(source_type="store", source=self.store, transaction_type="prize"),
        }
        for label, order in orders.items():
            with self.subTest(label):
                expense = self.expense_block(order)
                row = expense.split(f'name="operations-{FIELD}"', 1)[0].rsplit("<input", 1)[1]
                self.assertNotIn("disabled", row)
                ledger = finance_ledger(self.operations_form(order), self.profile(order))
                rows = [row for group in ledger["expense"]["groups"] for row in group["rows"] if row["name"] == FIELD]
                self.assertEqual(len(rows), 1)
                self.assertFalse(rows[0]["not_applicable"])
                self.assertEqual(rows[0]["tag"], "")

    def operations_form(self, order, data=None):
        from sales.forms import OrderOperationsForm
        return OrderOperationsForm(data, instance=self.profile(order), prefix="operations", section="finance")

    def test_autosave_stores_the_amount_and_lowers_profit(self):
        from sales.services.order_workspace import payment_formset_for
        order = self.make_order()
        self.filled_profile(order)
        data = form_data(self.operations_form(order))
        data.update(formset_data(payment_formset_for(SalesOrder.objects.get(pk=order.pk))))
        data.update({"_section": "finance", f"operations-{FIELD}": "640"})
        response = self.client.post(reverse("order_operations", args=[order.pk]), data, HTTP_X_ORDER_WORKSPACE="1")
        self.assertEqual(response.status_code, 200, response.content.decode()[:500])
        self.assertTrue(response.json().get("ok"), response.json())
        profile = self.profile(order)
        self.assertEqual(getattr(profile, FIELD), 640)
        # 存檔時其他系統欄位照舊同步；淨利正好是改版前算法再少這 640。
        self.assertEqual(profile.net_profit, profit_before(profile) - 640)
        self.assertEqual(finance_totals(profile)["net"], profile.net_profit)

    # ---- 匯出與回匯 ----
    def test_export_offers_the_column_without_changing_defaults(self):
        column = cols.COLUMN_BY_KEY[FIELD]
        self.assertEqual((column.label, column.group, column.editable), ("牌險手續費支出", "finance", True))
        self.assertNotIn(FIELD, cols.DEFAULT_COLUMNS)
        self.assertNotIn(FIELD, cols.DEFAULT_EXTRA_COLUMNS)
        self.assertEqual(len(cols.LEGACY_EXPORT), 92)
        self.assertIn(FIELD, reimport.FINANCE_KEYS)
        order = self.make_order()
        OrderOperationsProfile.objects.filter(order=order).update(**{FIELD: 120})
        self.assertEqual(cols.row_values(SalesOrder.objects.get(pk=order.pk), [column]), [Decimal("120")])
