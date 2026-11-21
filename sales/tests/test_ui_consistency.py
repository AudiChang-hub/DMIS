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
    "errors/csrf.html",
    "registration/login.html",
    "registration/password_change_required.html",
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

    def test_home_screen_app_opens_standalone(self):
        import json

        head = (TEMPLATES / "base.html").read_text(encoding="utf-8").split("</head>", 1)[0]
        manifest = json.loads(Path("static/manifest.webmanifest").read_text(encoding="utf-8"))

        self.assertIn("rel=\"manifest\" href=\"{% static 'manifest.webmanifest' %}\"", head)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', head)
        self.assertEqual((manifest["display"], manifest["start_url"], manifest["scope"]), ("standalone", "/", "/"))
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
        self.assertIn("--select-chevron: var(--ink-soft);", app)
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

    def test_confirm_pages_share_confirm_panel(self):
        """獨立確認頁共用 confirm-panel 結構，提示用 callout，勾選確認用 check-row。"""
        confirm_pages = [
            "order_deletion_confirm", "dealer_volume_bonus_confirm_delete", "sales_source_confirm_delete",
            "announcement_action", "historical_date_change", "historical_buyer_replacement",
            "print_company_missing", "inventory_restore", "order_return",
        ]
        offenders = []
        for name in confirm_pages:
            text = (TEMPLATES / "sales" / f"{name}.html").read_text(encoding="utf-8")
            if "section-block confirm-panel" not in text or "confirm-panel__actions" not in text:
                offenders.append(f"{name}: 缺少 confirm-panel 結構")
            if re.search(r'type="checkbox"|_field\.html" with field=form\.(?:confirmed|acknowledged|\w+_confirmed)', text) and "check-row" not in text:
                offenders.append(f"{name}: 勾選確認未用 check-row")
            if re.search(r'class="[^"]*(?:replacement-panel|source-delete|bonus-delete-notice|import-review-summary)', text):
                offenders.append(f"{name}: 仍使用舊的專用提示框")

        self.assertEqual(offenders, [])

    def test_data_tables_share_inventory_table(self):
        """資料表格一律用 inventory-table；列印文件、報表閱讀器與拖曳排序表為例外。"""
        exempt = {"sales/contract_print.html", "sales/price_list_distribution_assignments.html"}
        offenders = []
        for name, text in template_files():
            if name in exempt:
                continue
            for match in re.finditer(r"<table\b[^>]*>", text):
                tag = match.group(0)
                if "report-results" in tag or "inventory-table" in tag:
                    continue
                offenders.append(f"{name}:{line_of(text, match.start())}")
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertEqual(offenders, [])
        for retired in (".recycle-table", ".command-trend-table", ".data-table", ".responsive-table-wrap"):
            self.assertNotIn(retired, app)

    def test_forms_share_fields_and_savebar(self):
        """表單不用 as_p 系列輸出；長表單只用 form-savebar，舊的各式儲存列樣式不得再出現。"""
        offenders = []
        for name, text in template_files():
            for match in re.finditer(r"\.as_(?:p|table|div|ul)\b", text):
                offenders.append(f"{name}:{line_of(text, match.start())}")
        css = "\n".join(path.read_text(encoding="utf-8") for path in CSS_DIR.glob("*.css"))

        self.assertEqual(offenders, [])
        self.assertIn(".form-savebar { position: sticky;", css)
        for retired in (".master-model-actions {", ".dealer-reward-actions {", ".bonus-save-bar {", ".account-savebar{", ".vehicle-model-save-actions {"):
            self.assertNotIn(retired, css)
        self.assertNotIn(".standalone-form { max-width: 860px; margin-inline: auto; }", css)
        for name in ("dealer_volume_bonus_form", "vehicle_model_form", "incentive_campaign_form", "dealer_reward_campaign_form",
                     "settlement_cost_rule_form", "dealer_reward_catalog_form"):
            self.assertIn("form-savebar", (TEMPLATES / "sales" / f"{name}.html").read_text(encoding="utf-8"), name)

    def test_filter_bar_fits_medium_screens(self):
        """中等寬度下篩選列改為四欄，避免 7 欄最小寬度撐出卡片（1024px 筆電）。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn("@media (min-width: 860.02px) and (max-width: 1360px) {\n  .inventory-filters:not(.customer-filters) { grid-template-columns: repeat(4, minmax(0, 1fr)); }", app.replace("\r\n", "\n"))

    def test_data_menu_keeps_hover_bridge(self):
        """資料維護選單的按鈕與展開選單之間有空隙，必須有懸停橋，否則滑鼠移過去選單就收起、點不到。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn(".desktop-data-menu:hover > a::after { position: absolute; top: 100%;", app)

    def test_data_menu_vehicle_group_order(self):
        """資料維護選單「車輛與商品」順序：品牌→機種與售價→庫存→配件與工資→原廠車型比對（使用者 2026-11-13）。"""
        base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
        group = base.split('<h2 id="data-menu-vehicles">', 1)[1].split("</section>", 1)[0]
        labels = re.findall(r"<strong>([^<]+)</strong>", group)

        # T-205：結算成本搬進機種與售價；「機種與售價・結算成本」只給沒有機種權限、有成本權限的人。
        self.assertEqual(labels, ["車輛品牌", "機種與售價", "機種與售價・結算成本", "車輛庫存", "配件與工資", "原廠車型比對"])

    def test_header_nav_fits_medium_screens(self):
        """861–1100px 導覽膠囊要收窄，且基礎內距規則必須在它之前，否則頁首會超出畫面。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8").replace("\r\n", "\n")
        base = ".desktop-nav > a, .desktop-data-menu > a { display: grid; place-items: center; min-height: 36px; padding: 0 var(--space-4);"
        narrow = "@media (min-width: 860.02px) and (max-width: 1100px) {\n    .desktop-nav > a, .desktop-data-menu > a { padding-inline: var(--space-2); }"

        self.assertIn(base, app)
        self.assertIn(narrow, app)
        self.assertLess(app.index(base), app.index(narrow))
        self.assertIn("@media (min-width: 860.02px) and (max-width: 900px) {\n    .app-header { padding-inline: var(--space-2); }\n    .brand { padding-right: 0; }", app)
        self.assertEqual(app.count(".desktop-nav > a, .desktop-data-menu > a {"), 2)

    def test_table_spans_do_not_reveal_both_compact_texts(self):
        """表格內 span 的區塊顯示不可套到寬版／窄版文字，否則機種、備註會同時顯示兩次。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn(".inventory-table td span:not(.compact-text-wide, .compact-text-narrow) { display: block; }", app)
        self.assertNotIn(".inventory-table td span { display: block; }", app)

    def test_breakpoints_have_no_gap(self):
        """max-width: N 與 min-width: N+1 之間會漏掉 Windows 縮放產生的小數寬度（例如 860.5px），兩邊規則都不套用。"""
        for path in CSS_DIR.glob("*.css"):
            css = path.read_text(encoding="utf-8")
            max_widths = {int(n) for n in re.findall(r"max-width: ?(\d+)px", css)}
            gaps = sorted(n - 1 for n in map(int, re.findall(r"min-width: ?(\d+)px", css)) if n - 1 in max_widths)
            self.assertEqual(gaps, [], f"{path.name} 斷點 {gaps} 請改用 min-width: N.02px")

    def test_alignment_rules_exist(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn(".section-title { display: flex; min-height: 58px; padding: 0 var(--card-pad);", app)
        self.assertIn(".section-body { padding: var(--card-pad); }", app)
        self.assertIn("summary:not(:has(.ui-chevron)))::-webkit-details-marker { display: none; }", app)
        self.assertIn("#drafts .draft-row { display: grid;", app)
        # 手機底部「更多」不套全站展開箭頭，避免多出 V 與錯位。
        self.assertEqual(app.count("report-multiselect, .mobile-data-menu)) > :where(summary"), 4)

    def test_shell_widths_come_from_tokens(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertFalse(".page-shell { width: min(100% - 48px, 1560px)" in app)
        self.assertIn("--shell-wide: 1560px;", app)
        self.assertRegex(app, r"\.page-shell \{[^}]*width: min\(100% - var\(--shell-gutter\), var\(--shell-wide\)\);")


class NumberWheelGuardTests(SimpleTestCase):
    def test_number_inputs_ignore_mouse_wheel(self):
        # 1.70.2：數字欄位不跟著滑鼠滾輪改值；全站共用 form-feedback.js（base.html 載入）。
        script = Path("static/js/form-feedback.js").read_text(encoding="utf-8")
        self.assertIn('document.addEventListener("wheel"', script)
        self.assertIn('input.type === "number"', script)
        self.assertIn("form-feedback.js", (TEMPLATES / "base.html").read_text(encoding="utf-8"))


class MobileUatLayoutTests(SimpleTestCase):
    """上線前驗收（UAT 2026-11）手機版面：U-07 水平捲動、U-12 步驟把手與刪除按鈕太近。"""

    HANDLES = (
        ("app.css", "side-nav"),
        ("order-steps.css", "order-nav"),
        ("vehicle-model-workspace.css", "model-nav"),
    )

    @staticmethod
    def mobile_block(css, start="@media (max-width: 860px) {"):
        """回傳檔案中每個 860px 以下區塊的內容（到對應的右括號為止）。"""
        blocks = []
        for match in re.finditer(re.escape(start), css):
            depth, index = 1, match.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(css[index], 0)
                index += 1
            blocks.append(css[match.end():index - 1])
        return "\n".join(blocks)

    def test_step_handles_move_to_header_on_phones(self):
        """手機的步驟把手要至少 44px 高、放在頁首左側，不能再留在左下角貼著底部按鈕。"""
        for filename, name in self.HANDLES:
            mobile = self.mobile_block((CSS_DIR / filename).read_text(encoding="utf-8").replace("\r\n", "\n"))
            rule = re.search(rf"\n  \.{name}__handle \{{([^}}]*)\}}", mobile)
            self.assertIsNotNone(rule, f"{filename} 缺少手機版 .{name}__handle")
            self.assertIn("min-height: 44px", rule.group(1))
            self.assertIn("var(--nav-handle-width", rule.group(1))
            self.assertIn("var(--app-header-height", rule.group(1))
            self.assertNotIn("bottom: calc(", rule.group(1))
            self.assertIn(f".{name}.is-open .{name}__handle {{ transform: none;", mobile)
            self.assertIn(f".{name}__close {{ width: 44px; min-height: 44px; }}", mobile)
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        # 頁首品牌讓位給把手；品牌文字只做視覺隱藏，連結仍有可讀名稱。
        self.assertIn("min-width: 44px; margin-left: calc(var(--nav-handle-width) + var(--space-3));", app)
        self.assertRegex(app, r"\.brand-copy \{\s*position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect\(0 0 0 0\);")
        self.assertIn('class="brand-copy"', (TEMPLATES / "base.html").read_text(encoding="utf-8"))

    def test_delete_button_keeps_distance_in_mobile_action_bar(self):
        """手機操作列的刪除類按鈕不換行，與其他按鈕的間距補到 16px（列本身的間距是 --stack-gap-sm）。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn(
            ".mobile-submit .button.danger-outline { flex: 0 0 auto; margin-right: max(0px, var(--space-4) - var(--stack-gap-sm)); white-space: nowrap; }",
            app,
        )

    def test_phone_layout_cannot_scroll_sideways(self):
        """U-07：底部導覽欄寬可縮、選車卡價格窄卡改上下排、檔案上傳框不超過欄寬。"""
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")

        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", app)
        self.assertNotIn("grid-template-columns: repeat(5, 1fr);", app)
        self.assertIn(".catalog-card { container: catalog-card / inline-size; }", app)
        self.assertIn("@container catalog-card (max-width: 280px) {", app)
        self.assertIn(':where(main) input[type="file"] { max-width: 100%; }', app)

    def test_layout_audit_reports_page_overflow(self):
        """?ui_audit=1 要檢查整頁 scrollWidth，並列出最內層的超出元素（排除跟著被撐寬的固定定位導覽）。"""
        script = Path("static/js/layout-audit.js").read_text(encoding="utf-8")

        self.assertIn("document.documentElement.scrollWidth - viewportWidth", script)
        self.assertIn('getComputedStyle(element).position === "fixed"', script)
        self.assertIn('element.closest(".mobile-nav")', script)
        self.assertIn("頁面水平溢出", script)


class MobileFoundationTests(SimpleTestCase):
    """T-226：iPhone 操作卡頓與版面。共用規則只寫在 860px／600px 以下，桌面版不變。"""

    app = (CSS_DIR / "app.css").read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_phone_inputs_never_trigger_ios_zoom(self):
        """iOS 欄位字級低於 16px 點下去會放大畫面；元件常以 font: inherit 繼承 13–14px 標籤字級，所以手機強制 16px。"""
        mobile = MobileUatLayoutTests.mobile_block(self.app)
        self.assertIn("select, textarea) { font-size: var(--text-base) !important; }", mobile)

    def test_phone_fields_and_buttons_share_control_height(self):
        mobile = MobileUatLayoutTests.mobile_block(self.app)
        self.assertIn("--control-h: 44px;", self.app.split("}", 1)[0])
        self.assertIn(".order-filter-bar :is(input, select), .order-filter-submit) { min-height: var(--control-h);", mobile)

    def test_phone_button_groups_fill_rows_evenly(self):
        """頁首按鈕群組每顆至少半列寬，放不下半列就自己滿寬一列，不再依字數長短參差排列。"""
        phone = MobileUatLayoutTests.mobile_block(self.app, "@media (max-width: 600px) {")
        rule = re.search(r":is\(\.hero-actions > \.button, [^{]*\) \{([^}]*)\}", phone)
        self.assertIsNotNone(rule)
        self.assertIn("flex: 1 1 calc(50% - var(--space-3) / 2);", rule.group(1))
        self.assertIn("min-height: var(--control-h);", rule.group(1))
        self.assertIn("white-space: nowrap;", rule.group(1))

    def test_phone_wrapping_rules(self):
        mobile = MobileUatLayoutTests.mobile_block(self.app)
        self.assertIn("main :is(h1, h2, h3) { text-wrap: balance; }", mobile)
        self.assertIn("main :is(p, li, dd) { text-wrap: pretty; }", mobile)
        # 中文沒有空格，keep-all 會讓整句無法斷行；只允許很短、以空白分段的「目前排序」一行（T-241）。
        self.assertEqual(re.findall(r"([^{}\n]*)\{[^}]*keep-all", self.app), ["    .order-sort-controls p "])

    def test_phone_skips_glass_and_entry_motion(self):
        """手機頁首、底部導覽、精靈底部列、訂單精簡列不用毛玻璃；換頁進場動畫與跨頁轉場只在桌面。"""
        mobile = MobileUatLayoutTests.mobile_block(self.app)
        for selector in (".app-header", ".form-progress", ".mobile-submit"):
            rule = re.search(rf"\n  {re.escape(selector)} \{{([^}}]*)\}}", mobile)
            self.assertIsNotNone(rule, selector)
            self.assertIn("backdrop-filter: none;", rule.group(1))
        self.assertNotRegex(self.app, r"\.mobile-nav \{[^}]*blur\(")
        workspace = (CSS_DIR / "order-workspace.css").read_text(encoding="utf-8")
        self.assertIn(".order-compact-bar { background: var(--paper); -webkit-backdrop-filter: none; backdrop-filter: none; }", MobileUatLayoutTests.mobile_block(workspace))
        self.assertIn("@media (min-width: 860.02px) { @view-transition { navigation: auto; } }", self.app)
        self.assertEqual(self.app.count("@view-transition"), 1)
        self.assertIn("@media (prefers-reduced-motion: reduce), (max-width: 860px) {\n  main, .hero-row { animation: none; }", self.app)


def phone_blocks(css):
    """回傳 860px 以下（含 600px 等更窄斷點）每個 @media 區塊的內容，註解先拿掉。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"@media\s*\(\s*max-width:\s*(\d+)(?:\.\d+)?px\s*\)\s*\{", css):
        if int(match.group(1)) > 860:
            continue
        depth, index = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[index], 0)
            index += 1
        yield css[match.end():index - 1]


