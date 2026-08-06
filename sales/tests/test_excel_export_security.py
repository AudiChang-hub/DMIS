from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from sales.services.excel_export import sanitize_excel_row, sanitize_excel_value


class ExcelExportSecurityTests(SimpleTestCase):
    def test_formula_prefixes_are_escaped_as_text(self):
        for value in ("=1+1", "+SUM(A1:A2)", "-2+3", "@SUM(A1:A2)"):
            with self.subTest(value=value):
                self.assertEqual(sanitize_excel_value(value), f"'{value}")

    def test_control_character_cannot_bypass_formula_detection(self):
        self.assertEqual(sanitize_excel_value("\t=1+1"), "'\t=1+1")

    def test_non_text_values_and_normal_text_are_unchanged(self):
        values = ["一般文字", Decimal("123.45"), date(2026, 8, 6), None]
        self.assertEqual(sanitize_excel_row(values), values)
