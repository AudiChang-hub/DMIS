from pathlib import Path

from django.test import TestCase
from django.urls import reverse


class CatalogAutoFilterTests(TestCase):
    def test_catalog_filters_apply_on_select_change(self):
        page = self.client.get(reverse("catalog")).content.decode()
        form = page.split("data-catalog-filters", 1)[1].split("</form>", 1)[0]
        self.assertIn("data-auto-submit", form)
        # 有 JavaScript 時不需要按鈕；停用時仍可手動套用。
        self.assertIn("<noscript><button class=\"button primary\">套用篩選</button></noscript>", form)
        script = Path("static/js/catalog-manage.js").read_text(encoding="utf-8")
        self.assertIn("form.hasAttribute('data-auto-submit')", script)
        self.assertIn("form.requestSubmit()", script)
