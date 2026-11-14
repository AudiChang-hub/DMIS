"""套表列印：表格上方的橫向捲軸（T-173，使用者 11/13 回饋：捲軸在長表格最底下很難拉）。"""
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.tests import test_order_lifecycle as lifecycle


class FormPrintTopScrollbarTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.make_order(deposit=Decimal("5000"))
        self.client.force_login(self.user)

    def test_bar_sits_right_above_the_table_and_starts_hidden(self):
        html = self.client.get(reverse("form_print")).content.decode()
        bar = re.search(r'<div class="form-print__hscroll"[^>]*>', html).group(0)
        self.assertIn("hidden", bar)
        self.assertIn('aria-hidden="true"', bar)
        self.assertRegex(html, r'data-hscroll hidden aria-hidden="true"><div></div></div>\s*<div class="inventory-table-wrap"[^>]*data-hscroll-target')

    def test_bar_sticks_below_header_and_follows_the_table(self):
        css = (Path(settings.BASE_DIR) / "static/css/form-print.css").read_text(encoding="utf-8")
        rule = re.search(r"\.form-print__hscroll \{(.*?)\}", css, flags=re.S).group(1)
        self.assertIn("position: sticky", rule)
        self.assertIn("top: var(--app-header-height", rule)
        js = (Path(settings.BASE_DIR) / "static/js/form-print.js").read_text(encoding="utf-8")
        self.assertIn('querySelector("[data-hscroll-target]")', js)
        self.assertIn("ResizeObserver", js)
