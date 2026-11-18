"""T-233（使用者 2026-11-18）：全部訂單篩選只留日期起訖、能源別、收款確認，直接顯示不摺疊。

日期依據、收款風險、作業提醒、成交範圍從畫面拿掉；營運總表等連結帶來的網址參數照舊有效，
篩選表單以隱藏欄位帶著走，已套用條件列顯示名稱。
"""
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.services.order_filters import analysis_filter_context
from sales.tests import test_command_center


def filter_form(response):
    html = response.content.decode()
    return html.split('<form class="filter-bar order-filter-bar"', 1)[1].split("</form>", 1)[0]


class OrderListFilterT233Tests(TestCase):
    make_order = test_command_center.CommandCenterTests.make_order

    @classmethod
    def setUpTestData(cls):
        test_command_center.CommandCenterTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.user)

    def test_only_four_filters_shown_without_folding(self):
        form = filter_form(self.client.get(reverse("order_list")))
        self.assertNotIn("<details", form)
        visible = re.findall(r'<(?:input|select)(?![^>]*type="hidden")[^>]*name="([a-z_]+)"', form)
        self.assertEqual(visible, ["q", "date_from", "date_to", "energy_type", "payment_status", "status"])
        for removed in ("date_basis", "risk", "attention", "business_only"):
            self.assertNotIn(f'name="{removed}"', form)
        self.assertIn("日期起訖依實際領牌日期。", form)
        self.assertRegex(form, r'order-filter-submit" type="submit">搜尋</button>\s*<p class="muted order-filter-note">')

    def test_removed_filters_still_work_from_links_and_survive_resubmit(self):
        cases = {
            "risk=outstanding": ("risk", "outstanding", "收款風險「待收款」"),
            "attention=dealer": ("attention", "dealer", "作業提醒「車行到期提醒」"),
            "attention=fees": ("attention", "fees", "作業提醒「牌險金額差異待確認」"),
            "date_basis=established": ("date_basis", "established", "日期依據「訂單成立日期」"),
            "business_only=1": ("business_only", "1", "成交範圍「排除取消／退款」"),
        }
        for query, (key, value, label) in cases.items():
            with self.subTest(query):
                response = self.client.get(f"{reverse('order_list')}?{query}")
                self.assertIn(f'<input type="hidden" name="{key}" value="{value}">', filter_form(response))
                self.assertContains(response, f"已套用篩選條件：{label}")

    def test_defaults_and_unknown_values_are_not_carried(self):
        context = analysis_filter_context({"date_basis": "registration", "business_only": "0", "risk": "bogus"})
        self.assertEqual(context["hidden_filters"], [])
        form = filter_form(self.client.get(reverse("order_list"), {"date_basis": "registration", "business_only": "0"}))
        self.assertNotIn('name="date_basis"', form)
        self.assertNotIn('name="business_only"', form)

    def test_hidden_business_only_still_filters_cancelled(self):
        today = timezone.localdate()
        kept = self.make_order(today)
        cancelled = self.make_order(today, status="cancelled")
        params = {"date_from": today.isoformat(), "date_to": today.isoformat()}
        both = self.client.get(reverse("order_list"), params)
        self.assertEqual({o.pk for o in both.context["orders"]}, {kept.pk, cancelled.pk})
        business = self.client.get(reverse("order_list"), {**params, "business_only": "1"})
        self.assertEqual([o.pk for o in business.context["orders"]], [kept.pk])

    def test_export_link_keeps_current_query(self):
        response = self.client.get(reverse("order_list"), {"risk": "refund", "business_only": "1"})
        self.assertContains(response, "risk=refund&amp;business_only=1&include_cancelled=0")
        plain = self.client.get(reverse("order_list"), {"date_from": "2026-01-01"})
        self.assertContains(plain, "date_from=2026-01-01&include_cancelled=1")
