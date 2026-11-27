"""T-320 代交車、中獎車：交易類型、不計業績、報表中心各自成一類（使用者 2026-11-25 定案）。

- 不新增欄位：既有的交易類型加「代交車」；不計業績＝交易類型是代交車或中獎車。
- 只能本店現金單、不能指定歸屬車行；車價收入與車輛成本固定 0；牌險、配件照一般規則。
- 不計業績：營運總表主數字、賣速／缺貨／滯銷、報表平均車價、本店人員傭金。
- 一般銷售完全不受影響（各段都有對照）。Excel 匯入單只改歸類與口徑，收支與限制不回頭套用。
"""
import re
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.forms import (
    NON_PERFORMANCE_KEEP_RECIPIENT_ERROR, NON_PERFORMANCE_PAYMENT_ERROR, NON_PERFORMANCE_RECIPIENT_ERROR,
    NON_PERFORMANCE_SOURCE_ERROR, OrderOperationsForm, SalesOrderForm,
)
from sales.models import (
    LegacyImportBatch, LegacyImportRow, LegacySalesSnapshot, OrderChange, OrderEvent, OrderOperationsProfile,
    ReportDefinition, SalesOrder, SalesSource, Store, VehicleColor, VehicleInventory, VehicleModel,
    VehicleSettlementCostRule,
)
from sales.order_exchange import columns as export_columns
from sales.reporting.engine import (
    FIXED_COLOR_SLOTS, FIXED_COLOR_VARS, PALETTE, base_query, card_result, dimension_color, drill_query, fixed_color,
)
from sales.reporting.forms import FilterForm
from sales.reporting.records import record_context
from sales.reporting.source_compatibility import (
    SOURCE_CLASSIFICATIONS, STORE_STAFF_NAMES, sales_source_expression, sales_source_query,
)
from sales.reporting.views import initial_config
from sales.services import operations_cockpit
from sales.services.dashboard_metrics import build_dashboard_metrics
from sales.services.dealer_commission import apply_order_dealer_commission, store_staff_commission
from sales.services.finance_ledger import finance_ledger
from sales.services.operations_sync import sync_order_operations
from sales.services.order_filters import filter_order_analysis, performance_orders
from sales.services.settlement_cost import apply_order_settlement_cost

PROXY = SalesOrder.TransactionType.PROXY_DELIVERY
PRIZE = SalesOrder.TransactionType.PRIZE
REGULAR = SalesOrder.TransactionType.REGULAR_NEW
TODAY = date(2026, 11, 20)


def mark_imported(order, fingerprint):
    batch = LegacyImportBatch.objects.create(import_type="operations", original_filename="t320.xlsx", file_size=0)
    row = LegacyImportRow.objects.create(batch=batch, sheet_name="銷貨", source_row=1, fingerprint=fingerprint)
    LegacySalesSnapshot.objects.create(order=order, import_row=row)
    return SalesOrder.objects.get(pk=order.pk)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 帳號名稱要是 admin：系統管理員才有淨利、收支等全部畫面（sales/access/services.py）。
        cls.admin = get_user_model().objects.create_superuser("admin", "t320@example.invalid", "Test-Only-123")
        cls.dealer = SalesSource.objects.create(name="甲車行", source_type="dealer")
        cls.platform = SalesSource.objects.create(name="示範平台", source_type="platform")
        cls.staff = SalesSource.objects.create(name=STORE_STAFF_NAMES[0], source_type="store", staff_commission=800)
        cls.proxy_source = SalesSource.objects.create(name="代交車", source_type="store")
        cls.model = VehicleModel.objects.create(brand="SUZUKI", name="代交測試車", energy_type="gas", base_dealer_commission=2000)
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.ev = VehicleModel.objects.create(brand="SUZUKI", name="代交測試電車", energy_type="electric")
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name="藍")
        cls.cost_rule = VehicleSettlementCostRule.objects.create(
            vehicle_model=cls.model, amount=56000, effective_from=date(2025, 1, 1))

    def setUp(self):
        cache.clear()

    def make_order(self, kind=REGULAR, **kwargs):
        non_performance = kind in SalesOrder.NON_PERFORMANCE_TRANSACTION_TYPES
        fields = dict(
            transaction_type=kind, source_type="store", source=None, order_date=date(2026, 11, 1),
            owner_type="company", owner_name="合成車主", owner_id_number="83739807", owner_phone="0912345678",
            owner_address="合成地址", vehicle_model=self.model, color=self.color,
            vehicle_price=Decimal("0") if non_performance else Decimal("70000"),
            plate_insurance_fee=Decimal("2350"), payment_type="cash", delivery_method="store_pickup",
        )
        fields.update(kwargs)
        order = SalesOrder(**fields)
        order.calculated_balance = order.calculate_balance()
        order.actual_balance = order.calculated_balance
        order.save()
        return order

    def registered(self, kind=REGULAR, day=TODAY, **kwargs):
        kwargs.setdefault("status", "completed")
        order = self.make_order(kind, registration_date=day, established_on=day,
                                registration_completed_at=timezone.now(), **kwargs)
        apply_order_settlement_cost(order, "測試人員", lock=True)    # 比照領牌完成：依領牌日帶入並鎖定成本
        return SalesOrder.objects.get(pk=order.pk)

    def profile(self, order):
        return OrderOperationsProfile.objects.get(order=order)

    def post_data(self, **kwargs):
        data = dict(source_type="store", source="", owner_type="company", owner_name="測試公司",
                    owner_id_number="83739807", owner_phone="0912345678", owner_address="測試地址", id_verified="on",
                    vehicle_model=str(self.model.pk), color=str(self.color.pk), payment_type="cash", vehicle_price="70000",
                    transaction_type="regular_new", plate_choice="none", delivery_method="store_pickup",
                    deposit_amount="0", plate_insurance_fee="2350", installment_opening_fee="0",
                    **{"accessories-TOTAL_FORMS": "0", "accessories-INITIAL_FORMS": "0", "accessories-MIN_NUM_FORMS": "0",
                       "accessories-MAX_NUM_FORMS": "1000", "other_fees-TOTAL_FORMS": "0", "other_fees-INITIAL_FORMS": "0",
                       "other_fees-MIN_NUM_FORMS": "0", "other_fees-MAX_NUM_FORMS": "1000"})
        data.update(kwargs)
        return data


