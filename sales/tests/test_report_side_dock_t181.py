"""T-181：報表中心報表頁的「報表頁面」「車型篩選」都收成左側窄標籤，可各自展開。"""
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.views import initial_config


ROOT = Path(settings.BASE_DIR)


class SideDockTests(TestCase):
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

    def page(self, report):
        return self.client.get(reverse("report_display", args=[report.pk])).content.decode()

    @staticmethod
    def dock(html):
        start = html.index("data-report-side-dock")
        return html[start:html.index('<div class="report-reader-main', start)]

    def test_dock_sits_left_of_report_with_collapsed_rails_and_panels(self):
        html = self.page(self.analysis)
        self.assertIn('<div class="report-reader-layout has-side-dock">', html)
        self.assertNotIn("has-tree-filter", html)
        dock = self.dock(html)
        rails = re.findall(r'<button[^>]*data-side-rail="(\w+)"[^>]*>', dock)
        self.assertEqual(rails, ["pages", "tree"])  # 一上一下：報表頁面在上、車型篩選在下
        for name in ("pages", "tree"):
            rail = re.search(rf'<button[^>]*data-side-rail="{name}"[^>]*>', dock).group(0)
            self.assertIn('type="button"', rail)
            self.assertIn('aria-expanded="false"', rail)  # 預設收合
            self.assertIn(f'aria-controls="report-{name}-panel"', rail)
            self.assertIn(f'id="report-{name}-panel" data-side-panel="{name}"', dock)
            close = re.search(rf'<button[^>]*data-side-close="{name}"[^>]*>', dock).group(0)
            self.assertIn(f'aria-controls="report-{name}-panel"', close)
            self.assertIn("aria-expanded=", close)
        # 兩個都開時由左到右：報表頁面 → 車型篩選；報表內容在 dock 之後。
        self.assertLess(dock.index('data-side-panel="pages"'), dock.index('data-side-panel="tree"'))
        self.assertIn('aria-label="報表頁面"', dock)
        self.assertIn("data-report-tree", dock)
        self.assertNotIn("data-reader-pages", html)
        # 車型篩選窄標籤顯示已選數量（視覺徽章＋報讀文字），沿用 report-tree-filter.js 的更新。
        self.assertIn('class="report-side-rail__badge" aria-hidden="true" data-report-tree-rail-badge', dock)
        self.assertIn('<span class="sr-only">，<span data-report-tree-rail-count></span></span>', dock)

    def test_reader_page_drops_right_panel_controls(self):
        html = self.page(self.analysis)
        self.assertEqual(html.count("data-report-tree "), 1)
        for needle in ("data-report-tree-collapse", "data-report-tree-drawer", 'class="report-tree-filter__rail"'):
            self.assertNotIn(needle, html)

    def test_only_tree_reports_get_second_rail(self):
        html = self.page(self.sales)
        dock = self.dock(html)
        self.assertEqual(re.findall(r'data-side-rail="(\w+)"', dock), ["pages"])
        self.assertNotIn("report-tree-panel", html)
        self.assertNotIn("data-report-tree", html)
        self.assertIn('aria-current="page"', dock)

    def test_payout_page_keeps_existing_navigation(self):
        html = self.client.get(reverse("dealer_payout_list")).content.decode()
        self.assertIn('<aside class="report-page-nav"><details open data-reader-pages>', html)
        self.assertNotIn("data-report-side-dock", html)

    def test_styles_cover_push_sticky_overlay_and_motion(self):
        css = (ROOT / "static/css/reporting.css").read_text(encoding="utf-8")
        block = css[css.index("/* 報表中心報表頁左側收合（T-181）"):]
        self.assertIn(".report-reader-shell .report-workspace .report-reader-layout.has-side-dock { grid-template-columns: auto minmax(0, 1fr);", block)
        self.assertIn("position: sticky; top: var(--dock-top);", block)
        self.assertIn("--dock-top: calc(var(--app-header-height, 72px) + var(--space-4));", block)
        self.assertIn("max-height: var(--dock-h);", block)
        # 捲到頁底時 dock 仍完整停在頁首下方：頁底留白併進報表欄。
        self.assertIn("--dock-tail: 170px; margin-bottom: calc(-1 * var(--dock-tail));", block)
        self.assertIn(".report-side-rail:focus-visible, .report-side-panel__close:focus-visible { outline: 2px solid var(--focus-ring);", block)
        phone = block[block.index("@media (max-width: 800px)"):block.index("@keyframes report-side-fade")]
        self.assertIn("position: fixed; inset: var(--app-header-height, 62px) auto 0 0;", phone)
        self.assertIn("transform: translateX(-100%);", phone)
        self.assertIn("min(340px, calc(100vw - var(--space-7)))", phone)
        self.assertIn("@media (prefers-reduced-motion: reduce) { .report-side-rail,", block)
        self.assertIn("@media print { .report-side-dock { display: none !important; } }", block)

    def test_script_remembers_state_safely_and_supports_escape(self):
        script = (ROOT / "static/js/report-side-dock.js").read_text(encoding="utf-8")
        for needle in ("try { return window.localStorage; } catch", "matchMedia('(max-width: 800px)')",
                       "event.key !== 'Escape'", "backdrop?.addEventListener('click', closeOverlay)",
                       "if (!overlay.matches) reportSideDockWrite(storage(), state);",
                       "window.dispatchEvent(new Event('resize'))"):
            self.assertIn(needle, script)
        tree = (ROOT / "static/js/report-tree-filter.js").read_text(encoding="utf-8")
        self.assertIn("const docked = root.closest('[data-report-side-dock]');", tree)
        self.assertIn("if (!docked) {", tree)

    def test_storage_helpers_default_to_collapsed(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("本機沒有 node")
        script = (ROOT / "static/js/report-side-dock.js").as_posix()
        code = f"""
const m = require({script!r});
const store = {{}}; const ok = {{getItem: k => store[k] ?? null, setItem: (k, v) => {{ store[k] = v; }}}};
const broken = {{getItem() {{ throw new Error('blocked'); }}, setItem() {{ throw new Error('blocked'); }}}};
const out = [m.reportSideDockRead(ok), m.reportSideDockWrite(ok, {{pages: true, tree: false}}), m.reportSideDockRead(ok),
  m.reportSideDockRead(broken), m.reportSideDockWrite(broken, {{pages: true}}), m.reportSideDockRead(null)];
console.log(JSON.stringify(out));
"""
        result = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(result.stdout.strip(), '[{"pages":false,"tree":false},true,{"pages":true,"tree":false},'
                                                '{"pages":false,"tree":false},false,{"pages":false,"tree":false}]')
