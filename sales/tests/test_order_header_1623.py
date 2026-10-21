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


class CompactBarScriptTests(SimpleTestCase):
    def test_compact_bar_never_changes_layout_height(self):
        # 1.86.34（使用者 2026-10-21）：頁首不再縮放、也不墊高補位（舊做法往下捲時會露出一段空白）；
        # 精簡列疊在高度為 0 的 sticky 定位點上，顯示與否不影響版面高度。
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        self.assertFalse((base / "static/js/sticky-hero.js").exists())
        script = (base / "static/js/order-compact-bar.js").read_text(encoding="utf-8")
        self.assertIn("IntersectionObserver", script)
        self.assertNotIn("spacer", script)
        styles = (base / "static/css/order-workspace.css").read_text(encoding="utf-8")
        anchor = styles.split(".order-compact-anchor {", 1)[1].split("}", 1)[0]
        self.assertIn("height: 0", anchor)
        self.assertIn("position: sticky", anchor)
        bar = styles.split(".order-compact-bar {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", bar)
        self.assertNotIn("order-sticky-hero", styles)

    def test_left_steps_land_on_section_top_without_padding(self):
        # 左側步驟一律停在該區最上方（瞬間定位）；不再在下方補空白來湊停點。
        from pathlib import Path
        from django.conf import settings
        script = (Path(settings.BASE_DIR) / "static/js/order-workspace.js").read_text(encoding="utf-8")
        END = chr(10) + "  }" + chr(10)
        land = script.split("function land(smooth) {", 1)[1].split(END, 1)[0]
        self.assertNotIn("paddingBottom = `", land)
        self.assertIn("Math.min(top, max)", land)
        self.assertIn("panelOf(activeKey)", script.split("function stageTop() {", 1)[1].split(END, 1)[0])
        self.assertIn("showBar(false); return; }", script)


class OrderHeaderTests(TestCase):
    setUpTestData = classmethod(correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = correction_tests.CompletedOrderCorrectionTests.setUp
    order = correction_tests.CompletedOrderCorrectionTests.order

    def test_detail_shows_phone_birthdays_and_full_id(self):
        order = self.order(owner_birth_date=date(1992, 1, 21))
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        self.assertContains(response, "data-order-hero")
        self.assertContains(response, "data-order-compact-bar")
        self.assertNotContains(response, "data-sticky-hero")
        self.assertContains(response, "民國 81 年 1 月 21 日")
        self.assertContains(response, "西元 1992/01/21")
        self.assertContains(response, "1992/01/21")
        self.assertContains(response, '<span>電話</span><strong class="order-owner-facts__mono">0912345678</strong>', html=False)
        self.assertContains(response, "A123456789")
        self.assertNotContains(response, "A1＊")

    def test_order_page_edits_inline_without_finish_button(self):
        # 1.82.0：不另開編輯頁，訂單內容在訂單頁自動儲存，不需要「完成編輯」。
        order = self.order()
        response = self.client.get(reverse("order_detail", args=[order.pk]), {"tab": "order"})
        self.assertContains(response, "data-inline-order")
        self.assertNotContains(response, "完成編輯")
        self.assertNotContains(response, f'href="{reverse("order_edit", args=[order.pk])}"')