class TransactionTypeRulesTests(Base):
    """建單、訂單頁與模型的限制：本店、現金、不能指定歸屬車行、車價 0；結案後不能改。"""

    def test_proxy_delivery_is_a_transaction_type_and_both_kinds_are_non_performance(self):
        self.assertEqual(dict(SalesOrder.TransactionType.choices)[PROXY], "代交車")
        self.assertEqual(set(SalesOrder.NON_PERFORMANCE_TRANSACTION_TYPES), {PROXY, PRIZE})
        self.assertFalse(hasattr(SalesOrder, "is_proxy_delivery"))   # 不新增欄位
        for kind in SalesOrder.TransactionType.values:
            order = SalesOrder(transaction_type=kind)
            self.assertEqual(order.is_non_performance, kind in (PROXY, PRIZE), kind)

    def test_form_forces_store_cash_and_zero_price(self):
        for kind in (PROXY, PRIZE):
            with self.subTest(kind=kind):
                form = SalesOrderForm(data=self.post_data(transaction_type=kind, vehicle_price="70000"))
                self.assertTrue(form.is_valid(), form.errors)
                order = form.save()
                self.assertEqual((order.source_type, order.payment_type, order.vehicle_price), ("store", "cash", 0))
                self.assertEqual(order.payment_splits, [{"method": "cash", "amount": 0}])
                self.assertEqual(order.plate_insurance_fee, 2350)   # 牌險照一般規則

    def test_form_rejects_dealer_and_platform_sources(self):
        for kind in (PROXY, PRIZE):
            for source_type, source in (("dealer", self.dealer), ("platform", self.platform)):
                with self.subTest(kind=kind, source_type=source_type):
                    form = SalesOrderForm(data=self.post_data(
                        transaction_type=kind, source_type=source_type, source=str(source.pk)))
                    self.assertFalse(form.is_valid())
                    self.assertIn(NON_PERFORMANCE_SOURCE_ERROR, form.errors["source_type"])

    def test_form_rejects_non_cash_payment(self):
        for method in ("installment", "card"):
            with self.subTest(method=method):
                splits = '[{"method": "%s", "amount": 70000}]' % method
                form = SalesOrderForm(data=self.post_data(transaction_type=PROXY, payment_splits=splits,
                                                          installment_company="測試分期", installment_periods="12",
                                                          installment_monthly="5000"))
                self.assertFalse(form.is_valid())
                self.assertIn(NON_PERFORMANCE_PAYMENT_ERROR, form.errors["payment_splits"])

    def test_form_rejects_commission_recipient(self):
        form = SalesOrderForm(data=self.post_data(
            transaction_type=PROXY, assign_commission_to_other="True", commission_recipient=str(self.dealer.pk)))
        self.assertFalse(form.is_valid())
        self.assertIn(NON_PERFORMANCE_RECIPIENT_ERROR, form.errors["commission_recipient"])

    def test_order_page_cannot_switch_while_recipient_is_assigned(self):
        # 訂單頁的歸屬在頁首另一張表單：沒帶歸屬開關時保留已存的歸屬，錯誤掛在看得到的交易類型欄。
        order = self.make_order(commission_recipient=self.dealer)
        form = SalesOrderForm(data=self.post_data(transaction_type=PROXY), instance=order)
        self.assertFalse(form.is_valid())
        self.assertIn(NON_PERFORMANCE_KEEP_RECIPIENT_ERROR, form.errors["transaction_type"])

    def test_model_clean_enforces_the_same_rules(self):
        cases = (
            (dict(source_type="dealer", source=self.dealer), "source_type"),
            (dict(source_type="platform", source=self.platform), "source_type"),
            (dict(payment_type="installment", installment_company="測試分期", installment_periods=12,
                  installment_monthly=5000), "payment_type"),
            (dict(payment_splits=[{"method": "card", "amount": 0}]), "payment_type"),
            (dict(commission_recipient=self.dealer), "commission_recipient"),
        )
        for kind in (PROXY, PRIZE):
            for extra, field in cases:
                with self.subTest(kind=kind, field=field, extra=sorted(extra)):
                    with self.assertRaises(ValidationError) as caught:
                        self.make_order(kind, **extra)
                    self.assertIn(field, caught.exception.message_dict)
        self.assertEqual(self.make_order(PROXY).commission_attribution_block_reason,
                         "代交車、中獎車不能指定台數與傭金歸屬車行。")

    def test_regular_orders_keep_every_source_payment_and_recipient(self):
        # 一般銷售不受影響：車行、平台、分期、指定歸屬都照舊。
        self.make_order(source_type="dealer", source=self.dealer)
        self.make_order(source_type="platform", source=self.platform)
        self.make_order(commission_recipient=self.dealer)
        self.make_order(payment_type="installment", installment_company="測試分期", installment_periods=12,
                        installment_monthly=5000)
        form = SalesOrderForm(data=self.post_data(source_type="dealer", source=str(self.dealer.pk)))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().vehicle_price, 70000)
        self.assertEqual(self.make_order().commission_attribution_block_reason, "")

    def test_type_can_change_until_the_order_is_closed(self):
        order = self.registered(status="completed", delivered_at=timezone.now())
        self.assertFalse(SalesOrderForm(instance=order).fields["transaction_type"].disabled)
        order.transaction_type = PROXY
        order.vehicle_price = 0
        order.save()                                   # 已交車、未結案：可以改
        order.mark_closed("測試人員")
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertTrue(SalesOrderForm(instance=order).fields["transaction_type"].disabled)
        order.transaction_type = REGULAR
        with self.assertRaises(ValidationError) as caught:
            order.save()
        self.assertIn("transaction_type", caught.exception.message_dict)
        order.transaction_type = PROXY
        order.note = "結案後改其他欄位不受影響"
        order.save()

    def test_imported_prize_order_is_not_restricted(self):
        # 正式站 3 張匯入的中獎車：只改歸類與業績口徑，來源、付款、收支都不回頭檢查。
        order = self.make_order(source_type="dealer", source=self.dealer)
        order = mark_imported(order, "t320-imported-prize")
        SalesOrder.objects.filter(pk=order.pk).update(transaction_type=PRIZE, vehicle_price=65000)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertTrue(order.is_non_performance)
        self.assertFalse(order.zero_vehicle_finance)
        order.note = "匯入單照常存檔"
        order.save()
        self.assertEqual(SalesOrder.objects.get(pk=order.pk).vehicle_price, 65000)

    def test_create_page_offers_the_type_and_explains_it(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("order_create")).content.decode()
        self.assertIn('<option value="proxy_delivery">代交車</option>', page)
        self.assertIn('data-conditional="non-performance" hidden', page)
        self.assertIn("代交車、中獎車：只能是本店訂單，付款固定現金、沒有車價", page)
        self.assertIn("代交車、中獎車不計業績", page)


