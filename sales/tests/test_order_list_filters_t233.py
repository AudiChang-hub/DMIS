"""T-233（使用者 2026-11-18）：全部訂單篩選只留日期起訖、能源別、收款確認、領牌，直接顯示不摺疊。

日期起訖固定依實際領牌日期；領牌篩選沿用 registration_confirmed_q（按過確認完成且有領牌日）。

日期依據、收款風險、作業提醒、成交範圍從畫面拿掉；營運總表等連結帶來的網址參數照舊有效，
篩選表單以隱藏欄位帶著走，已套用條件列顯示名稱。
"""
import re

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import SalesOrder

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
        self.assertEqual(visible, ["q", "date_from", "date_to", "energy_type", "payment_status", "registered", "status"])
        for removed in ("date_basis", "risk", "attention", "business_only"):
            self.assertNotIn(f'name="{removed}"', form)
        self.assertIn("日期起訖依實際領牌日期", form)
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
        # T-232 Q9：舊「匯出營運資料」連結拿掉，頁首「匯出」帶入目前的篩選（範圍口徑與清單相同）。
        export = reverse("order_export")
        response = self.client.get(reverse("order_list"), {"risk": "refund", "business_only": "1"})
        self.assertContains(response, f'href="{export}?risk=refund&amp;business_only=1" data-order-export-link')
        plain = self.client.get(reverse("order_list"), {"date_from": "2026-01-01"})
        self.assertContains(plain, f'href="{export}?date_from=2026-01-01" data-order-export-link')

    def test_registered_filter_uses_confirmed_registration(self):
        today = timezone.localdate()
        done = self.make_order(today)
        waiting = self.make_order(status="allocated")
        # 只填預計領牌日、還沒按確認完成：算未領牌（T-172 A′）。
        planned = self.make_order(status="allocated")
        SalesOrder.objects.filter(pk=planned.pk).update(registration_date=today)
        url = reverse("order_list")
        self.assertEqual({o.pk for o in self.client.get(url, {"registered": "yes"}).context["orders"]}, {done.pk})
        self.assertEqual({o.pk for o in self.client.get(url, {"registered": "no"}).context["orders"]}, {waiting.pk, planned.pk})
        self.assertEqual(len(self.client.get(url, {"registered": "bogus", "tab": "all"}).context["orders"]), 3)
        selected = filter_form(self.client.get(url, {"registered": "no"}))
        self.assertIn('<option value="no" selected>未領牌</option>', selected)

    def test_registered_filter_with_date_range(self):
        today = timezone.localdate()
        inside = self.make_order(today)
        self.make_order(today - timedelta(days=60))  # 已領牌但不在範圍
        self.make_order(status="allocated")  # 未領牌
        params = {"date_from": (today - timedelta(days=7)).isoformat(), "date_to": today.isoformat()}
        url = reverse("order_list")
        both = self.client.get(url, params)
        self.assertEqual([o.pk for o in both.context["orders"]], [inside.pk])
        registered = self.client.get(url, {**params, "registered": "yes"})
        self.assertEqual([o.pk for o in registered.context["orders"]], [inside.pk])
        # 日期起訖依實際領牌日期，未領牌的單沒有領牌日期，所以兩者一起用不會有結果。
        unregistered = self.client.get(url, {**params, "registered": "no"})
        self.assertEqual(list(unregistered.context["orders"]), [])
        self.assertContains(unregistered, "未領牌的單沒有領牌日期")

    def test_export_link_carries_registered_filter(self):
        response = self.client.get(reverse("order_list"), {"registered": "no"})
        self.assertContains(response, f'href="{reverse("order_export")}?registered=no" data-order-export-link')  # T-232
