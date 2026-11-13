"""T-167 營運總表駕駛艙（使用者 2026-11-13 選 A 案）。"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import (
    IncentiveCampaign,
    OrderOperationsProfile,
    PaymentRecord,
    SalesOrder,
    Store,
    VehicleColor,
    VehicleInventory,
    VehicleModel,
)
from sales.services import operations_cockpit
from sales.services.dashboard_metrics import _last_year, build_dashboard_metrics


def make_vehicle(model, color, status, number, received_on=None):
    store = Store.objects.get_or_create(code="OPS", defaults={"name": "總表測試店"})[0]
    return VehicleInventory.objects.create(
        vehicle_model=model, color=color, engine_number=f"ENG-OPS-{number:05d}", ownership_store=store,
        location_store=store, status=status, received_on=received_on or date(2026, 9, 1))


class InventoryOnHandTests(TestCase):
    """2.6.x「庫存總數」只排除停用，已售出、調出、已交車都被算進去（正式站顯示 1,554，實際在庫 40）。"""

    @classmethod
    def setUpTestData(cls):
        cls.model = VehicleModel.objects.create(brand="測試", name="在庫測試機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def test_on_hand_counts_only_available_reserved_and_condition_issue(self):
        statuses = ["available", "available", "reserved", "condition_issue",
                    "sold", "transferred_out", "delivered", "inactive"]
        for number, status in enumerate(statuses, start=1):
            make_vehicle(self.model, self.color, status, number)
        inventory = build_dashboard_metrics(date(2026, 9, 12))["inventory"]
        self.assertEqual(inventory["total"], 4)
        self.assertEqual(inventory["available"], 2)
        self.assertEqual(inventory["reserved"], 1)
        self.assertEqual(inventory["issues"], 1)


ALL_LINKS = {key: True for key in (
    "order_list", "inventory_list", "reconciliation_list", "dealer_payout_list", "report_center",
    "dealer_volume_bonus_list", "incentive_rule_list", "operations_report_export")}


class CockpitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("cockpit-admin", password="test-only")
        cls.model = VehicleModel.objects.create(brand="測試", name="駕駛艙機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")
        cls.ev = VehicleModel.objects.create(brand="測試", name="駕駛艙電車", energy_type="electric")
        cls.ev_color = VehicleColor.objects.create(vehicle_model=cls.ev, name="藍")

    def setUp(self):
        cache.clear()

    def make_order(self, day=None, status="completed", price=80000, profit=20000, established=None, model=None, **extra):
        model = model or self.model
        color = self.ev_color if model == self.ev else self.color
        order = SalesOrder.objects.create(
            owner_name="駕駛艙合成測試", owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=model, color=color, registration_date=day, established_on=established or day, status=status,
            vehicle_price=price, **extra)
        OrderOperationsProfile.objects.filter(order=order).update(
            actual_disbursement=price, vehicle_cost=price - profit, legacy_finance_reconciliation={})
        return order

    def user_with(self, *screens):
        user = get_user_model().objects.create_user("cockpit-" + "-".join(screens), password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        for key in screens:
            ScreenAccessGrant.objects.create(user=user, screen_key=key, view=True)
        return user

    # ── 比較基準：上月同期與去年同期並列 ──

    def test_last_year_handles_leap_day(self):
        self.assertEqual(_last_year(date(2028, 2, 29)), date(2027, 2, 28))
        self.assertEqual(_last_year(date(2026, 11, 13)), date(2025, 11, 13))

    def test_previous_and_last_year_same_period_side_by_side(self):
        today = date(2026, 11, 13)
        self.make_order(date(2026, 11, 2))
        self.make_order(date(2026, 11, 10), price=60000)
        self.make_order(date(2026, 10, 5))                 # 上月同期
        self.make_order(date(2026, 10, 20))                # 上月但超過同期，不算
        for day in (date(2025, 11, 1), date(2025, 11, 12), date(2025, 11, 13), date(2025, 11, 3)):
            self.make_order(day)                           # 去年同期 4 台
        self.make_order(date(2025, 11, 20))                # 去年同月但超過同期
        self.make_order(date(2026, 11, 3), status="cancelled")
        pulse = operations_cockpit.build("month", today)["pulse"]
        self.assertEqual(pulse["count"]["value"], 2)
        self.assertEqual(pulse["count"]["previous"], 1)
        self.assertEqual(pulse["count"]["last_year"], 4)
        self.assertEqual(pulse["count"]["vs_previous"], 100)
        self.assertEqual(pulse["count"]["vs_last_year"], -50)
        self.assertEqual(pulse["sales"]["value"], Decimal("140000"))
        chips = operations_cockpit._chips(pulse["count"], "台", True)
        self.assertEqual([(chip["label"], chip["change"], chip["tone"]) for chip in chips],
                         [("上月同期", "+100%", "up"), ("去年同期", "−50%", "down")])

    def test_last_month_and_ytd_windows(self):
        today = date(2026, 11, 13)
        self.make_order(date(2026, 10, 25))
        self.make_order(date(2026, 9, 25))
        self.make_order(date(2025, 10, 30))
        self.make_order(date(2026, 1, 5))
        last_month = operations_cockpit.build("last_month", today)
        self.assertEqual(last_month["windows"]["current"], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(last_month["pulse"]["count"]["value"], 1)
        self.assertEqual(last_month["pulse"]["count"]["previous"], 1)
        self.assertEqual(last_month["pulse"]["count"]["last_year"], 1)
        ytd = operations_cockpit.build("ytd", today)
        self.assertIsNone(ytd["windows"]["previous"])
        self.assertEqual(ytd["pulse"]["count"]["value"], 3)
        self.assertIsNone(ytd["pulse"]["count"]["vs_previous"])
        chips = operations_cockpit._chips(ytd["pulse"]["count"], "台", False)
        self.assertEqual([chip["label"] for chip in chips], ["去年同期"])

    def test_trend_pairs_each_month_with_same_month_last_year(self):
        today = date(2026, 11, 13)
        self.make_order(date(2026, 11, 2))
        self.make_order(date(2025, 11, 2))
        self.make_order(date(2025, 11, 25))   # 去年同月但晚於去年今天，不算進最後一點
        series = operations_cockpit.build("month", today)["trend"]["series"]["count"]
        self.assertEqual(len(series["points"]), 12)
        self.assertEqual(series["points"][-1]["label"], "2026/11")
        self.assertEqual(series["points"][-1]["last_label"], "2025/11")
        self.assertEqual((series["points"][-1]["this"], series["points"][-1]["last"]), (1, 1))

    # ── 顯示門檻 ──

    def test_flow_stage_thresholds(self):
        today = timezone.localdate()
        self.make_order(status="allocation_pending", established=today - timedelta(days=4))
        self.make_order(status="allocation_pending", established=today - timedelta(days=3))
        SalesOrder.objects.filter(pk=self.make_order(status="allocated").pk).update(
            allocated_at=timezone.now() - timedelta(days=31))
        SalesOrder.objects.filter(pk=self.make_order(status="allocated").pk).update(
            allocated_at=timezone.now() - timedelta(days=29))
        stages = {stage["key"]: stage for stage in operations_cockpit.build("month", today)["flow"]["stages"]}
        self.assertEqual((stages["allocation_pending"]["count"], stages["allocation_pending"]["stuck"]), (2, 1))
        self.assertEqual(stages["allocation_pending"]["oldest"], 4)
        self.assertEqual((stages["allocated"]["count"], stages["allocated"]["stuck"]), (2, 1))
        self.assertIsNone(stages["delivery_pending"]["oldest"])
        self.assertEqual([stage["limit"] for stage in stages.values()], [3, 30, 7, 14])

    def test_stock_age_shortage_and_slow(self):
        today = timezone.localdate()
        for number in range(1, 3):
            make_vehicle(self.model, self.color, "available", number, received_on=today - timedelta(days=95))
        make_vehicle(self.model, self.color, "reserved", 3, received_on=today - timedelta(days=10))
        make_vehicle(self.model, self.color, "sold", 4, received_on=today - timedelta(days=400))
        for offset in (1, 20, 40):
            self.make_order(today - timedelta(days=offset), model=self.ev)   # 電車 90 天賣 3 台、在庫 0
        stock = operations_cockpit.build("month", today)["stock"]
        self.assertEqual(stock["on_hand"], 3)
        self.assertEqual(stock["aged"], 2)
        self.assertEqual([bucket["count"] for bucket in stock["aging"]], [1, 0, 0, 2])
        self.assertEqual(stock["shortage"], ["駕駛艙電車"])
        self.assertEqual(stock["slow"], ["駕駛艙機種"])   # 在庫 3、90 天內 0 台

    # ── 錢 ──

    def test_receivables_split_before_and_after_delivery(self):
        delivered = self.make_order(date(2026, 9, 1), status="completed")
        pending = self.make_order(status="allocation_pending")
        for order in (delivered, pending):
            PaymentRecord.objects.create(order=order, expected_amount=500, received_amount=100, confirmed=False)
        money = operations_cockpit.build("month", date(2026, 9, 12))["money"]
        self.assertEqual(money["outstanding_count"], 2)
        self.assertEqual(money["unsettled_count"] + money["before_delivery_count"], money["outstanding_count"])
        self.assertGreaterEqual(money["before_delivery_count"], 1)

    # ── 頁面與權限 ──

    def test_admin_page_renders_all_sections(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        self.make_order(today)
        IncentiveCampaign.objects.create(name="駕駛艙測試活動", effective_from=today - timedelta(days=5),
                                         effective_to=today + timedelta(days=10))
        response = self.client.get(reverse("operations_report"))
        self.assertEqual(response.status_code, 200)
        for text in ("營運總表", "上月同期", "去年同期", "需要處理", "訂單流程", "結構變化", "車型貢獻",
                     "進行中的原廠獎勵", "駕駛艙測試活動", "即將結束", "資料可信度"):
            self.assertContains(response, text)
        self.assertNotContains(response, "台數獎金門檻進度")   # dealer_payouts 要明確勾選（只有 root 帳號 admin 例外）
        self.assertNotContains(response, "駕駛艙合成測試")   # 不列客戶資料
        for period in ("last_month", "ytd", "unknown"):
            self.assertEqual(self.client.get(reverse("operations_report"), {"period": period}).status_code, 200)

    def test_dashboard_only_viewer_sees_no_money_amounts_or_profit(self):
        today = timezone.localdate()
        self.make_order(today, profit=12345)
        self.client.force_login(self.user_with("dashboard"))
        response = self.client.get(reverse("operations_report"))
        cockpit = response.context["cockpit"]
        self.assertNotIn("profit", cockpit["pulse"])
        self.assertNotIn("outstanding_amount", cockpit["money"])
        for key in ("payouts", "volume_bonus", "campaigns", "reconciliation"):
            self.assertNotIn(key, cockpit)
        self.assertContains(response, "需要「查看淨利」權限")
        self.assertNotContains(response, "12,345")
        self.assertNotContains(response, "待收合計")
        self.assertNotContains(response, "台數獎金門檻進度")
        self.assertNotContains(response, "進行中的原廠獎勵")

    def test_optional_sections_follow_their_own_screens(self):
        self.client.force_login(self.user_with("dashboard", "dealer_payouts", "incentives"))
        response = self.client.get(reverse("operations_report"))
        self.assertContains(response, "台數獎金門檻進度")
        self.assertContains(response, "進行中的原廠獎勵")
        self.assertContains(response, "車行傭金／獎金未給付")

    def test_attention_lists_red_before_amber_and_reports_clear_items(self):
        flags = {"dashboard": True, "operations": True, "profit": True, "reconciliation": False,
                 "dealer_payouts": False, "incentives": False, "links": ALL_LINKS}
        data = operations_cockpit.build("month", timezone.localdate())
        data["money"].update({"unconfirmed": 3, "refund": 1, "overpaid": 0})
        attention, clear = operations_cockpit._attention(data, flags)
        self.assertEqual([item["key"] for item in attention], ["refund", "unconfirmed"])
        self.assertIn("溢收待退", clear)

    def test_cache_recomputes_after_data_changes(self):
        today = timezone.localdate()
        first = operations_cockpit.load("month", today)
        self.assertEqual(first["pulse"]["count"]["value"], 0)
        self.assertEqual(operations_cockpit.load("month", today)["generated_at"], first["generated_at"])
        self.make_order(today)
        self.assertEqual(operations_cockpit.load("month", today)["pulse"]["count"]["value"], 1)

    def test_query_count_stays_bounded(self):
        today = timezone.localdate()
        for offset in range(6):
            self.make_order(today - timedelta(days=offset * 20))
        with CaptureQueriesContext(connection) as queries:
            operations_cockpit.build("month", today)
        self.assertLess(len(queries), 60)