class FinanceTests(Base):
    """車價收入、車輛成本固定 0、收支標「不適用」、淨利可計入；本店人員傭金不發。"""

    def test_vehicle_income_and_cost_are_zero_and_profit_is_ready(self):
        for kind in (PROXY, PRIZE):
            with self.subTest(kind=kind):
                order = self.make_order(kind)
                profile = self.profile(order)
                self.assertEqual((profile.actual_disbursement, profile.vehicle_cost), (0, 0))
                self.assertIsNone(profile.vehicle_cost_rule)
                self.assertTrue(profile.profit_is_ready)
                # 牌險照一般規則列收入與支出。
                self.assertEqual(profile.registration_tax_income, profile.registration_tax_expense)
                incentives = sum((getattr(profile, name) or 0 for name in profile.INCENTIVE_FIELDS), Decimal("0"))
                self.assertEqual(profile.net_profit, profile.total_income - profile.total_expense + incentives)

    def test_regular_order_finance_is_unchanged(self):
        order = self.make_order()
        profile = self.profile(order)
        self.assertEqual(profile.actual_disbursement, 70000)
        self.assertEqual((profile.vehicle_cost, profile.vehicle_cost_rule), (56000, self.cost_rule))
        self.assertTrue(profile.profit_is_ready)
        # 沒有成本的一般單照舊算「淨利待補」。
        OrderOperationsProfile.objects.filter(pk=profile.pk).update(vehicle_cost=0)
        self.assertFalse(self.profile(order).profit_is_ready)

    def test_registration_lock_keeps_cost_zero(self):
        order = self.make_order(PROXY)
        order.registration_date = TODAY
        profile = apply_order_settlement_cost(order, "測試人員", lock=True)
        self.assertEqual((profile.vehicle_cost, profile.vehicle_cost_rule), (0, None))
        regular = self.make_order()
        regular.registration_date = TODAY
        locked = apply_order_settlement_cost(regular, "測試人員", lock=True)
        self.assertEqual(locked.vehicle_cost, 56000)
        self.assertIsNotNone(locked.vehicle_cost_locked_at)

    def test_switching_type_zeroes_and_restores_finance(self):
        order = self.make_order()
        order.transaction_type = PROXY
        order.vehicle_price = 0
        order.save()
        profile = self.profile(order)
        self.assertEqual((profile.actual_disbursement, profile.vehicle_cost), (0, 0))
        order.transaction_type = REGULAR
        order.vehicle_price = 70000
        order.save()
        profile = self.profile(order)
        self.assertEqual((profile.actual_disbursement, profile.vehicle_cost), (70000, 56000))

    def test_ledger_marks_both_rows_not_applicable(self):
        self.client.force_login(self.admin)
        order = self.make_order(PROXY)
        profile = self.profile(order)
        form = OrderOperationsForm(instance=profile)
        self.assertTrue(form.fields["actual_disbursement"].disabled)
        self.assertTrue(form.fields["vehicle_cost"].disabled)
        blocks = finance_ledger(form, profile)
        rows = {row["name"]: row for block in (blocks["income"], blocks["expense"])
                for group in block["groups"] for row in group["rows"]}
        self.assertTrue(rows["actual_disbursement"]["not_applicable"])
        self.assertTrue(rows["vehicle_cost"]["not_applicable"])
        self.assertFalse(rows["registration_tax_income"]["not_applicable"])
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        for name in ("actual_disbursement", "vehicle_cost"):
            self.assertIn(f'<p class="ledger-row__na" data-ledger-na="{name}">不適用</p>', page)
        # 送出的金額不會寫進這兩欄。
        bound = OrderOperationsForm({"actual_disbursement": "999", "vehicle_cost": "888"}, instance=profile)
        bound.is_valid()
        self.assertEqual((bound.cleaned_data.get("actual_disbursement"), bound.cleaned_data.get("vehicle_cost")), (0, 0))

    def test_regular_ledger_has_no_not_applicable_rows(self):
        self.client.force_login(self.admin)
        order = self.make_order()
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        self.assertNotIn("data-ledger-na", page)
        self.assertIn('name="operations-vehicle_cost"', page)
        profile = self.profile(order)
        blocks = finance_ledger(OrderOperationsForm(instance=profile), profile)
        self.assertFalse(any(row["not_applicable"] for block in (blocks["income"], blocks["expense"])
                             for group in block["groups"] for row in group["rows"]))

    def test_store_staff_commission_is_not_paid(self):
        regular = self.make_order(source=self.staff)
        self.assertEqual(store_staff_commission(regular), 800)
        self.assertEqual(self.profile(regular).dealer_commission_expense, 800)
        for kind in (PROXY, PRIZE):
            with self.subTest(kind=kind):
                order = self.make_order(kind, source=self.staff)
                self.assertEqual(store_staff_commission(order), 0)
                profile = self.profile(order)
                self.assertEqual((profile.dealer_commission_base, profile.dealer_commission_expense), (0, 0))

    def test_locked_staff_commission_is_dropped_when_type_changes_after_registration(self):
        order = self.make_order(source=self.staff)
        apply_order_dealer_commission(order, lock=True)
        self.assertEqual(self.profile(order).dealer_commission_expense, 800)
        SalesOrder.objects.filter(pk=order.pk).update(
            transaction_type=PROXY, vehicle_price=0, registration_date=TODAY, registration_completed_at=timezone.now())
        sync_order_operations(order.pk)
        profile = self.profile(order)
        self.assertEqual((profile.dealer_commission_base, profile.dealer_commission_expense), (0, 0))
        # 一般單的鎖定照舊：之後改人員傭金設定不回頭改。
        regular = self.make_order(source=self.staff)
        apply_order_dealer_commission(regular, lock=True)
        SalesSource.objects.filter(pk=self.staff.pk).update(staff_commission=4000)
        sync_order_operations(regular.pk)
        self.assertEqual(self.profile(regular).dealer_commission_expense, 800)

    def test_imported_prize_order_finance_is_not_zeroed(self):
        # 匯入單（含還沒結案的）：車價收入、車輛成本照原本的規則，不因中獎車歸零，收支也不標「不適用」。
        order = mark_imported(self.make_order(), "t320-imported-finance")
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_cost=50000, vehicle_cost_manual=True)
        SalesOrder.objects.filter(pk=order.pk).update(transaction_type=PRIZE)
        sync_order_operations(order.pk)
        profile = self.profile(order)
        self.assertEqual((profile.actual_disbursement, profile.vehicle_cost), (order.vehicle_price, 50000))
        blocks = finance_ledger(OrderOperationsForm(instance=profile), profile)
        self.assertFalse(any(row["not_applicable"] for block in (blocks["income"], blocks["expense"])
                             for group in block["groups"] for row in group["rows"]))

    def test_imported_prize_order_with_zero_cost_stays_pending_profit(self):
        # 匯入的中獎車舊單成本是 0：照舊列「淨利待補」，不因中獎車變成「可計入」；系統建立的中獎車才算可計入。
        order = mark_imported(self.make_order(), "t320-imported-zero-cost")
        OrderOperationsProfile.objects.filter(order=order).update(vehicle_cost=0, vehicle_cost_manual=True)
        self.assertFalse(self.profile(order).profit_is_ready)
        SalesOrder.objects.filter(pk=order.pk).update(transaction_type=PRIZE)
        sync_order_operations(order.pk)
        profile = self.profile(order)
        self.assertEqual(profile.vehicle_cost, 0)
        self.assertFalse(profile.profit_is_ready)
        self.assertTrue(self.profile(self.make_order(PRIZE)).profit_is_ready)

    def test_imported_prize_order_keeps_store_staff_commission(self):
        # 匯入單的傭金不變：本店人員的匯入單改成中獎車，人員傭金照原本的規則。
        order = mark_imported(self.make_order(source=self.staff), "t320-imported-commission")
        before = self.profile(order)
        self.assertEqual(before.dealer_commission_expense, 800)
        SalesOrder.objects.filter(pk=order.pk).update(transaction_type=PRIZE)
        order = SalesOrder.objects.get(pk=order.pk)
        self.assertEqual(store_staff_commission(order), 800)
        sync_order_operations(order.pk)
        apply_order_dealer_commission(SalesOrder.objects.get(pk=order.pk))
        after = self.profile(order)
        self.assertEqual((after.dealer_commission_base, after.dealer_commission_expense),
                         (before.dealer_commission_base, before.dealer_commission_expense))
        self.assertEqual(after.net_profit, before.net_profit)


class NonPerformanceWorkflowTests(Base):
    """代交車、中獎車照常走作業流程：配車扣庫存、簽署、申請電動車補助。"""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.store = Store.objects.create(name="示範門市", code="T320")

    def test_allocation_reserves_inventory(self):
        for index, kind in enumerate((PROXY, PRIZE)):
            with self.subTest(kind=kind):
                order = self.make_order(kind, status="allocation_pending", accepted_at=timezone.now())
                vehicle = VehicleInventory.objects.create(
                    vehicle_model=self.model, color=self.color, engine_number=f"T320-ALLOC-{index}",
                    ownership_store=self.store, location_store=self.store)
                available = VehicleInventory.objects.filter(status=VehicleInventory.Status.AVAILABLE).count()
                response = self.client.post(reverse("allocate_vehicle", args=[order.pk]), {"vehicle": vehicle.pk})
                self.assertEqual(response.status_code, 302)
                order.refresh_from_db()
                vehicle.refresh_from_db()
                self.assertEqual((order.status, order.allocated_vehicle_id), (SalesOrder.Status.ALLOCATED, vehicle.pk))
                self.assertEqual(vehicle.status, VehicleInventory.Status.RESERVED)
                self.assertEqual(VehicleInventory.objects.filter(status=VehicleInventory.Status.AVAILABLE).count(),
                                 available - 1)
                self.assertTrue(OrderEvent.objects.filter(order=order, event_type="allocated").exists())

    def test_signing_flow_stores_signed_documents(self):
        from sales.tests.test_document_signing import signature_data_url

        for kind in (PROXY, PRIZE):
            with self.subTest(kind=kind):
                order = self.make_order(kind, id_verified=True)
                self.assertTrue(order.needs_customer_signatures)
                page = self.client.get(reverse("order_sign", args=[order.pk]))
                self.assertEqual(page.status_code, 200)
                response = self.client.post(reverse("order_sign", args=[order.pk]), {
                    "documents": ["contract", "privacy"], "signer_name": "合成簽署人", "agree": "1",
                    "signature": signature_data_url(),
                    "fingerprint_contract": order.document_fingerprint("contract"),
                    "fingerprint_privacy": order.document_fingerprint("privacy"),
                })
                self.assertRedirects(response, reverse("order_sign_done", args=[order.pk]))
                order.refresh_from_db()
                self.assertTrue(order.signed_contract_is_electronic)
                self.assertTrue(order.privacy_consent_is_electronic)
                self.assertEqual(order.events.filter(event_type__endswith="_esigned").count(), 2)

    def test_electric_vehicle_subsidy_can_be_applied(self):
        from sales.models import SubsidyItem
        from sales.services.order_steps import order_step_url

        for kind in (PROXY, PRIZE):
            with self.subTest(kind=kind):
                order = self.make_order(kind, vehicle_model=self.ev, color=self.ev_color, id_verified=True)
                response = self.client.post(reverse("subsidy_data_update", args=[order.pk]), {
                    "_order_revision": str(order.revision), "is_trade_in_subsidy": "on",
                    "old_owner_same_as_owner": "on", "trade_in_plate": "ABC-1234", "old_owner_name": "",
                    "old_owner_id_number": "", "subsidy_type": "汰舊換新", "old_vehicle_valuation": "0",
                    "old_vehicle_tax": "0", "change_reason": "申請電動車補助",
                    "subsidy_items-TOTAL_FORMS": "1", "subsidy_items-INITIAL_FORMS": "0",
                    "subsidy_items-MIN_NUM_FORMS": "0", "subsidy_items-MAX_NUM_FORMS": "1000",
                    "subsidy_items-0-category": SubsidyItem.Category.INDUSTRY,
                    "subsidy_items-0-item_name": "電動機車購車補助", "subsidy_items-0-expected_amount": "7000",
                    "subsidy_items-0-applied_on": "2026-11-05", "subsidy_items-0-status": SubsidyItem.Status.SUBMITTED,
                    "subsidy_items-0-note": "",
                })
                self.assertRedirects(response, order_step_url(order.pk, "subsidy"))
                item = order.subsidy_items.get()
                self.assertEqual((item.category, item.expected_amount), (SubsidyItem.Category.INDUSTRY, 7000))
                profile = self.profile(order)
                self.assertEqual((profile.subsidy_amount, profile.subsidy_applied_on), (7000, date(2026, 11, 5)))
                # 申請補助不會讓車價收入、車輛成本離開 0。
                self.assertEqual((profile.actual_disbursement, profile.vehicle_cost), (0, 0))


