"""T-193：套表列印頁的「列印清單」改成最左側可收合的窄條（同報表左側收合 T-181），收合後訂單表格吃滿寬度。"""
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from sales.tests import test_order_lifecycle as lifecycle


ROOT = Path(settings.BASE_DIR)


class FormPrintTrayDockTests(TestCase):
    make_order = lifecycle.OrderLifecycleTests.make_order

    def setUp(self):
        lifecycle.OrderLifecycleTests.setUp(self)
        self.make_order(deposit=Decimal("5000"))
        self.client.force_login(self.user)

    def page(self):
        return self.client.get(reverse("form_print")).content.decode()

    def test_tray_moves_to_left_dock_before_the_order_table(self):
        html = self.page()
        layout = html[html.index("data-form-print"):]
        # 最左側先是窄條＋面板，訂單表格在右邊。
        self.assertLess(layout.index("data-tray-dock"), layout.index("form-print__finder"))
        rail = re.search(r"<button[^>]*data-tray-rail[^>]*>", html).group(0)
        self.assertIn('type="button"', rail)
        self.assertIn('aria-controls="form-print-tray-panel"', rail)
        self.assertIn("aria-expanded=", rail)
        close = re.search(r"<button[^>]*data-tray-close[^>]*>", html).group(0)
        self.assertIn('aria-controls="form-print-tray-panel"', close)
        self.assertIn('aria-label="收合列印清單"', close)
        self.assertIn('id="form-print-tray-panel" data-tray-panel', html)
        self.assertIn("js/form-print-tray.js", html)
        # 收合時窄條上也看得到份數：視覺徽章＋報讀文字。
        self.assertIn('data-rail-badge><b data-rail-count>0</b><small>份</small>', html)
        self.assertIn('<span class="visually-hidden">，已勾選 <span data-rail-count>0</span> 份</span>', html)
        # 舊的底部「前往列印」捷徑已由窄條取代；空狀態不再說「左邊表格」。
        self.assertNotIn("data-dock-count", html)
        self.assertNotIn("在左邊表格", html)
        self.assertIn("在訂單表格勾選要印的套表", html)

    def test_existing_print_flow_stays_inside_the_panel(self):
        html = self.page()
        panel = html[html.index('id="form-print-tray-panel"'):html.index("data-tray-backdrop")]
        form = re.search(r"<form[^>]*data-tray-form[^>]*>", panel, flags=re.S).group(0)
        self.assertIn(f'action="{reverse("form_print_pdf")}"', form)
        self.assertIn(f'data-preview-url="{reverse("form_print_preview")}"', form)
        self.assertIn("csrfmiddlewaretoken", panel)
        for needle in ("data-total", "data-papers", "data-empty", "data-list", 'name="group" value="form"',
                       "data-preview-open", "data-clear", "data-submit-envelope-pdf", "data-submit-envelope", "data-submit disabled"):
            self.assertIn(needle, panel)
        # 表格勾選還在右邊的訂單表格裡。
        finder = html[html.index("form-print__finder"):]
        self.assertIn("data-row-pick", finder)
        self.assertIn('data-form="envelope"', finder)

    def test_styles_push_table_stick_and_slide_over_on_phone(self):
        css = (ROOT / "static/css/form-print.css").read_text(encoding="utf-8")
        self.assertIn(".form-print { display: grid; grid-template-columns: auto minmax(0, 1fr);", css)
        self.assertNotIn("form-print__dock", css)
        block = css[css.index("/* ── 列印清單左側收合（T-193）"):]
        self.assertIn("position: sticky; top: var(--tray-top);", block)
        self.assertIn("--tray-top: calc(var(--app-header-height, 72px) + var(--space-4));", block)
        self.assertIn(".form-print__tray-panel.is-open { width: var(--tray-w); margin-inline-start: var(--space-3); visibility: visible;", block)
        self.assertIn(".form-print__rail:focus-visible, .form-print__tray-close:focus-visible { outline: 2px solid var(--focus-ring);", block)
        self.assertIn("display: grid; width: var(--tray-w); max-height: var(--tray-h);", css)
        phone = block[block.index("@media (max-width: 800px)"):block.index("@keyframes form-print-fade")]
        self.assertIn("position: fixed; inset: var(--app-header-height, 62px) auto 0 0;", phone)
        self.assertIn("transform: translateX(-100%);", phone)
        self.assertIn("var(--mobile-nav-height, 72px)", phone)
        self.assertIn("html.form-print-tray-locked { overflow: hidden; }", phone)
        motion = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .form-print__item"):]
        self.assertIn(".form-print__tray-panel, .form-print__tray-close { transition: none; }", motion)

    def test_scripts_remember_state_and_update_rail_count(self):
        dock = (ROOT / "static/js/form-print-tray.js").read_text(encoding="utf-8")
        for needle in ("FORM_PRINT_TRAY_KEY = 'dmis.formPrintTray'", "try { return window.localStorage; } catch",
                       "matchMedia('(max-width: 800px)')", "matchMedia('(min-width: 1100.02px)')",
                       "if (!overlay.matches) formPrintTrayWrite(storage(), open);",
                       "event.key !== 'Escape'", "document.querySelector('dialog[open]')"):
            self.assertIn(needle, dock)
        main = (ROOT / "static/js/form-print.js").read_text(encoding="utf-8")
        self.assertIn('railCounts.forEach((node) => { node.textContent = total; });', main)
        self.assertNotIn("data-dock", main)

    def test_storage_helpers_fall_back_safely(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("本機沒有 node")
        script = (ROOT / "static/js/form-print-tray.js").as_posix()
        code = f"""
const m = require({script!r});
const store = {{}}; const ok = {{getItem: k => store[k] ?? null, setItem: (k, v) => {{ store[k] = v; }}}};
const broken = {{getItem() {{ throw new Error('blocked'); }}, setItem() {{ throw new Error('blocked'); }}}};
const out = [m.formPrintTrayRead(ok), m.formPrintTrayWrite(ok, false), m.formPrintTrayRead(ok), m.formPrintTrayWrite(ok, true),
  m.formPrintTrayRead(ok), m.formPrintTrayRead(broken), m.formPrintTrayWrite(broken, true), m.formPrintTrayRead(null)];
console.log(JSON.stringify(out));
"""
        result = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(result.stdout.strip(), "[null,true,false,true,true,null,false,null]")