class MobileTextTests(SimpleTestCase):
    """T-267：手機版文字不截斷、不怪斷行；改動只在 860px 以下，電腦版不變。"""

    app = (CSS_DIR / "app.css").read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_phone_blocks_never_hide_text(self):
        """手機斷點裡不能用省略號或行數限制把文字藏起來（要完整顯示、放不下就換行）。"""
        offenders = []
        for path in sorted(CSS_DIR.glob("*.css")):
            if path.name == "form-print.css":  # 列印版面，不在手機上顯示
                continue
            for block in phone_blocks(path.read_text(encoding="utf-8")):
                for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
                    if re.search(r"text-overflow:\s*ellipsis|(?<!-)line-clamp:\s*\d", rule.group(2)):
                        offenders.append(f"{path.name}: {rule.group(1).strip()[:80]}")
        self.assertEqual(offenders, [])

    def test_base_ellipsis_is_undone_on_phones(self):
        """各元件在所有寬度共用的省略號／行數限制，手機斷點要改回完整顯示。"""
        undone = {
            "app.css": (
                ".recent-field-values__option", ".account-menu__identity strong", ".search-match mark", ".order-origin__meta",
                ".field-editor-badge", ".upload-queue__name", ".source-system-info dd", ".home-link__label",
                ".source-list-note > span:not(.gift-not-required)", ".order-row--detailed .order-fact :is(b, .order-machine-color)",
                ".order-row--detailed .order-fact .order-vehicle-number", ".order-row--detailed .order-fact--note b",
            ),
            "order-workspace.css": (".order-compact-bar__name", ".order-compact-bar__recipient b", ".order-hero-note__text"),
            "order-steps.css": (".ledger__hint",),
            "catalog-photo-board.css": (".photo-cell__meta strong",),
            "report-designer.css": (".designer-chip__value",),
            "reporting.css": (".report-filter-chip__value",),
            "vehicle-model-tools.css": (".model-tool-switch__item span", ".model-installment-cond > summary"),
            "vehicle-models.css": (
                ".vehicle-brand-group__identity strong", ".master-model-table .vm-reward-cell small",
                ".master-model-table td span.color-peek__names",
            ),
            "business-holidays.css": (".holiday-calendar-day strong",),
        }
        for filename, selectors in undone.items():
            phone = "\n".join(phone_blocks((CSS_DIR / filename).read_text(encoding="utf-8")))
            for selector in selectors:
                self.assertIn(selector, phone, f"{filename} 手機斷點沒有處理 {selector}")

    def test_table_cards_put_label_above_value(self):
        """表格在 600px 以下變卡片：欄名在上、內容在下（單欄），不再用固定寬的欄名欄把內容擠成一個字一行。"""
        phone = "\n".join(phone_blocks(self.app))
        rule = re.search(r"\n  \.inventory-table td \{([^}]*)\}", phone)
        self.assertIsNotNone(rule)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", rule.group(1))
        self.assertNotRegex(phone, r"\.inventory-table td \{[^}]*grid-template-columns: \d+px")
        # 依附舊「第二欄」位置的規則要跟著改成單欄，否則會多撐出隱含欄。
        for path in sorted(CSS_DIR.glob("*.css")):
            for block in phone_blocks(path.read_text(encoding="utf-8")):
                self.assertNotRegex(
                    block, r"(sales-source-table|settlement-cost-table|model-copy-preview|model-reward-table)[^{]*\{[^}]*grid-column: 2;", path.name)
        overview = (CSS_DIR / "order-overview.css").read_text(encoding="utf-8")
        self.assertIn('.order-overview__table td:is(:first-child, [data-label="備註"]) { grid-column: 1 / -1; }', overview)

    def test_order_cards_use_full_card_width(self):
        """全部訂單手機卡片：欄位排滿整張卡寬，不擠在姓名欄（日期不再拆兩行、車行不再省略）。"""
        phone = "\n".join(phone_blocks(self.app))
        self.assertIn(".order-row--detailed > .order-main { display: contents; }", phone)
        self.assertIn(".order-row--detailed .order-facts { grid-column: 2 / -1; grid-row: 3; }", phone)

    def test_order_overview_has_phone_back_bar(self):
        """訂單總覽手機版：頂端固定「← 返回」（44px、避開瀏海），返回手勢只關總覽、不離開頁面；電腦版不顯示。"""
        for name in ("sales/_order_step_nav.html", "sales/order_list.html"):
            html = (TEMPLATES / name).read_text(encoding="utf-8")
            self.assertRegex(html, r'<button type="button" class="order-overview-dialog__back" data-overview-close[^>]*>', name)
        css = (CSS_DIR / "order-overview.css").read_text(encoding="utf-8")
        self.assertIn(".order-overview-dialog__back { display: none; }", css)
        phone = "\n".join(phone_blocks(css))
        self.assertIn("calc(env(safe-area-inset-top) + var(--space-2))", phone)
        back = re.search(r"\n  \.order-overview-dialog__back \{([^}]*)\}", phone)
        self.assertIsNotNone(back)
        self.assertIn("min-height: var(--control-h);", back.group(1))
        script = Path("static/js/order-overview.js").read_text(encoding="utf-8")
        self.assertIn('window.matchMedia("(max-width: 860px)")', script)
        self.assertIn("history.pushState({ ...(history.state || {}), orderOverview: true }", script)
        self.assertIn("if (ownsHistory) { history.back(); return; }", script)
        self.assertRegex(script, r'window\.addEventListener\("popstate", \(event\) => \{[^}]*stopImmediatePropagation\(\);[^}]*\}, true\);')

    def test_phone_full_text_for_single_line_fields(self):
        """下拉與單行欄位放不下時，手機在下方補一行完整文字；只在 860px 以下執行，電腦版不插入元素也沒有樣式。"""
        base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
        self.assertIn("js/phone-full-text.js", base)
        script = Path("static/js/phone-full-text.js").read_text(encoding="utf-8")
        self.assertIn('window.matchMedia("(max-width: 860px)")', script)
        self.assertIn('caption.setAttribute("aria-hidden", "true");', script)
        phone = "\n".join(phone_blocks(self.app))
        self.assertIn(".phone-full-text { display: block;", phone)
        outside = re.sub(r"@media\s*\(\s*max-width:[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", re.sub(r"/\*.*?\*/", "", self.app, flags=re.S))
        self.assertNotIn("phone-full-text", outside)
        self.assertNotIn("is-phone-wide", outside)


