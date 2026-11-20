"""T-255（使用者 2026-11-20）：全部訂單「領牌日期」今天標綠、下個工作日標黃；未領牌與其他日期不上色。

下個工作日沿用 services/business_days.add_business_days（跳過週末與「工作日與假日設定」的假日）；今天以台灣時區為準。
不能只靠顏色：標色的日期另有 title 與螢幕報讀文字。只改這一欄，客戶頁等其他用到訂單列的地方不受影響。
"""
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import BusinessHoliday, SalesOrder, VehicleColor, VehicleModel
from sales.services.business_days import registration_marks

FRIDAY = date(2026, 11, 20)
TODAY_MARK = '<span class="registration-date-mark registration-date-mark--today" title="今天">{}<span class="visually-hidden">（今天）</span></span>'
NEXT_MARK = '<span class="registration-date-mark registration-date-mark--next" title="下個工作日">{}<span class="visually-hidden">（下個工作日）</span></span>'


class RegistrationMarksServiceTests(TestCase):
    def test_next_business_day_skips_weekend_and_holidays(self):
        self.assertEqual(registration_marks(date(2026, 11, 18)), {"today": date(2026, 11, 18), "next_business_day": date(2026, 11, 19)})
        self.assertEqual(registration_marks(FRIDAY)["next_business_day"], date(2026, 11, 23))  # 週五 → 下週一
        BusinessHoliday.objects.create(date=date(2026, 11, 23), name="合成假日")
        self.assertEqual(registration_marks(FRIDAY)["next_business_day"], date(2026, 11, 24))  # 週一放假 → 週二
        BusinessHoliday.objects.filter(date=date(2026, 11, 23)).update(active=False)  # 不排除工作日計算的假日不跳過
        self.assertEqual(registration_marks(FRIDAY)["next_business_day"], date(2026, 11, 23))

    def test_today_uses_taiwan_time(self):
        # UTC 11/19 17:00＝台灣 11/20 01:00：今天要算 11/20。
        with patch("django.utils.timezone.now", return_value=datetime(2026, 11, 19, 17, 0, tzinfo=ZoneInfo("UTC"))):
            self.assertEqual(registration_marks()["today"], FRIDAY)


@patch("sales.services.business_days.timezone.localdate", return_value=FRIDAY)
class OrderListRegistrationMarkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("mark-admin", password="Test-Only-123")
        cls.model = VehicleModel.objects.create(brand="測試", name="標色測試車", energy_type="gas")
        cls.color = VehicleColor.objects.create(vehicle_model=cls.model, name="白")

    def setUp(self):
        self.client.force_login(self.admin)

    def make_order(self, day, *, completed=False, owner="標色合成車主"):
        return SalesOrder.objects.create(
            owner_name=owner, owner_phone="0912345678", owner_address="合成地址", owner_id_number="A123456789",
            vehicle_model=self.model, color=self.color, registration_date=day,
            registration_completed_at=timezone.now() if completed else None)

    def page(self, **params):
        response = self.client.get(reverse("order_list"), {"tab": "all", **params})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_today_green_next_business_day_yellow_others_plain(self, _localdate):
        self.make_order(FRIDAY)                                   # 預計今天
        self.make_order(FRIDAY, completed=True)                   # 今天已領牌
        self.make_order(date(2026, 11, 23))                       # 下個工作日（跳過週末）
        self.make_order(date(2026, 11, 21))                       # 週六：不是下個工作日
        self.make_order(date(2026, 11, 19), completed=True)       # 昨天
        self.make_order(None)                                     # 未領牌
        html = self.page()
        # 電腦版表格與手機版卡片各一份。
        self.assertEqual(html.count(TODAY_MARK.format("預計 2026/11/20")), 2)
        self.assertEqual(html.count(TODAY_MARK.format("2026/11/20")), 2)
        self.assertEqual(html.count(NEXT_MARK.format("預計 2026/11/23")), 2)
        self.assertEqual(html.count("registration-date-mark--today"), 4)
        self.assertEqual(html.count("registration-date-mark--next"), 2)
        for plain in ("<td>預計 2026/11/21</td>", "<td>2026/11/19</td>", "<td>未領牌</td>",
                      "<b>預計 2026/11/21</b>", "<b>2026/11/19</b>", "<b>未領牌</b>"):
            self.assertIn(plain, html)
        self.assertIn("css/order-registration-mark.css", html)

    def test_holiday_moves_the_yellow_mark(self, _localdate):
        BusinessHoliday.objects.create(date=date(2026, 11, 23), name="合成假日")
        self.make_order(date(2026, 11, 23))
        self.make_order(date(2026, 11, 24))
        html = self.page()
        self.assertIn("<td>預計 2026/11/23</td>", html)
        self.assertEqual(html.count(NEXT_MARK.format("預計 2026/11/24")), 2)

    def test_sorting_and_filters_are_unchanged(self, _localdate):
        today = self.make_order(FRIDAY, completed=True, owner="標色今天")
        older = self.make_order(date(2026, 11, 2), completed=True, owner="標色較早")
        html = self.page(sort="registration_date")
        self.assertLess(html.index("標色較早"), html.index("標色今天"))
        registered = self.page(registered="no")
        self.assertNotIn("標色今天", registered)
        self.assertTrue(today.pk and older.pk)

    def test_customer_page_order_rows_are_not_marked(self, _localdate):
        order = self.make_order(FRIDAY)
        response = self.client.get(reverse("customer_detail", args=[order.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(order.number, html)
        self.assertNotIn("registration-date-mark", html)


@patch("sales.services.business_days.timezone.localdate", return_value=FRIDAY)
class MobileCardRegistrationFullTests(OrderListRegistrationMarkTests):
    """2.32.0 追加：手機卡片的領牌日期完整顯示（換行，不再單行省略），只改這一欄。"""
    for _name in [name for name in dir(OrderListRegistrationMarkTests) if name.startswith("test_")]:
        locals()[_name] = None
    del _name

    def test_card_registration_fact_wraps_instead_of_truncating(self, _localdate):
        self.make_order(FRIDAY)
        html = self.page()
        self.assertIn('<span class="order-fact order-fact--registration"><small>領牌日期</small><b>'
                      + TODAY_MARK.format("預計 2026/11/20") + "</b></span>", html)
        self.assertEqual(html.count("order-fact--registration"), 1)  # 其他欄位不加
        from django.conf import settings
        css = (settings.BASE_DIR / "static/css/order-registration-mark.css").read_text(encoding="utf-8")
        rule = css[css.index(".order-fact--registration b {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("white-space: normal;", rule)
        self.assertIn("overflow: visible;", rule)
        card_mark = css[css.index(".order-fact b .registration-date-mark {"):]
        self.assertNotIn("nowrap", card_mark[:card_mark.index("}")])