class ReportTests(Base):
    """報表中心「銷售來源」：代交車、中獎車各自成一類，優先於其他五類；平均車價不算這兩類。"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.expo = SalesSource.objects.create(name="展場", source_type="store")
        cls.config = {**initial_config(), "audience": "team", "include_records": True}
        ReportDefinition.objects.create(draft=cls.config, published=cls.config, version=1)

    def setUp(self):
        super().setUp()
        plan = [
            ("store", None, 10, REGULAR), ("store", self.staff, 10, REGULAR), ("store", self.expo, 10, REGULAR),
            ("dealer", self.dealer, 10, REGULAR), ("platform", self.platform, 10, REGULAR),
            ("store", self.staff, 11, PROXY), ("store", self.expo, 11, PROXY), ("store", None, 11, PRIZE),
            ("store", None, 11, REGULAR),
        ]
        self.orders = [
            self.make_order(kind, source_type=source_type, source=source, order_date=date(2026, month, 1),
                            registration_date=date(2026, month, 3), registration_completed_at=timezone.now(),
                            status="completed")
            for source_type, source, month, kind in plan]

    def classify(self, queryset):
        return dict(sales_source_query(queryset).annotate(cls=sales_source_expression()).values_list("pk", "cls"))

    def card(self, **kwargs):
        return {**self.config["cards"][0], **kwargs}

    def test_classification_takes_priority_over_the_other_five(self):
        result = self.classify(SalesOrder.objects.all())
        expected = ["馭盛", "店內員工", "展場", "車行", "網路平台", "代交車", "代交車", "中獎車", "馭盛"]
        self.assertEqual([result[order.pk] for order in self.orders], expected)
        # 匯入的中獎車舊單（車行來源也一樣）歸「中獎車」。
        imported = mark_imported(self.make_order(source_type="dealer", source=self.dealer), "t320-report-prize")
        SalesOrder.objects.filter(pk=imported.pk).update(transaction_type=PRIZE)
        self.assertEqual(self.classify(SalesOrder.objects.filter(pk=imported.pk))[imported.pk], "中獎車")

    def test_other_orders_classify_the_same_as_before(self):
        regular = [order.pk for order in self.orders if not order.is_non_performance]
        before = self.classify(SalesOrder.objects.filter(pk__in=regular))
        SalesOrder.objects.exclude(pk__in=regular).update(transaction_type=REGULAR)
        self.assertEqual(self.classify(SalesOrder.objects.filter(pk__in=regular)), before)
        # 改回一般交易類型就回到原本的 T-183 歸類。
        restored = self.classify(SalesOrder.objects.all())
        self.assertEqual([restored[order.pk] for order in self.orders[5:8]], ["店內員工", "展場", "馭盛"])

    def test_filter_choices_and_fixed_colours(self):
        self.assertEqual(SOURCE_CLASSIFICATIONS, ("馭盛", "網路平台", "店內員工", "展場", "車行", "代交車", "中獎車"))
        form = FilterForm(config=self.config)
        for label in ("代交車", "中獎車"):
            self.assertIn((label, label), form.fields["legacy_source"].choices)
        bound = FilterForm({"legacy_source": ["代交車"]}, config=self.config)
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertEqual(base_query(self.config, bound.cleaned_data).count(), 2)
        # 每一類各一個固定色、互不相同，也不和中性灰相同；不隨名次換色。
        colors = {label: dimension_color("legacy_sales_source", label, index)
                  for index, label in enumerate(SOURCE_CLASSIFICATIONS)}
        self.assertEqual(len(set(colors.values())), len(colors))
        self.assertNotIn("var(--chart-other)", colors.values())
        self.assertEqual(colors["代交車"], PALETTE[FIXED_COLOR_SLOTS["代交車"]])
        self.assertEqual(colors["中獎車"], FIXED_COLOR_VARS["中獎車"])
        self.assertEqual(dimension_color("legacy_sales_source", "中獎車", 0), dimension_color("legacy_sales_source", "中獎車", 5))
        for label in ("車行", "馭盛", "網路平台", "店內員工", "展場"):     # 既有五類的顏色不變
            self.assertEqual(colors[label], PALETTE[("車行", "馭盛", "網路平台", "店內員工", "展場").index(label)])

    def test_python_and_frontend_colours_agree(self):
        script = (Path(settings.BASE_DIR) / "static/js/report-interactions.js").read_text(encoding="utf-8")
        slots = dict(re.findall(r"'([^']+)':(\d+)", re.search(r"REPORT_FIXED_SLOTS = \{([^}]*)\}", script).group(1)))
        fixed = dict(re.findall(r"'([^']+)':'([^']+)'", re.search(r"REPORT_FIXED_COLORS = \{([^}]*)\}", script).group(1)))
        for label in SOURCE_CLASSIFICATIONS:
            if label in FIXED_COLOR_VARS:
                self.assertEqual(fixed[label], FIXED_COLOR_VARS[label], label)
            else:
                self.assertEqual(int(slots[label]), FIXED_COLOR_SLOTS[label], label)
            self.assertTrue(fixed_color(label), label)
        # 新的固定色在淺色、深色、跟隨系統三組主題都有定義。
        css = (Path(settings.BASE_DIR) / "static/css/app.css").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"--chart-prize:\s*#[0-9a-f]{6};", css)), 3)

    def test_pie_stack_drill_and_records_agree(self):
        pie = card_result(self.config, self.card(chart="donut", dimension="legacy_sales_source"), {})
        counts = {row["label"]: row["count"] for row in pie["rows"]}
        self.assertEqual(counts, {"馭盛": 2, "店內員工": 1, "展場": 1, "車行": 1, "網路平台": 1, "代交車": 2, "中獎車": 1})
        self.assertEqual(sum(counts.values()), pie["count"])
        self.assertEqual(pie["count"], SalesOrder.objects.count())
        for label, expected in (("代交車", self.orders[5:7]), ("中獎車", self.orders[7:8])):
            row = next(row for row in pie["rows"] if row["label"] == label)
            drilled = drill_query(self.config, self.card(chart="donut", dimension="legacy_sales_source"), {}, row["key"])
            self.assertEqual(set(drilled.values_list("pk", flat=True)), {order.pk for order in expected})

        stack_card = self.card(chart="stacked", dimension="month", series="legacy_sales_source")
        stack = card_result(self.config, stack_card, {})
        legend = {item["label"]: item["color"] for item in stack["series_legend"]}
        self.assertEqual(legend, {row["label"]: row["color"] for row in pie["rows"]})
        for row in stack["rows"]:
            self.assertEqual(sum(segment["count"] for segment in row["segments"]), row["count"])
        november = next(row for row in stack["rows"] if any(s["label"] == "代交車" for s in row["segments"]))
        for label, expected in (("代交車", 2), ("中獎車", 1)):
            segment = next(s for s in november["segments"] if s["label"] == label)
            self.assertEqual(segment["count"], expected)
            self.assertEqual(drill_query(self.config, stack_card, {}, segment["key"]).count(), expected)

        records = record_context({**self.config, "records_columns": ["legacy_sales_source"]}, {})
        values = {row["pk"]: row["cells"][0]["value"] for row in records["records_rows"]}
        self.assertEqual([values[order.pk] for order in self.orders[5:8]], ["代交車", "代交車", "中獎車"])
        self.assertEqual(len(values), pie["count"])

    def test_average_price_leaves_out_both_kinds(self):
        card = self.card(chart="bar", dimension="legacy_sales_source", metric="average_price")
        result = card_result(self.config, card, {})
        self.assertEqual(result["total"], "70,000")
        rows = {row["label"]: row for row in result["rows"]}
        self.assertEqual(rows["馭盛"]["display"], "70,000")
        self.assertEqual(rows["代交車"]["count"], 2)                  # 台數照列；沒有車價，不拉低整體平均
        # 台數、車價合計照列全部訂單。
        count_card = self.card(chart="bar", dimension="legacy_sales_source", metric="count")
        self.assertEqual(card_result(self.config, count_card, {})["count"], 9)
        total_card = self.card(chart="bar", dimension="legacy_sales_source", metric="sale_total")
        self.assertEqual(card_result(self.config, total_card, {})["total"], "420,000")
        # 有車價的中獎車（例如匯入單）也不算進平均。
        SalesOrder.objects.filter(pk=self.orders[7].pk).update(vehicle_price=1000)
        self.assertEqual(card_result(self.config, card, {})["total"], "70,000")

    def test_old_source_type_links_leave_out_both_kinds(self):
        form = FilterForm(QueryDict("source_type=store"), config=self.config)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(base_query(self.config, form.cleaned_data).count(),
                         performance_orders(SalesOrder.objects.filter(source_type="store")).count())


class CockpitTests(Base):
    """營運總表 A：主數字只算計入業績的單，代交車、中獎車寫在副標（0 時不顯示），和明細張數對得上。"""

    def seed(self):
        self.r1 = self.registered(day=TODAY - timedelta(days=3))
        self.r2 = self.registered(day=TODAY - timedelta(days=5), source_type="dealer", source=self.dealer)
        self.p1 = self.registered(PROXY, day=TODAY - timedelta(days=2))
        self.p2 = self.registered(PROXY, day=TODAY - timedelta(days=4), vehicle_model=self.ev, color=self.ev_color)
        self.z1 = self.registered(PRIZE, day=TODAY - timedelta(days=6))
        self.pending_regular = self.make_order(status="allocation_pending", established_on=TODAY - timedelta(days=1))
        self.pending_proxy = self.make_order(PROXY, status="allocation_pending", established_on=TODAY - timedelta(days=1))
        cache.clear()

    def view(self, user=None):
        self.client.force_login(user or self.admin)
        response = self.client.get(reverse("operations_report"), {"period": "month", "refresh": "1"})
        self.assertEqual(response.status_code, 200)
        return response

    def listed(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.context["page_obj"].paginator.count

    def test_main_numbers_leave_out_both_kinds(self):
        self.seed()
        data = operations_cockpit.build("month", TODAY)
        pulse = data["pulse"]
        self.assertEqual(pulse["count"]["value"], 2)
        self.assertEqual(pulse["sales"]["value"], 140000)
        regular_profit = sum(self.profile(order).net_profit for order in (self.r1, self.r2))
        self.assertEqual(pulse["profit"]["value"], regular_profit)
        self.assertEqual((pulse["profit"]["ready"], pulse["profit"]["count"], pulse["profit"]["pending"]), (2, 2, 0))
        self.assertEqual(pulse["new_orders"]["value"], 3)             # r1、r2、待配車的一般單
        # 走勢、結構、車型貢獻、油電已領牌同口徑。
        self.assertEqual(data["trend"]["series"]["count"]["points"][-1]["this"], 2)
        self.assertEqual(data["mix"]["source"]["rows"][0]["total"], 2)
        self.assertEqual(sum(row["current"] for row in data["movers"]), 2)
        self.assertEqual(data["energy"]["registered"], 2)
        metrics = build_dashboard_metrics(TODAY)
        self.assertEqual(metrics["performance"]["count"], 2)
        self.assertEqual({order.pk for order in metrics["non_performance_orders"]}, {self.p1.pk, self.p2.pk, self.z1.pk})

    def test_regular_only_numbers_are_identical_with_and_without_the_other_kinds(self):
        # 一般銷售不受影響：加入代交車、中獎車前後，業績數字完全相同。
        self.r1 = self.registered(day=TODAY - timedelta(days=3))
        self.r2 = self.registered(day=TODAY - timedelta(days=5), source_type="dealer", source=self.dealer)
        self.make_order(status="allocation_pending", established_on=TODAY - timedelta(days=1))
        keys = ("value", "previous", "last_year")

        def snapshot():
            data = operations_cockpit.build("month", TODAY)
            return ({name: {key: data["pulse"][name][key] for key in keys} for name in ("count", "sales", "profit", "new_orders")},
                    data["mix"], data["movers"], data["energy"]["registered"],
                    [row["this"] for row in data["trend"]["series"]["count"]["points"]])

        before = snapshot()
        self.assertIsNone(operations_cockpit.build("month", TODAY)["pulse"]["count"]["aside"])
        self.registered(PROXY, day=TODAY - timedelta(days=2))
        self.registered(PRIZE, day=TODAY - timedelta(days=6))
        self.make_order(PROXY, status="allocation_pending", established_on=TODAY)
        self.assertEqual(snapshot(), before)

    def test_asides_only_appear_when_there_is_something_to_say(self):
        self.registered(day=TODAY - timedelta(days=3))
        with self.settings():
            page = self.view().content.decode()
        self.assertNotIn("ops-aside__text", page)
        self.assertNotIn('data-ops-aside="mix"', page)
        self.assertNotIn('data-ops-aside="stock"', page)
        self.assertNotIn("ops-track__aside", page)
        self.assertNotIn("ops-energy__aside", page)
        # 每個數字都能點開看怎麼算（沒有這兩類時說明寫「本期沒有」）。
        self.assertEqual(page.count("data-ops-how"), 4)
        self.assertIn("代交車、中獎車（不計業績）；本期沒有", page)

    def test_asides_and_explanations_match_the_order_list(self):
        self.seed()
        with self.settings():
            response = self.view()
        page = response.content.decode()
        pulse = response.context["cockpit"]["pulse"]
        today_text = "2026" if TODAY else ""
        self.assertTrue(today_text)
        count = pulse["count"]
        self.assertEqual([(kind["key"], kind["count"]) for kind in count["aside"]["items"]],
                         [("proxy_delivery", 2), ("prize", 1)])
        self.assertIn("另有 ", page)
        self.assertIn("代交車 2 台</a>・", page)
        self.assertIn("中獎車 1 台</a>（不計業績）", page)
        self.assertIn("不含代交車、中獎車（這兩種沒有車價）", page)
        self.assertIn("計入 2 台＋代交車 2 台＋中獎車 1 台＝本期領牌 5 張", page)
        # 主數字與副標點進全部訂單，張數相同。
        links = {link["label"]: link["url"] for link in count["how"]["links"]}
        self.assertEqual(self.listed(links["看這 2 台"]), 2)
        self.assertEqual(self.listed(links["看代交車 2 台"]), 2)
        self.assertEqual(self.listed(links["看中獎車 1 台"]), 1)
        for kind in count["aside"]["items"]:
            self.assertEqual(self.listed(kind["url"]), kind["count"])
            self.assertIn(kind["url"].replace("&", "&amp;"), page)
        # 淨利：代交車、中獎車的牌險配件損益另計。
        aside_profit = sum(self.profile(order).net_profit for order in (self.p1, self.p2, self.z1))
        self.assertEqual(pulse["profit"]["aside"]["items"][0]["text"], operations_cockpit._signed_money(aside_profit))
        self.assertIn("代交車／中獎車 牌險配件損益 ", page)
        self.assertIn("；另計 3 筆 ", page)
        # 新成立訂單：主數字連結與副標都對得上。
        new_orders = pulse["new_orders"]
        self.assertEqual(self.listed(new_orders["url"]), new_orders["value"])
        self.assertEqual([(kind["key"], kind["count"]) for kind in new_orders["aside"]["items"]],
                         [("proxy_delivery", 3), ("prize", 1)])
        for kind in new_orders["aside"]["items"]:
            self.assertEqual(self.listed(kind["url"]), kind["count"])
        self.assertIn("計入 3 張＋代交車 3 張＋中獎車 1 張＝本期成立 7 張", page)
        self.assertIn("交易類型「計入業績的訂單（不含代交車、中獎車）」", self.client.get(new_orders["url"]).content.decode())

    def test_flow_and_pending_registration_count_them_with_a_note(self):
        self.seed()
        response = self.view()
        cockpit = response.context["cockpit"]
        stage = next(stage for stage in cockpit["flow"]["stages"] if stage["key"] == "allocation_pending")
        self.assertEqual(stage["count"], 2)                           # 照實際作業計入
        self.assertEqual([(kind["key"], kind["count"]) for kind in stage["aside"]], [("proxy_delivery", 1)])
        self.assertEqual(self.listed(stage["aside"][0]["url"]), 1)
        self.assertEqual(self.listed(stage["url"]), 2)
        gas = next(row for row in cockpit["energy"]["rows"] if row["key"] == "gas")
        electric = next(row for row in cockpit["energy"]["rows"] if row["key"] == "electric")
        self.assertEqual((gas["registered"], gas["pending"]), (2, 2))
        self.assertEqual([(kind["key"], kind["count"]) for kind in gas["registered_aside"]],
                         [("proxy_delivery", 1), ("prize", 1)])
        self.assertEqual(self.listed(gas["registered_url"]), gas["registered"])
        for kind in gas["registered_aside"]:
            self.assertEqual(self.listed(kind["url"]), kind["count"])
        self.assertEqual([(kind["key"], kind["count"]) for kind in gas["pending_aside"]], [("proxy_delivery", 1)])
        self.assertEqual((electric["registered"], [kind["count"] for kind in electric["registered_aside"]]), (0, [1]))
        page = response.content.decode()
        self.assertIn('data-ops-aside="flow-allocation_pending">含 ', page)
        self.assertIn('data-ops-aside="energy-registered-gas">另有 ', page)
        self.assertIn('data-ops-aside="energy-pending-gas">含 <b>代交車 1 張</b>', page)
        self.assertIn('data-ops-aside="mix">本期不含 ', page)
        self.assertEqual(self.listed(cockpit["non_performance_aside"]["items"][0]["url"]), 2)

    def test_money_risks_still_include_them(self):
        # 款項類照實際作業：客人仍要付牌險、配件。
        order = self.make_order(PROXY, status="delivered_docs_pending", delivered_at=timezone.now(),
                                registration_date=TODAY, registration_completed_at=timezone.now())
        self.assertGreater(order.calculate_balance(), 0)
        data = operations_cockpit.build("month", TODAY)
        self.assertEqual(data["money"]["unsettled_count"], 1)
        self.assertEqual(data["pulse"]["count"]["value"], 0)

    def test_velocity_shortage_and_slow_ignore_them(self):
        store = Store.objects.get_or_create(code="T320", defaults={"name": "T320 測試店"})[0]

        def stock(number, received_on):
            return VehicleInventory.objects.create(
                vehicle_model=self.model, color=self.color, engine_number=f"ENG-T320-{number:04d}",
                ownership_store=store, location_store=store, status="available", received_on=received_on)

        stock(1, TODAY - timedelta(days=120))
        for offset in range(7):
            self.registered(PROXY, day=TODAY - timedelta(days=10 + offset))
        rows, excluded = operations_cockpit._model_velocity(TODAY)
        row = next(row for row in rows if row["model_id"] == self.model.pk)
        self.assertEqual((row["sold"], row["on_hand"], row["shortage"]), (0, 1, False))
        self.assertTrue(row["slow"])                                  # 代交車領牌不算「賣出」，照樣是滯銷
        self.assertEqual(excluded, 7)
        self.assertEqual(operations_cockpit.model_velocity(TODAY), rows)
        # 同樣台數的一般銷售照舊算賣速（近 90 天 7 台、在庫 1 台＝可銷約 13 天＝缺貨風險、不是滯銷）。
        for offset in range(7):
            self.registered(day=TODAY - timedelta(days=10 + offset))
        rows, excluded = operations_cockpit._model_velocity(TODAY)
        row = next(row for row in rows if row["model_id"] == self.model.pk)
        self.assertEqual((row["sold"], row["shortage"], row["slow"]), (7, True, False))
        self.assertEqual(excluded, 7)

    def test_viewer_without_order_list_gets_text_without_links(self):
        self.seed()
        user = get_user_model().objects.create_user("t320-ops-only", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        for key in ("operations", "dashboard"):
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True)
        response = self.view(user)
        page = response.content.decode()
        self.assertIn("<b>代交車 2 台</b>", page)
        self.assertNotIn("txn=", page)
        self.assertNotIn("ops-how__links", page)


class OrderListAndExportTests(Base):
    def test_txn_filter_scopes(self):
        regular, proxy, prize = self.make_order(), self.make_order(PROXY), self.make_order(PRIZE)
        rows = SalesOrder.objects.all()
        expected = {"performance": {regular.pk}, "non_performance": {proxy.pk, prize.pk},
                    "proxy_delivery": {proxy.pk}, "prize": {prize.pk}}
        for key, pks in expected.items():
            self.assertEqual(set(filter_order_analysis(rows, {"txn": key}).values_list("pk", flat=True)), pks, key)
        everything = {regular.pk, proxy.pk, prize.pk}
        self.assertEqual(set(filter_order_analysis(rows, {}).values_list("pk", flat=True)), everything)
        self.assertEqual(set(filter_order_analysis(rows, {"txn": "unknown"}).values_list("pk", flat=True)), everything)

    def test_order_list_shows_the_applied_scope_and_all_matching_orders(self):
        self.make_order()
        self.make_order(PROXY, status="completed", delivered_at=timezone.now())
        self.client.force_login(self.admin)
        response = self.client.get(reverse("order_list"), {"txn": "proxy_delivery"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "交易類型「代交車」")
        self.assertContains(response, '<input type="hidden" name="txn" value="proxy_delivery">')

    def test_export_has_transaction_type_by_default(self):
        column = export_columns.COLUMN_BY_KEY["transaction_type"]
        self.assertEqual((column.label, column.editable), ("交易類型", False))
        self.assertEqual(column.getter(self.make_order(PROXY)), "代交車")
        self.assertEqual(column.getter(self.make_order(PRIZE)), "中獎車")
        self.assertEqual(column.getter(self.make_order()), "一般新車")
        selection = export_columns.default_selection({"finance", "profit", "payout_account"})
        self.assertEqual(selection[:92], list(export_columns.DEFAULT_COLUMNS))     # 舊匯出 92 欄的順序不變
        self.assertEqual(selection[92:], ["transaction_type"])
        resolved = [column.key for column in export_columns.resolve(selection, {"finance", "profit", "payout_account"})]
        self.assertEqual(resolved[-1], "transaction_type")


class ConvertCommandTests(Base):
    """convert_proxy_delivery_orders：來源名稱「代交車」的本店單轉成交易類型代交車。"""

    def run_command(self, *args):
        out = StringIO()
        call_command("convert_proxy_delivery_orders", *args, stdout=out)
        return out.getvalue()

    def legacy_proxy(self, **kwargs):
        """轉換前的記法：本店來源「代交車」、一般新車、車價 0、成本人工改 0。"""
        kwargs.setdefault("vehicle_price", Decimal("0"))
        order = self.make_order(source=self.proxy_source, **kwargs)
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=0, vehicle_cost=0, vehicle_cost_rule=None, vehicle_cost_manual=True,
            manual_financial_fields=["vehicle_cost"])
        return order

    def state(self):
        return (list(SalesOrder.objects.order_by("pk").values_list("pk", "transaction_type", "updated_at")),
                list(OrderOperationsProfile.objects.order_by("pk").values_list(
                    "pk", "actual_disbursement", "vehicle_cost", "vehicle_cost_manual", "updated_at")),
                OrderChange.objects.count(), OrderEvent.objects.count())

    def test_dry_run_lists_before_and_after_without_writing(self):
        order = self.legacy_proxy()
        self.make_order()                                             # 其他本店單不在範圍
        before = self.state()
        output = self.run_command()
        self.assertEqual(self.state(), before)
        self.assertIn("要轉 1 張；已是代交車 0 張；Excel 匯入單 0 張（不動）", output)
        self.assertIn(order.number, output)
        for label in ("車價收入 0→0", "車輛成本 0→0", "淨利 ", "應收 ", "金額不變"):
            self.assertIn(label, output)
        self.assertIn("dry-run：未寫入", output)
        self.assertNotIn("合成車主", output)                          # 只列單號，不列個資
        self.assertNotIn("83739807", output)

    def test_apply_converts_only_target_orders_and_can_rerun(self):
        target = self.legacy_proxy()
        closed = self.legacy_proxy(status="completed", delivered_at=timezone.now(), registration_date=TODAY,
                                   registration_completed_at=timezone.now())
        closed.mark_closed("測試人員")
        other_store = self.make_order(source=self.staff)
        dealer_order = self.make_order(source_type="dealer", source=self.dealer)
        figures = {order.pk: (self.profile(order).net_profit, order.calculate_balance()) for order in (target, closed)}
        output = self.run_command("--apply")
        self.assertIn("已轉換 2 張；略過 0 張。", output)
        for order in (target, closed):
            fresh = SalesOrder.objects.get(pk=order.pk)
            self.assertEqual(fresh.transaction_type, PROXY)
            profile = self.profile(fresh)
            self.assertEqual((profile.actual_disbursement, profile.vehicle_cost, profile.vehicle_cost_manual), (0, 0, False))
            self.assertTrue(profile.profit_is_ready)
            self.assertEqual((profile.net_profit, fresh.calculate_balance()), figures[order.pk])
            change = OrderChange.objects.get(order=fresh, reason__contains="代交車")
            self.assertEqual(change.changes, {"交易類型": {"before": "一般新車", "after": "代交車"}})
            self.assertEqual(OrderEvent.objects.filter(order=fresh, event_type="transaction_type_converted").count(), 1)
        self.assertIsNotNone(SalesOrder.objects.get(pk=closed.pk).closed_at)
        for order in (other_store, dealer_order):
            self.assertEqual(SalesOrder.objects.get(pk=order.pk).transaction_type, REGULAR)
        # 重跑不重複寫入。
        before = self.state()
        output = self.run_command("--apply")
        self.assertIn("要轉 0 張；已是代交車 2 張", output)
        self.assertEqual(self.state(), before)

    def test_imported_orders_are_left_alone(self):
        imported = mark_imported(self.legacy_proxy(), "t320-command-imported")
        before = self.state()
        output = self.run_command("--apply")
        self.assertIn("要轉 0 張；已是代交車 0 張；Excel 匯入單 1 張（不動）", output)
        self.assertEqual(self.state(), before)
        self.assertEqual(SalesOrder.objects.get(pk=imported.pk).transaction_type, REGULAR)

    def test_orders_that_cannot_be_non_performance_are_skipped_with_a_reason(self):
        priced = self.make_order(source=self.proxy_source)             # 車價 70,000
        assigned = self.legacy_proxy(commission_recipient=self.dealer)
        fine = self.legacy_proxy()
        output = self.run_command("--apply")
        self.assertIn(f"{priced.number}（待配車）｜不能轉：車價不是 0", output)
        self.assertIn(f"{assigned.number}（待配車）｜不能轉：已指定台數與傭金歸屬車行", output)
        self.assertIn("已轉換 1 張；略過 2 張。", output)
        self.assertEqual(SalesOrder.objects.get(pk=fine.pk).transaction_type, PROXY)
        for order in (priced, assigned):
            self.assertEqual(SalesOrder.objects.get(pk=order.pk).transaction_type, REGULAR)

    def test_finance_changes_stop_the_whole_run_until_accepted(self):
        changing = self.make_order(source=self.proxy_source, vehicle_price=Decimal("0"))   # 成本照車型帶 56,000
        self.assertEqual(self.profile(changing).vehicle_cost, 56000)
        fine = self.legacy_proxy()
        output = self.run_command()
        self.assertIn("車輛成本 56,000→0", output)
        self.assertIn("※金額有變動", output)
        before = self.state()
        with self.assertRaises(CommandError) as caught:
            self.run_command("--apply")
        self.assertIn("沒有寫入任何一張", str(caught.exception))
        self.assertEqual(self.state(), before)
        self.assertEqual(SalesOrder.objects.get(pk=fine.pk).transaction_type, REGULAR)
        self.run_command("--apply", "--accept-changes")
        self.assertEqual(self.profile(changing).vehicle_cost, 0)
        self.assertEqual(SalesOrder.objects.filter(transaction_type=PROXY).count(), 2)

    def test_order_option_limits_the_run(self):
        first, second = self.legacy_proxy(), self.legacy_proxy()
        self.run_command("--apply", "--order", first.number)
        self.assertEqual(SalesOrder.objects.get(pk=first.pk).transaction_type, PROXY)
        self.assertEqual(SalesOrder.objects.get(pk=second.pk).transaction_type, REGULAR)

    def test_to_convert_count_only_includes_orders_that_will_convert(self):
        self.make_order(source=self.proxy_source)                       # 車價 70,000，不能轉
        self.legacy_proxy(commission_recipient=self.dealer)             # 已指定歸屬，不能轉
        self.legacy_proxy()
        for args in ((), ("--apply",)):
            with self.subTest(args=args):
                output = self.run_command(*args)
                self.assertIn("要轉 1 張；已是代交車 0 張；Excel 匯入單 0 張（不動）；不能轉 2 張（略過）", output)
        self.assertIn("要轉 0 張；已是代交車 1 張；Excel 匯入單 0 張（不動）；不能轉 2 張（略過）", self.run_command())

    def test_apply_is_one_transaction(self):
        # 轉到一半出錯：前面已轉的單也一起復原，一張都不寫入。
        from unittest import mock

        from sales.management.commands import convert_proxy_delivery_orders as command

        first, second = self.legacy_proxy(), self.legacy_proxy()
        real_convert = command._convert

        def failing(order, write_audit):
            if write_audit and order.pk == second.pk:
                raise RuntimeError("模擬寫入失敗")
            return real_convert(order, write_audit)

        before = self.state()
        with mock.patch.object(command, "_convert", side_effect=failing):
            with self.assertRaises(RuntimeError):
                self.run_command("--apply")
        self.assertEqual(self.state(), before)
        for order in (first, second):
            self.assertEqual(SalesOrder.objects.get(pk=order.pk).transaction_type, REGULAR)

    def test_apply_locks_only_the_target_orders(self):
        # 目標單查詢有接來源與匯入快照（可空的外部連接）：PostgreSQL 上只鎖訂單本身（FOR UPDATE OF），不會 500。
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.legacy_proxy()
        with CaptureQueriesContext(connection) as captured:
            output = self.run_command("--apply")
        self.assertIn("已轉換 1 張；略過 0 張。", output)
        if connection.features.has_select_for_update_of:
            targets = [query["sql"] for query in captured.captured_queries
                       if "FOR UPDATE" in query["sql"] and '"sales_salessource"' in query["sql"]]
            self.assertEqual(len(targets), 1, targets)
            self.assertRegex(targets[0], r'FOR UPDATE OF "sales_salesorder"\s*$')


class RevertCommandTests(Base):
    """convert_proxy_delivery_orders --revert：退回 2.41.1 前，把交易類型「代交車」的單改回一般新車。"""

    run_command = ConvertCommandTests.run_command
    state = ConvertCommandTests.state

    def proxies(self):
        system = self.make_order(PROXY)
        closed = self.make_order(PROXY, status="completed", delivered_at=timezone.now(), registration_date=TODAY,
                                 registration_completed_at=timezone.now())
        closed.mark_closed("測試人員")
        imported = mark_imported(self.make_order(), "t320-revert-imported")
        SalesOrder.objects.filter(pk=imported.pk).update(transaction_type=PROXY)
        return system, closed, imported

    def test_dry_run_lists_order_numbers_without_writing(self):
        orders = self.proxies()
        self.make_order(PRIZE)
        before = self.state()
        output = self.run_command("--revert")
        self.assertEqual(self.state(), before)
        self.assertIn("要改回一般新車 3 張", output)
        for order in orders:
            self.assertIn(f"{order.number}（", output)
        self.assertIn("dry-run：未寫入", output)
        self.assertNotIn("合成車主", output)                          # 只列單號，不列個資
        self.assertNotIn("83739807", output)

    def test_apply_reverts_every_proxy_order_and_can_rerun(self):
        orders = self.proxies()
        prize, regular = self.make_order(PRIZE), self.make_order()
        figures = {order.pk: (self.profile(order).net_profit, self.profile(order).vehicle_cost) for order in orders}
        output = self.run_command("--revert", "--apply")
        self.assertIn("已改回 3 張。", output)
        for order in orders:
            fresh = SalesOrder.objects.get(pk=order.pk)
            self.assertEqual(fresh.transaction_type, "regular_new")          # 2.41.1 認得的值
            self.assertEqual((self.profile(fresh).net_profit, self.profile(fresh).vehicle_cost), figures[order.pk])
            change = OrderChange.objects.get(order=fresh, reason__contains="退回 2.41.1")
            expected = {"交易類型": {"before": "代交車", "after": "一般新車"}}
            if order.pk != orders[2].pk:                                  # 系統建立的單：成本釘成人工 0
                expected["車輛成本"] = {"before": "0", "after": "0（人工調整）"}
            self.assertEqual(change.changes, expected)
            self.assertEqual(OrderEvent.objects.filter(order=fresh, event_type="transaction_type_reverted").count(), 1)
        self.assertIsNotNone(SalesOrder.objects.get(pk=orders[1].pk).closed_at)
        self.assertEqual(SalesOrder.objects.get(pk=prize.pk).transaction_type, PRIZE)   # 中獎車 2.41.1 本來就有
        self.assertEqual(SalesOrder.objects.get(pk=regular.pk).transaction_type, REGULAR)
        self.assertFalse(SalesOrder.objects.filter(transaction_type=PROXY).exists())
        before = self.state()
        self.assertIn("要改回一般新車 0 張", self.run_command("--revert", "--apply"))
        self.assertEqual(self.state(), before)

    def test_reverted_cost_is_manual_zero_and_survives_resync(self):
        # 2.41.1 把它們當一般新車重新同步：成本是人工調整的 0，不會依車型帶回 56,000；車價收入維持 0。
        pending = self.make_order(PROXY)                                 # 未領牌：一般單會帶預估成本
        registered = self.make_order(PROXY, registration_date=TODAY, established_on=TODAY)   # 已領牌、成本未鎖
        self.run_command("--revert", "--apply")
        for order in (pending, registered):
            profile = self.profile(order)
            self.assertEqual((profile.vehicle_cost, profile.vehicle_cost_manual), (0, True))
            self.assertIn("vehicle_cost", profile.manual_financial_fields)
            self.assertIsNone(profile.vehicle_cost_rule)
            fresh = SalesOrder.objects.get(pk=order.pk)
            fresh.save()                                                  # 一般存檔會重新同步收支
            sync_order_operations(order.pk)
            apply_order_settlement_cost(SalesOrder.objects.get(pk=order.pk), "測試人員", lock=True)   # 領牌完成鎖成本
            profile = self.profile(order)
            self.assertEqual((profile.vehicle_cost, profile.actual_disbursement), (0, 0))
        # 對照：沒釘成人工的一般單，同步後會帶車型成本。
        control = self.make_order(vehicle_price=Decimal("0"))
        self.assertEqual(self.profile(control).vehicle_cost, 56000)

    def test_dry_run_shows_cost_before_after_and_flags_staff_commission(self):
        staff_order = self.make_order(PROXY, source=self.staff)           # 本店人員設了 800 傭金
        plain = self.make_order(PROXY)
        imported = mark_imported(self.make_order(), "t320-revert-cost")
        SalesOrder.objects.filter(pk=imported.pk).update(transaction_type=PROXY)
        self.assertEqual(self.profile(staff_order).dealer_commission_expense, 0)
        output = self.run_command("--revert")
        lines = {order.pk: next(line for line in output.splitlines() if order.number in line)
                 for order in (staff_order, plain, imported)}
        self.assertIn("車輛成本 0→0（人工調整）｜※退版後可能產生人員傭金 800", lines[staff_order.pk])
        self.assertIn("車輛成本 0→0（人工調整）", lines[plain.pk])
        self.assertNotIn("人員傭金", lines[plain.pk])
        self.assertIn("車輛成本 56,000→56,000（Excel 匯入單，不動）", lines[imported.pk])
        # 匯入單 --apply 後成本照舊、不改成人工。
        self.run_command("--revert", "--apply")
        profile = self.profile(imported)
        self.assertEqual((profile.vehicle_cost, profile.vehicle_cost_manual), (56000, False))

    def test_order_option_limits_the_revert(self):
        first, second = self.make_order(PROXY), self.make_order(PROXY)
        self.run_command("--revert", "--apply", "--order", first.number)
        self.assertEqual(SalesOrder.objects.get(pk=first.pk).transaction_type, REGULAR)
        self.assertEqual(SalesOrder.objects.get(pk=second.pk).transaction_type, PROXY)

    def test_revert_apply_is_one_transaction(self):
        from unittest import mock

        from sales.management.commands import convert_proxy_delivery_orders as command

        first, second = self.make_order(PROXY), self.make_order(PROXY)
        real_revert = command._revert

        def failing(order):
            if order.pk == second.pk:
                raise RuntimeError("模擬寫入失敗")
            return real_revert(order)

        before = self.state()
        with mock.patch.object(command, "_revert", side_effect=failing):
            with self.assertRaises(RuntimeError):
                self.run_command("--revert", "--apply")
        self.assertEqual(self.state(), before)
        for order in (first, second):
            self.assertEqual(SalesOrder.objects.get(pk=order.pk).transaction_type, PROXY)

    def test_revert_apply_locks_the_target_orders(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.make_order(PROXY)
        with CaptureQueriesContext(connection) as captured:
            output = self.run_command("--revert", "--apply")
        self.assertIn("已改回 1 張。", output)
        if connection.features.has_select_for_update_of:
            targets = [query["sql"] for query in captured.captured_queries
                       if "FOR UPDATE" in query["sql"] and "proxy_delivery" in query["sql"]]
            self.assertEqual(len(targets), 1, targets)
            self.assertRegex(targets[0], r'FOR UPDATE OF "sales_salesorder"\s*$')
