"""T-271（使用者 2026-11-21 選 A）：營運總表「新成立訂單」的歸屬日。

補登單（實際領牌日早於成立日）算到領牌那個月；其他單照成立日。點開數字列出的訂單筆數要和卡片一致。
"""
from datetime import date
from urllib.parse import parse_qsl, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesOrder, VehicleColor, VehicleModel
from sales.services import operations_cockpit

TODAY = date(2026, 11, 21)


class NewOrdersBasisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t271-admin", password="test-only")
        cls.model = VehicleModel.objects.create(brand="測試", name="T271 機種", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def setUp(self):
        cache.clear()

    def make(self, established, registration=None, *, confirmed=True, status="allocated"):
        return SalesOrder.objects.create(
            owner_name="T271 合成測試", owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, established_on=established, registration_date=registration,
            registration_completed_at=timezone.now() if registration and confirmed else None, status=status,
            vehicle_price=80000)

    def make_mix(self):
        self.make(date(2026, 11, 5), date(2026, 10, 25))                    # 補登：10 月已領牌，11 月才建（超過上月同期）
        self.make(date(2026, 11, 8), date(2026, 10, 9))                     # 補登，落在上月同期（10/1–10/21）
        self.make(date(2026, 11, 3), date(2026, 11, 10))                    # 一般：成立後才領牌
        self.make(date(2026, 11, 4))                                        # 未領牌
        self.make(date(2026, 11, 6), date(2026, 10, 25), confirmed=False)   # 只填預計日：不算實際領牌，照成立日
        self.make(date(2026, 11, 2), status="cancelled")                    # 取消
        self.make(date(2026, 11, 7), date(2026, 10, 1), status="cancelled")  # 取消的補登單也不算
        self.make(date(2025, 11, 12), date(2025, 10, 30))                   # 去年補登：不算去年 11 月
        self.make(date(2025, 11, 3))                                        # 去年同期一般單

    def test_backfilled_order_counts_in_registration_month(self):
        self.make_mix()
        metric = operations_cockpit.build("month", TODAY)["pulse"]["new_orders"]
        self.assertEqual(metric["value"], 3)        # 一般、未領牌、只填預計日
        self.assertEqual(metric["previous"], 1)     # 10/9 領牌的補登單
        self.assertEqual(metric["last_year"], 1)

    def test_last_month_window_includes_backfilled_orders(self):
        self.make_mix()
        metric = operations_cockpit.build("last_month", TODAY)["pulse"]["new_orders"]
        self.assertEqual(metric["value"], 2)        # 10/25、10/9 領牌的補登單
        self.assertEqual(metric["last_year"], 1)    # 2025-10-30 領牌的去年補登單

    def test_card_link_lists_same_orders_as_card(self):
        self.make_mix()
        for period in ("month", "last_month", "ytd"):
            metric = operations_cockpit.build(period, TODAY)["pulse"]["new_orders"]
            params = dict(parse_qsl(urlsplit(metric["url"]).query))
            self.client.force_login(self.admin)
            response = self.client.get(reverse("order_list"), params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["page_obj"].paginator.count, metric["value"], period)

    def test_order_list_default_date_filter_still_uses_registration_date(self):
        self.make_mix()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("order_list"), {"date_from": "2026-10-01", "date_to": "2026-10-31"})
        # 已確認領牌在 10 月：兩張補登＋一張取消的補登（預設包含取消）
        self.assertEqual(response.context["page_obj"].paginator.count, 3)

    def test_page_links_card_and_shows_basis_label(self):
        self.make_mix()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("operations_report"))
        url = page.context["cockpit"]["pulse"]["new_orders"]["url"]
        self.assertContains(page, url.replace("&", "&amp;"))
        listed = self.client.get(url)
        self.assertContains(listed, "訂單成立日期（補登依領牌日）")

    def test_card_has_no_link_without_order_list_access(self):
        user = get_user_model().objects.create_user("t271-ops", password="test-only")
        UserAccessState.objects.create(user=user, configured=True)
        ScreenAccessGrant.objects.create(user=user, screen_key="operations", view=True)
        self.make_mix()
        self.client.force_login(user)
        page = self.client.get(reverse("operations_report"))
        self.assertNotContains(page, "date_basis=new_order")
