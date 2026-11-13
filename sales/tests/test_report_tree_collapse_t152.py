"""T-152：大數據分析的車型篩選在寬螢幕可向右收合，放大報表區。"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.views import initial_config


ROOT = Path(settings.BASE_DIR)


class TreeCollapseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        SalesOrder.objects.create(source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, 3),
            owner_type="company", owner_name="合成車主", owner_id_number="83739807", vehicle_model=model,
            color=VehicleColor.objects.create(vehicle_model=model, name="白"), vehicle_price=10000, actual_balance=10000,
            calculated_balance=10000, payment_type="cash", status="completed")
        analysis = {**initial_config(), "audience": "team", "navigation_group": "analysis", "reader_layout": "analysis_overview"}
        sales = {**initial_config(), "audience": "team", "navigation_group": "sales"}
        cls.analysis = ReportDefinition.objects.create(draft=analysis, published=analysis, version=1)
        cls.sales = ReportDefinition.objects.create(draft=sales, published=sales, version=1)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_panel_has_keyboard_collapse_button_and_rail(self):
        html = self.client.get(reverse("report_display", args=[self.analysis.pk])).content.decode()
        collapse = re.search(r'<button[^>]*data-report-tree-collapse[^>]*>', html).group(0)
        rail = re.search(r'<button[^>]*data-report-tree-rail[^>]*>', html).group(0)
        for button, expanded in ((collapse, "true"), (rail, "false")):
            self.assertIn('type="button"', button)
            self.assertIn('aria-controls="report-tree-body"', button)
            self.assertIn(f'aria-expanded="{expanded}"', button)
        self.assertIn('aria-label="向右收合車型篩選，放大報表"', collapse)
        self.assertIn(">車型篩選</span>", html)
        self.assertIn("data-report-tree-rail-count", html)

    def test_other_groups_have_no_collapse_controls(self):
        html = self.client.get(reverse("report_display", args=[self.sales.pk])).content.decode()
        self.assertNotIn("data-report-tree-collapse", html)
        self.assertNotIn("data-report-tree-rail", html)

    def test_collapse_only_on_wide_screens_and_respects_reduced_motion(self):
        css = (ROOT / "static/css/reporting.css").read_text(encoding="utf-8")
        block = css[css.index("/* 寬螢幕向右收合（T-152）"):]
        wide = block[block.index("@media (min-width: 1280.02px)"):block.index("@media (prefers-reduced-motion")]
        self.assertIn(".report-tree-filter__collapse, .report-tree-filter__rail { display: none; }", block.split("@media")[0])
        self.assertIn(".report-reader-layout.has-tree-filter.is-tree-collapsed { grid-template-columns: 240px minmax(0, 1fr) 56px; }", wide)
        self.assertIn("transition: grid-template-columns", wide)
        self.assertIn(".report-reader-layout.has-tree-filter, .report-tree-filter__collapse, .report-tree-filter__rail { transition: none; }", block)
        script = (ROOT / "static/js/report-tree-filter.js").read_text(encoding="utf-8")
        for needle in ("reportTreeReadCollapsed(storage())", "window.dispatchEvent(new Event('resize'))",
                       "prefers-reduced-motion: reduce", "try { return window.localStorage; } catch"):
            self.assertIn(needle, script)
