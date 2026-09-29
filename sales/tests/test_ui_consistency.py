"""全站 UI 規範的靜態檢查；規則見 docs/reference/UI_GUIDELINES.md。"""

import re
from pathlib import Path

from django.test import SimpleTestCase

TEMPLATES = Path("templates")
CSS_DIR = Path("static/css")
BUTTON_LEVELS = {"primary", "ghost", "secondary", "danger", "danger-outline"}
# 獨立版面：錯誤頁、登入、列印、說明手冊、公告閱讀、權限工作區與報表閱讀器。
HERO_EXEMPT = {
    "errors/400.html",
    "errors/403.html",
    "errors/404.html",
    "errors/500.html",
    "registration/login.html",
    "registration/password_change_required.html",
    "help/user_guide.html",
    "sales/announcement_detail.html",
    "sales/permissions/fixed.html",
    "sales/permissions/orders.html",
    "sales/reporting/display.html",
    "sales/reporting/layout.html",
}
# 同一表單有多個送出按鈕時，主要動作須是第一個送出按鈕（Enter 預設）。
ACTION_ORDER_EXEMPT = {"sales/site_copy_manage.html", "sales/order_deletion_confirm.html"}


def template_files():
    for path in sorted(TEMPLATES.rglob("*.html")):
        yield path.relative_to(TEMPLATES).as_posix(), path.read_text(encoding="utf-8")


def expand_includes(text, depth=0):
    if depth > 3:
        return text
    for name in re.findall(r"{%\s*include\s+[\"']([^\"']+)[\"']", text):
        path = TEMPLATES / name
        if path.exists():
            text += expand_includes(path.read_text(encoding="utf-8"), depth + 1)
    return text


def line_of(text, index):
    return text.count("\n", 0, index) + 1


class UiConsistencyTests(SimpleTestCase):
    def test_base_loads_single_global_stylesheet(self):
        base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
        head = base.split("</head>", 1)[0]

        self.assertEqual(re.findall(r"static '(css/[^']+)'", head), ["css/app.css"])
        for retired in ("ui-comfort", "site-review", "ppt-refinements", "account-workspace", "catalog-selection"):
            self.assertFalse((CSS_DIR / f"{retired}.css").exists(), retired)

    def test_confirmations_use_shared_data_confirm(self):
        offenders = [
            f"{name}:{line_of(text, match.start())}"
            for name, text in template_files()
            for match in re.finditer(r"on(?:submit|click)=\"[^\"]*confirm\(|data-confirm-form", text)
        ]

        self.assertEqual(offenders, [])

    def test_every_button_declares_a_level(self):
        offenders = []
        for name, text in template_files():
            for match in re.finditer(r'class="(button(?:\s[^"]*)?)"', text):
                raw = match.group(1)
                if "{{" in raw:
                    continue
                classes = set(re.sub(r"{%.*?%}", " ", raw).split())
                if not classes & BUTTON_LEVELS or classes & {"danger-ghost", "text"}:
                    offenders.append(f"{name}:{line_of(text, match.start())} [{raw}]")

        self.assertEqual(offenders, [])

    def test_scripts_do_not_create_unleveled_buttons(self):
        offenders = []
        for path in sorted(Path("static/js").glob("*.js")):
            for match in re.finditer(r"className\s*=\s*['\"](button(?:\s[^'\"]*)?)['\"]", path.read_text(encoding="utf-8")):
                if not set(match.group(1).split()) & BUTTON_LEVELS:
                    offenders.append(f"{path.name}: {match.group(1)}")

        self.assertEqual(offenders, [])

    def test_back_navigation_uses_shared_partial(self):
        offenders = [
            f"{name}:{line_of(text, match.start())}"
            for name, text in template_files()
            if name not in {"sales/_page_back.html", "sales/contract_print.html"}
            for match in re.finditer(r'class="(?:back-link|permission-back)"|<a\b[^>]*>\s*←', text)
        ]

        self.assertEqual(offenders, [])

    def test_pages_use_standard_hero_header(self):
        pattern = re.compile(
            r'class="[^"]*\bhero-row\b[^"]*\bcompact-hero\b[^"]*"[^>]*>\s*(?:<div[^>]*>\s*)?'
            r'(?:<p class="eyebrow"[^>]*>.*?</p>\s*)?<h1',
            re.S,
        )
        missing = []
        for name, text in template_files():
            if Path(name).name.startswith("_") or name == "base.html" or name in HERO_EXEMPT:
                continue
            if not re.search(r"{%\s*extends", text):
                continue
            if not pattern.search(expand_includes(text)):
                missing.append(name)

        self.assertEqual(missing, [])

    def test_primary_action_is_last_in_action_rows(self):
        offenders = []
        row = re.compile(r'class="(?:form-actions|hero-actions|inventory-filter-actions|catalog-manage-actions|report-actions)[^"]*"')
        for name, text in template_files():
            if name in ACTION_ORDER_EXEMPT:
                continue
            for match in row.finditer(text):
                segment = text[match.end():match.end() + 2500]
                end = segment.find("</div>")
                levels = re.findall(r'class="button ([\w-]+)', segment[: end if end > 0 else 800])
                if "primary" in levels and levels[-1] != "primary":
                    offenders.append(f"{name}:{line_of(text, match.start())} {levels}")

        self.assertEqual(offenders, [])

    def test_css_uses_radius_and_type_scale(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        root = app.split("}", 1)[0]
        for token in ("--radius-sm", "--radius-md", "--radius-lg", "--radius-pill", "--text-xs", "--text-sm", "--text-base", "--text-xl"):
            self.assertIn(f"{token}:", root)

        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            if path.name == "contract.css":
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"border-radius:\s*([^;}]+)", text):
                for part in match.group(1).replace("!important", "").split():
                    size = re.fullmatch(r"(\d+)px", part)
                    if size and 4 <= int(size.group(1)) <= 24:
                        offenders.append(f"{path.name}: border-radius {match.group(1).strip()}")
            for match in re.finditer(r"font-size:\s*([^;}]+)", text):
                value = match.group(1).replace("!important", "").strip()
                size = re.fullmatch(r"(\d*\.?\d+)(rem|px)", value)
                if size and 0 < float(size.group(1)) / (16 if size.group(2) == "px" else 1) <= 2.35:
                    offenders.append(f"{path.name}: font-size {value}")

        self.assertEqual(offenders, [])

    def test_shell_widths_come_from_tokens(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertFalse(".page-shell { width: min(100% - 48px, 1560px)" in app)
        self.assertIn("--shell-wide: 1560px;", app)
        self.assertIn(".page-shell { width: min(100% - var(--shell-gutter), var(--shell-wide)); }", app)
