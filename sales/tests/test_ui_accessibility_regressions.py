import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class SharedUiAccessibilitySourceTests(SimpleTestCase):
    def test_searchable_select_hides_native_control_from_keyboard_and_a11y_tree(
        self,
    ):
        script = Path("static/js/searchable-select.js").read_text(encoding="utf-8")

        self.assertIn("select.tabIndex = -1;", script)
        self.assertIn('select.setAttribute("aria-hidden", "true");', script)
        self.assertIn("if (label) label.htmlFor = input.id;", script)

    def test_layout_audit_ignores_non_visible_content_and_bounded_scrollports(self):
        script = Path("static/js/layout-audit.js").read_text(encoding="utf-8")

        self.assertIn('ancestor.matches("details:not([open])")', script)
        self.assertIn('typeof element.checkVisibility === "function"', script)
        self.assertIn("getContainingHorizontalScrollport(element)", script)
        self.assertIn("scrollportRect.right <= viewportWidth + 2", script)

    def test_shared_contrast_and_responsive_rules_cover_known_regressions(self):
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        root = css.split("}", 1)[0]
        amber_match = re.search(r"--amber:\s*(#[0-9a-fA-F]{6})", root)
        self.assertIsNotNone(amber_match)

        def luminance(hex_color):
            channels = [
                int(hex_color[index : index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(left, right):
            darker, lighter = sorted((luminance(left), luminance(right)))
            return (lighter + 0.05) / (darker + 0.05)

        self.assertGreaterEqual(contrast(amber_match.group(1), "#fff1d6"), 4.5)
        self.assertIn(".performance-card--primary > span { color: #fff; }", css)
        self.assertIn(
            ".holiday-calendar-day.is-outside { color: var(--muted);",
            css,
        )
        self.assertIn(
            ".guide-flow:focus-visible { outline: 3px solid var(--focus-ring);",
            css,
        )
        self.assertIn(
            ".inventory-table-wrap:focus-visible { "
            "outline: 3px solid var(--focus-ring);",
            css,
        )
        self.assertIn(
            ".master-filters.sales-source-filters { "
            "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); "
            "padding: 14px; }",
            css,
        )

    def test_floating_list_fixture_has_valid_alpha_option_and_a11y_check(self):
        fixture = Path("tests/browser/floating-lists.html").read_text(encoding="utf-8")
        script = Path("tests/browser/floating-lists.js").read_text(encoding="utf-8")

        self.assertNotIn("</option value=", fixture)
        self.assertIn('</option><option value="a">Alpha 測試車型</option>', fixture)
        self.assertIn("native.tabIndex === -1", script)
        self.assertIn("Alpha 選項可搜尋並寫回原欄位", script)

    def test_guide_flow_is_a_named_focusable_region(self):
        template = Path("templates/help/user_guide.html").read_text(encoding="utf-8")

        self.assertIn(
            'class="guide-flow" role="region" aria-label="建立訂單五個區塊" tabindex="0"',
            template,
        )
        self.assertIn('id="system-integrity"', template)
        self.assertIn("/system-status/", template)
        self.assertIn("/system/integrity-report/", template)
        self.assertIn("一般使用者不顯示入口", template)
        self.assertIn("報告不代表「全部安全」", template)
        self.assertIn("{% if request.user.is_superuser %}", template)


class UiAccessibilityRenderedPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="ui-accessibility-user",
            password="test-pass-123",
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_business_holiday_uses_controls_without_invalid_grid_roles(self):
        response = self.client.get(
            reverse("business_holiday_list"),
            {"view": "month", "month": "2026-09"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="holiday-calendar-grid" role="group"')
        self.assertNotContains(response, 'role="grid"')
        self.assertNotContains(response, 'role="columnheader"')
        self.assertNotContains(response, 'role="gridcell"')

    def test_inventory_quick_entry_labels_existing_and_dynamic_row_fields(self):
        response = self.client.get(reverse("inventory_quick_create"))

        self.assertEqual(response.status_code, 200)
        for field_name in (
            "vehicle_model",
            "color",
            "received_on",
            "manufactured_year_month",
            "condition_note",
        ):
            with self.subTest(field_name=field_name):
                self.assertContains(
                    response,
                    f'for="id_vehicles-0-{field_name}"',
                )
                self.assertContains(
                    response,
                    f'for="id_vehicles-__prefix__-{field_name}"',
                )
        self.assertContains(
            response,
            'class="visually-hidden identifier-label" for="id_vehicles-0-identifier"',
        )
        self.assertContains(
            response,
            'class="visually-hidden identifier-label" '
            'for="id_vehicles-__prefix__-identifier"',
        )

    def test_inventory_table_scroll_region_is_named_and_keyboard_focusable(self):
        response = self.client.get(reverse("inventory_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'class="inventory-table-wrap" tabindex="0" '
            'aria-label="車輛庫存清單，可左右捲動查看完整欄位"',
        )
