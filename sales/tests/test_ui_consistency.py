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


def css_declarations(text):
    """逐一產生 (選擇器堆疊, 屬性, 值)；支援 @media 等巢狀區塊。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    stack, selector, index = [], [], 0
    while index < len(text):
        char = text[index]
        if char == "{":
            stack.append("".join(selector).strip())
            selector = []
        elif char == "}":
            if stack:
                stack.pop()
            selector = []
        elif char == ";":
            selector = []
        elif stack and not stack[-1].startswith("@"):
            end = index
            while end < len(text) and text[end] not in ";}":
                end += 1
            declaration = text[index:end]
            if ":" in declaration:
                prop, value = declaration.split(":", 1)
                yield list(stack), prop.strip().lower(), value.strip()
            index = end
            continue
        else:
            selector.append(char)
        index += 1


class UiConsistencyTests(SimpleTestCase):
    def test_base_loads_single_global_stylesheet(self):
        base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
        head = base.split("</head>", 1)[0]

        self.assertEqual(re.findall(r"static '(css/[^']+)'", head), ["css/app.css"])
        for retired in ("ui-comfort", "site-review", "ppt-refinements", "account-workspace", "catalog-selection"):
            self.assertFalse((CSS_DIR / f"{retired}.css").exists(), retired)

    def test_home_screen_app_opens_fullscreen(self):
        import json

        head = (TEMPLATES / "base.html").read_text(encoding="utf-8").split("</head>", 1)[0]
        manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))

        self.assertIn("rel=\"manifest\" href=\"{% static 'manifest.webmanifest' %}\"", head)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', head)
        self.assertEqual((manifest["display"], manifest["start_url"], manifest["scope"]), ("fullscreen", "/", "/"))
        for icon in manifest["icons"]:
            self.assertTrue(Path(icon["src"].lstrip("/")).exists(), icon["src"])
        self.assertTrue({"192x192", "512x512"} <= {icon["sizes"] for icon in manifest["icons"]})

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

    def test_css_colors_use_tokens(self):
        """色碼只能出現在參數定義、主題區塊、主題預覽色塊與列印樣式。"""
        color = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            if path.name == "contract.css":
                continue
            for stack, prop, value in css_declarations(path.read_text(encoding="utf-8")):
                context = " ".join(stack)
                if prop.startswith("--") or "url(" in value:
                    continue
                if any(key in context for key in (":root", "data-theme", "theme-option__preview", "print")):
                    continue
                if color.search(value):
                    offenders.append(f"{path.name}: {stack[-1][:60]} {{ {prop}: {value[:60]} }}")

        self.assertEqual(offenders, [])

    def test_spacing_uses_scale_tokens(self):
        """padding／margin／gap 只能用間距刻度或角色參數；0–3px 細線與 64px 以上版面值除外。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        root = app.split("}", 1)[0]
        for token in ("--space-1", "--space-5", "--card-pad", "--inset-pad", "--bar-pad", "--stack-gap", "--stack-gap-sm"):
            self.assertIn(f"{token}:", root)
        prop = re.compile(r"^(padding|margin|gap|row-gap|column-gap)(-[a-z-]+)?$")
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            if path.name == "contract.css":
                continue
            for stack, name, value in css_declarations(path.read_text(encoding="utf-8")):
                if not prop.match(name) or any("print" in part for part in stack):
                    continue
                for size in re.findall(r"(?<![\w.(-])(\d+(?:\.\d+)?)(px|rem)\b", value):
                    px = float(size[0]) * (16 if size[1] == "rem" else 1)
                    if 3 < px <= 71 and "calc" not in value and "clamp" not in value and "min(" not in value:
                        offenders.append(f"{path.name}: {stack[-1][:50]} {{ {name}: {value[:40]} }}")

        self.assertEqual(offenders, [])

    def test_dropdowns_share_one_style(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn("select:not([multiple]):not([size]):not(.searchable-select__native) {", app)
        self.assertIn("--select-chevron: var(--forest);", app)
        self.assertIn("color: var(--select-chevron); background: transparent;", app)
        offenders = [
            f"{path}"
            for path in [*TEMPLATES.rglob("*.html"), *Path("static/js").glob("*.js")]
            if "⌄" in path.read_text(encoding="utf-8") or "▾" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_page_actions_live_in_hero(self):
        """頁面操作按鈕放在頁首 hero-actions，不放在返回列與頁首之間。"""
        offenders = []
        for name, text in template_files():
            start = re.search(r"{%\s*block (?:content|report_content)\s*%}", text)
            hero = re.search(r'class="[^"]*\bhero-row\b', text)
            if not start or not hero or hero.start() < start.end():
                continue
            between = re.sub(r'{%\s*include\s+"sales/_page_back.html"[^%]*%}|{%\s*site_navigation\s*%}', "", text[start.end():hero.start()])
            if re.search(r'class="(?:button|form-actions|hero-actions)\b', between):
                offenders.append(name)

        self.assertEqual(offenders, [])

    def test_textareas_use_form_control(self):
        """表單的 Textarea 一律帶 form-control（或由表單類別統一補上），模板手寫的 textarea 也要有 class。"""
        import ast

        offenders = []
        for path in sorted(Path("sales").rglob("*.py")):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "Textarea" not in source:
                continue
            tree = ast.parse(source)
            classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}

            def applies_form_control(node, seen=()):
                body = ast.get_source_segment(source, node) or ""
                if 'setdefault("class", "form-control")' in body:
                    return True
                for base in node.bases:
                    name = getattr(base, "id", None)
                    if name in classes and name not in seen:
                        if applies_form_control(classes[name], (*seen, name)):
                            return True
                return False

            for node in classes.values():
                if node.name == "Meta":
                    continue
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "Textarea":
                        text = ast.get_source_segment(source, call) or ""
                        if "form-control" not in text and not applies_form_control(node):
                            offenders.append(f"{path}:{call.lineno} {node.name}")
        for name, text in template_files():
            for match in re.finditer(r"<textarea(?![^>]*\bclass=)[^>]*>", text):
                offenders.append(f"{name}:{line_of(text, match.start())}")

        self.assertEqual(sorted(set(offenders)), [])

    def test_alignment_rules_exist(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn(".section-title { display: flex; min-height: 58px; padding: 0 var(--card-pad);", app)
        self.assertIn(".section-body { padding: var(--card-pad); }", app)
        self.assertIn("summary:not(:has(.ui-chevron)))::-webkit-details-marker { display: none; }", app)
        self.assertIn("#drafts .draft-row { display: grid;", app)

    def test_shell_widths_come_from_tokens(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertFalse(".page-shell { width: min(100% - 48px, 1560px)" in app)
        self.assertIn("--shell-wide: 1560px;", app)
        self.assertIn(".page-shell { width: min(100% - var(--shell-gutter), var(--shell-wide)); }", app)
