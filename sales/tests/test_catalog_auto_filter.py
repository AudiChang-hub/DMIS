from pathlib import Path

from django.test import TestCase
from django.urls import reverse


class CatalogAutoFilterTests(TestCase):
    def test_catalog_filters_update_results_in_place(self):
        page = self.client.get(reverse("catalog")).content.decode()
        form = page.split("data-catalog-filters", 1)[1].split("</form>", 1)[0]
        self.assertIn("data-auto-submit", form)
        self.assertIn("data-catalog-clear", form)
        # 有 JavaScript 時不需要按鈕；停用時仍可手動套用。
        self.assertIn("<noscript><button class=\"button primary\">套用篩選</button></noscript>", form)
        results = page.split("data-catalog-results", 1)[1]
        self.assertIn("個車色選項", results.split("catalog-filter-options", 1)[0])
        script = Path("static/js/catalog-manage.js").read_text(encoding="utf-8")
        # 只替換結果區並更新網址，不重新整理整頁；失敗時才退回一般載入。
        self.assertIn("results.innerHTML = next.innerHTML", script)
        self.assertIn("history.replaceState", script)
        self.assertIn("window.location.assign(url)", script)
        self.assertNotIn("form.requestSubmit()", script)

    def test_filtered_request_renders_results_container(self):
        page = self.client.get(reverse("catalog"), {"brand": "不存在的品牌"}).content.decode()
        results = page.split("data-catalog-results", 1)[1]
        self.assertIn("目前沒有符合條件的啟用車色", results)
