from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase


class RecentFieldValuesTests(SimpleTestCase):
    def test_base_template_loads_recent_field_values_script(self):
        template = get_template("base.html")
        self.assertIsNotNone(template)
        source = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("recent-field-values.js", source)
        self.assertIn("data-history-user", source)

    def test_script_keeps_ten_values_and_excludes_sensitive_fields(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "recent-field-values.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("const MAX_VALUES = 10", source)
        self.assertIn("username|password|passwd|csrf|token|secret", source)
        self.assertIn("dataset.noRecentValues", source)
        self.assertIn('querySelectorAll?.("form, input, textarea, select")', source)
        self.assertIn('setAttribute("autocomplete", "off")', source)
