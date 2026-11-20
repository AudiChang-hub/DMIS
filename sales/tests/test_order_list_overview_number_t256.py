"""T-256（使用者 2026-11-20）：全部訂單每列「刪除訂單」下方加「訂單總覽」，機種下方加引擎號碼（電動車顯示車身號碼）。

總覽沿用訂單頁同一份唯讀內容（order_overview?fragment=1），在清單頁的對話框開啟；權限照 order_overview。
號碼取已配車的車輛，未配車不顯示；查詢數不隨列數增加。
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.models import SalesOrder, Store, VehicleColor, VehicleInventory, VehicleModel


class OrderListOverviewNumberTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("t256-admin", password="Test-Only-123")
        cls.store = Store.objects.create(name="T256 測試店", code="T256")
        cls.gas = VehicleModel.objects.create(brand="測試", name="油車機種", energy_type="gas", displacement_cc=125)
        cls.electric = VehicleModel.objects.create(brand="測試", name="電車機種", energy_type="electric")
        cls.gas_color = VehicleColor.objects.create(vehicle_model=cls.gas, name="白")
        cls.electric_color = VehicleColor.objects.create(vehicle_model=cls.electric, name="黑")
        cls.counter = 0

    def setUp(self):
        self.client.force_login(self.admin)

    def make_order(self, model, color, *, engine=None, frame=None, owner="號碼合成車主"):
        vehicle = None
        if engine or frame:
            vehicle = VehicleInventory.objects.create(
                vehicle_model=model, color=color, engine_number=engine, frame_number=frame,
                ownership_store=self.store, location_store=self.store, status=VehicleInventory.Status.RESERVED)
        return SalesOrder.objects.create(
            owner_name=owner, owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=model, color=color, allocated_vehicle=vehicle)

    def page(self, **params):
        response = self.client.get(reverse("order_list"), {"tab": "all", **params})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_gas_shows_engine_number_with_spaces_electric_shows_frame_unallocated_shows_nothing(self):
        self.make_order(self.gas, self.gas_color, engine="ABC  12345")
        self.make_order(self.electric, self.electric_color, frame="EVF 0001")
        self.make_order(self.gas, self.gas_color)
        html = self.page()
        engine = '<small class="order-vehicle-number" title="引擎號碼"><span class="visually-hidden">引擎號碼：</span>ABC  12345</small>'
        frame = '<small class="order-vehicle-number" title="車身號碼"><span class="visually-hidden">車身號碼：</span>EVF 0001</small>'
        self.assertEqual(html.count(engine), 2)  # 電腦版表格＋手機卡片
        self.assertEqual(html.count(frame), 2)
        self.assertEqual(html.count('class="order-vehicle-number"'), 4)  # 未配車那張不顯示
        self.assertIn("css/order-vehicle-number.css", html)

    def test_overview_link_under_delete_opens_the_shared_overview(self):
        order = self.make_order(self.gas, self.gas_color, owner="總覽合成車主")
        html = self.page()
        url = reverse("order_overview", args=[order.pk])
        link = html.index(f'data-order-overview-open="{url}"')
        cell = html[html.rindex("<td>", 0, link):]
        cell = cell[:cell.index("</td>")]
        self.assertIn(order.established_display, cell)  # 在第一欄「訂單成立日期」
        self.assertIn(f'href="{url}" data-order-overview-open="{url}"', cell)
        self.assertIn(f'data-overview-title="總覽合成車主" data-overview-meta="{order.number}"', cell)
        if "刪除訂單" in cell:
            self.assertLess(cell.index("刪除訂單"), cell.index(">訂單總覽<"))
        self.assertIn('data-order-overview-dialog data-overview-shortcut="off"', html)
        self.assertIn("js/order-overview.js", html)
        self.assertIn("css/order-overview.css", html)
        fragment = self.client.get(url, {"fragment": "1"})
        self.assertEqual(fragment.status_code, 200)
        self.assertContains(fragment, "data-order-overview")

    def test_overview_link_follows_overview_permission(self):
        order = self.make_order(self.gas, self.gas_color)
        staff = get_user_model().objects.create_user("t256-staff", password="Test-Only-123")
        UserAccessState.objects.create(user=staff, configured=True)
        ScreenAccessGrant.objects.create(user=staff, screen_key="orders", view=True)
        self.client.force_login(staff)
        html = self.page()
        self.assertIn(f'data-order-overview-open="{reverse("order_overview", args=[order.pk])}"', html)
        self.assertEqual(self.client.get(reverse("order_overview", args=[order.pk]), {"fragment": "1"}).status_code, 200)

    def test_query_count_does_not_grow_with_rows(self):
        self.make_order(self.gas, self.gas_color, engine="ENGQ0001")
        self.make_order(self.electric, self.electric_color, frame="FRMQ0001")
        self.page()  # 先熱身：快取、權限等一次性查詢
        with CaptureQueriesContext(connection) as few:
            self.page()
        for index in range(6):
            self.make_order(self.gas, self.gas_color, engine=f"ENGQ{index + 10:04d}")
            self.make_order(self.electric, self.electric_color, frame=f"FRMQ{index + 10:04d}")
        self.page()
        with CaptureQueriesContext(connection) as many:
            self.page()
        self.assertEqual(len(many), len(few), [q["sql"][:120] for q in many.captured_queries])


class MobileCardOverviewLinkTests(OrderListOverviewNumberTests):
    """2.32.0 追加：手機卡片也有「訂單總覽」，放在右欄狀態下方，打開同一個總覽對話框。"""
    for _name in [name for name in dir(OrderListOverviewNumberTests) if name.startswith("test_")]:
        locals()[_name] = None
    del _name

    def test_card_has_overview_link_in_status_column(self):
        order = self.make_order(self.gas, self.gas_color, owner="卡片總覽合成車主")
        html = self.page()
        url = reverse("order_overview", args=[order.pk])
        card = html[html.index('<div class="order-row order-row--detailed">'):]
        status = card[card.index('<span class="order-row-status">'):]
        status = status[:status.index("</span>", status.index("order-card-overview"))]
        self.assertIn(f'<a class="order-card-overview" href="{url}" data-order-overview-open="{url}"', status)
        self.assertIn(f'data-overview-title="卡片總覽合成車主" data-overview-meta="{order.number}"', status)
        self.assertEqual(html.count(f'data-order-overview-open="{url}"'), 2)  # 電腦版表格＋手機卡片各一個

    def test_customer_page_rows_have_no_overview_link(self):
        order = self.make_order(self.gas, self.gas_color)
        html = self.client.get(reverse("customer_detail", args=[order.pk])).content.decode()
        self.assertNotIn("order-card-overview", html)
