"""T-324（使用者 2026-11-27 核准）：列表頁的篩選設好條件按「套用」才查，送出按鈕一律叫「套用」。

報表中心、選車頁維持選了就查；價格表「月份」「縣市」、套表列印「範圍」維持選了就換（UI_GUIDELINES「篩選與查詢」）。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = Path(settings.BASE_DIR) / "templates" / "sales"
STATIC = Path(settings.BASE_DIR) / "static"


def get_forms(name):
    html = (TEMPLATES / name).read_text(encoding="utf-8")
    return [m.group(0) for m in re.finditer(r'<form(?![^>]*method="post")[^>]*>.*?</form>', html, re.S)]


def submit_labels(form):
    return [re.sub(r"<[^>]+>", "", m.group(1)).strip()
            for m in re.finditer(r'<button(?![^>]*type="button")[^>]*>(.*?)</button>', form, re.S)]


class FilterApplyT324Tests(SimpleTestCase):
    PAGES = {
        "order_list.html": "order-filter-bar",
        "dealer_reward_campaign_list.html": "campaign-filters",
        "gift_distribution.html": "filter-bar",
        "site_copy_manage.html": "filter-bar",
        "price_list_distribution.html": "price-distribution-filters",
        "price_list_distribution_assignments.html": "price-assignment-filters",
        "form_print.html": "form-print__search",
        "incentive_campaign_list.html": "data-campaign-filters",
    }

    def filter_form(self, name):
        marker = self.PAGES[name]
        forms = [form for form in get_forms(name) if marker in form.split(">", 1)[0]]
        self.assertEqual(len(forms), 1, name)
        return forms[0]

    def test_filter_submit_buttons_are_named_apply(self):
        for name in self.PAGES:
            with self.subTest(name):
                labels = submit_labels(self.filter_form(name))
                self.assertTrue(labels, f"{name} 要有送出按鈕")
                self.assertEqual(set(labels), {"套用"}, name)

    def test_order_list_status_waits_for_apply(self):
        form = self.filter_form("order_list.html")
        status = re.search(r'<select name="status"[^>]*>', form).group(0)
        self.assertNotIn("onchange", status)

    def test_incentive_campaign_list_no_longer_queries_while_typing(self):
        js = (STATIC / "js/incentive-campaigns.js").read_text(encoding="utf-8")
        filters = js[js.index("function initFilters"):js.index("function initBackfill")]
        self.assertNotIn("addEventListener('input'", filters)
        self.assertNotIn("addEventListener('change'", filters)
        self.assertIn("form.addEventListener('submit', (event) => { event.preventDefault(); load(); });", filters)
        form = self.filter_form("incentive_campaign_list.html")
        actions = form[form.index("inventory-filter-actions"):]
        self.assertLess(actions.index("清除"), actions.index("套用"), "次要在前、主要在後")

    def test_view_switches_stay_immediate(self):
        # 使用者核准維持選了就換：價格表月份、縣市（行政區連動）、套表列印範圍。
        self.assertIn('name="month" onchange="this.form.submit()"', self.filter_form("price_list_distribution.html"))
        self.assertIn('name="city" onchange="this.form.submit()"', self.filter_form("price_list_distribution.html"))
        self.assertIn('name="city" onchange="this.form.submit()"', self.filter_form("price_list_distribution_assignments.html"))
        self.assertIn('name="tab" onchange="this.form.submit()"', self.filter_form("form_print.html"))

    def test_rule_is_documented(self):
        guide = (Path(settings.BASE_DIR) / "docs/reference/UI_GUIDELINES.md").read_text(encoding="utf-8")
        section = guide[guide.index("## 篩選與查詢"):guide.index("## 提示框與確認頁")]
        self.assertIn("按「套用」才查", section)
        self.assertIn("報表中心、選車頁", section)
