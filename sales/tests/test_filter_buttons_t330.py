"""T-330（2.42.1 驗收）：篩選按鈕名稱與順序。

- 送禮分發：「活動清單」只有一個搜尋框，按鈕叫「搜尋」；「名單」有「完成狀態」下拉，維持「套用」。
- 套表列印、畫面與列印說明文字：照 UI_GUIDELINES「篩選與查詢」，「清除」在前、「套用」在後。
資料全部虛構。
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import GiftDistribution


def filter_form(html, marker):
    forms = [m.group(0) for m in re.finditer(r"<form(?![^>]*method=\"post\")[^>]*>.*?</form>", html, re.S)
             if marker in m.group(0).split(">", 1)[0]]
    assert len(forms) == 1, marker
    return forms[0]


def submit_labels(form):
    return [re.sub(r"<[^>]+>", "", m.group(1)).strip()
            for m in re.finditer(r"<button(?![^>]*type=\"button\")[^>]*>(.*?)</button>", form, re.S)]


class FilterButtonsT330Tests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="Local-t330-628!"))

    def test_gift_activity_list_uses_search_and_recipient_list_uses_apply(self):
        html = self.client.get(reverse("gift_distribution")).content.decode()
        self.assertEqual(submit_labels(filter_form(html, "filter-bar")), ["搜尋"])
        activity = GiftDistribution.objects.create(title="示範活動")
        html = self.client.get(reverse("gift_distribution_detail", args=[activity.pk])).content.decode()
        form = filter_form(html, "filter-bar")
        self.assertIn('name="state"', form)
        self.assertEqual(submit_labels(form), ["套用"])

    def test_clear_comes_before_apply(self):
        for url, marker, clear in (
            (reverse("form_print") + "?q=示範", "form-print__search", "清除搜尋"),
            (reverse("site_copy_manage") + "?q=示範", "filter-bar", "清除"),
        ):
            with self.subTest(url=url):
                form = filter_form(self.client.get(url).content.decode(), marker)
                self.assertLess(form.index(f">{clear}</a>"), form.index(">套用</button>"))
