"""1.62.3：訂單頁首固定、完成編輯、生日（民國＋西元）與證件號碼不遮罩。"""
from datetime import date

from django.urls import reverse

from sales.templatetags.sales_format import roc_date
from sales.tests import test_completed_order_corrections as correction_tests
from django.test import TestCase, SimpleTestCase


class RocDateTests(SimpleTestCase):
    def test_roc_date(self):
        self.assertEqual(roc_date(date(1992, 1, 21)), "民國 81 年 1 月 21 日")
        self.assertEqual(roc_date(None), "")


class StickyHeroScriptTests(SimpleTestCase):
    def test_collapsed_height_is_reserved_to_avoid_scroll_anchoring_loop(self):
        # 1.74.4：頁首縮小若改變頁面高度，瀏覽器捲動錨定會把位置拉回門檻內，形成無限切換。
        from pathlib import Path
        from django.conf import settings
        script = (Path(settings.BASE_DIR) / "static/js/sticky-hero.js").read_text(encoding="utf-8")
        self.assertIn("sticky-hero-spacer", script)
        self.assertIn("fullHeight - height", script)


class OrderHeaderTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order

    def test_detail_shows_phone_birthdays_and_full_id(self):
        order = self.order(owner_birth_date=date(1992, 1, 21))
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(response, "data-sticky-hero")
        self.assertContains(response, "民國 81 年 1 月 21 日")
        self.assertContains(response, "西元 1992/01/21")
        self.assertContains(response, "1992/01/21")
        self.assertContains(response, "電話 <strong>0912345678</strong>", html=False)
        self.assertContains(response, "A123456789")
        self.assertNotContains(response, "A1＊")

    def test_order_page_edits_inline_without_finish_button(self):
        # 1.82.0：不另開編輯頁，訂單內容在訂單頁自動儲存，不需要「完成編輯」。
        order = self.order()
        response = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})
        self.assertContains(response, "data-inline-order")
        self.assertNotContains(response, "完成編輯")
        self.assertNotContains(response, f'href="{reverse("order_edit", args=[order.pk])}"')