class PageStylesheetSplitTests(SimpleTestCase):
    """T-242 A 案：只有單一模組用到的樣式放在 static/css/<模組>.css，由該頁 {% block head %} 載入，不回到 app.css。"""

    # 前綴 → (模組 CSS, 載入它的頁面)
    MODULES = {
        ("price-distribution", "price-assignment"): ("price-list.css", ("sales/price_list_distribution.html", "sales/price_list_distribution_assignments.html")),
        ("dealer-reward",): ("dealer-rewards.css", ("sales/dealer_reward_campaign_form.html", "sales/dealer_reward_campaign_list.html",
                                                   "sales/dealer_reward_catalog_form.html", "sales/dealer_reward_catalog_list.html")),
        ("photo-board", "photo-cell"): ("catalog-photo-board.css", ("sales/catalog_photo_board.html",)),
        ("holiday-calendar",): ("business-holidays.css", ("sales/business_holiday_list.html",)),
        # 第二批（T-242）
        ("registration-rule",): ("registration-fee-rules.css", ("sales/brand_registration_fee_rule_list.html",)),
        ("vehicle-model", "vehicle-brand", "master-model"): ("vehicle-models.css", (
            "sales/vehicle_brand_list.html", "sales/vehicle_model_list.html", "sales/vehicle_model_form.html",
            "sales/vehicle_model_batch.html", "sales/vehicle_model_copy.html", "sales/vehicle_model_installment_batch.html",
            "sales/settlement_cost_rule_form.html", "sales/settlement_cost_rule_list.html",
            "sales/vehicle_model_price_versions.html", "sales/vehicle_model_settlement_costs.html",
            "sales/vehicle_model_commission.html", "sales/vehicle_model_incentives.html", "sales/vehicle_model_rules.html",
            "sales/catalog_edit.html", "sales/installment_plan_list.html")),
        ("source-line", "holiday-gift"): ("sales-sources.css", ("sales/sales_source_list.html", "sales/sales_source_holiday_gift_manage.html")),
        ("deletion-review",): ("order-deletion-queue.css", ("sales/order_deletion_queue.html",)),
        ("quick-entry",): ("inventory-quick-entry.css", ("sales/inventory_quick_form.html",)),
        ("accessory-bulk",): ("accessory-bulk.css", ("sales/accessory_product_list.html",)),
        ("reconciliation-table",): ("reconciliation.css", ("sales/reconciliation_list.html",)),
    }
    # 留在 app.css 的：和其他頁面共用的選擇器（同一條規則還列了其他元件，或 class 也出現在別頁），
    # 以及搬出去會改變層疊結果的規則（原本被 app.css 後段同特異度規則蓋過；tools/ui_audit/style_diff.py 找出）。
    SHARED = (".dealer-program-hero, .dealer-program-section, .dealer-reward-panel", ".dealer-reward-items",
              ".dealer-reward-tabs a:last-child", ".holiday-calendar-field",
              ".price-distribution-note textarea", ".price-assignment-picker", ".price-distribution-hero",
              ".dealer-reward-item__header .button", ".dealer-reward-cost-row__header .button",
              ".holiday-calendar-hero", ".holiday-calendar-active input",
              # 第二批：共用或層疊衝突
              ".registration-rule-panel__heading", ".master-model-section", ".master-model-grid", ".holiday-gift-summary",
              ".stacked-form, .master-model-form", ".form-section.static-section, .master-model-section",
              ".quick-entry-field", ".reconciliation-table td span.mobile-field-label")

    def test_single_page_prefixes_stay_out_of_app_css(self):
        app = (CSS_DIR / "app.css").read_text(encoding="utf-8")
        selectors = re.findall(r"(?:^|[}\n])\s*([^{}@/]+?)\s*\{", app)
        offenders = []
        for prefixes in self.MODULES:
            pattern = re.compile(r"\.(?:" + "|".join(map(re.escape, prefixes)) + r")[\w-]*")
            for selector in selectors:
                if pattern.search(selector) and not any(shared in selector for shared in self.SHARED):
                    offenders.append(" ".join(selector.split())[:80])
        self.assertEqual(offenders, [])

    def test_module_stylesheets_load_first_in_their_pages(self):
        for prefixes, (css, pages) in self.MODULES.items():
            self.assertTrue((CSS_DIR / css).exists(), css)
            for page in pages:
                text = (TEMPLATES / page).read_text(encoding="utf-8")
                self.assertIn("{% block head %}<link rel=\"stylesheet\" href=\"{% static 'css/" + css + "' %}", text, page)
                head = text.index("{% block head %}")
                self.assertRegex(text[:head], r"{%\s*load\s[^%]*\bstatic\b", page)
