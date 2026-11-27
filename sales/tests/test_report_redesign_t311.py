"""T-311 報表中心改版：月份圖切換（#4 #5 #7）與閱讀版型的圓餅（圖例一列一項、扇區百分比、前 5 名＋其他）。"""
import re
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import ReportDefinition, SalesOrder, VehicleColor, VehicleModel
from sales.reporting.reader_layouts import reader_cards
from sales.reporting.source_templates import electric_vehicle_sales, model_analysis, total_vehicle_sales

ROOT = Path(settings.BASE_DIR)


def result(index, chart, dimension, series="", date_dimension=False, series_label=""):
    return {"index": index, "card": {"chart": chart, "dimension": dimension, "series": series},
            "date_dimension": date_dimension, "series_label": series_label}


class ReaderCardsTests(SimpleTestCase):
    def items(self):
        return [result(0, "stacked", "month", "legacy_sales_source", True, "銷售來源"), result(1, "donut", "legacy_sales_source"),
                result(2, "stacked", "month", "legacy_motor_type", True, "舊報表車種分類（比對用）"), result(3, "donut", "legacy_motor_type")]

    def test_sales_layouts_merge_month_stacks_at_first_position(self):
        items = self.items()
        for layout in ("sales_overview", "electric_overview", "gasoline_overview"):
            cards = reader_cards({"reader_layout": layout}, items)
            self.assertEqual(len(cards), 3)
            self.assertEqual([member["result"]["index"] for member in cards[0]["switch"]], [0, 2])
            self.assertEqual([member["label"] for member in cards[0]["switch"]], ["依銷售來源", "依車種分類"])
            self.assertEqual([card["index"] for card in cards[1:]], [1, 3])

    def test_other_layouts_and_single_month_chart_stay_as_they_are(self):
        items = self.items()
        for layout in ("standard", "platform_overview", "dealer_overview", "count_overview", "analysis_overview", None):
            self.assertEqual(reader_cards({"reader_layout": layout} if layout else {}, items), items)
        single = [items[0], items[1]]
        self.assertEqual(reader_cards({"reader_layout": "sales_overview"}, single), single)


class ReaderPieAssetsTests(SimpleTestCase):
    def test_pie_rules_and_scripts(self):
        pie = (ROOT / "static/js/report-pie.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_PIE_MAX = 6;", pie)       # 超過 6 項才合併，畫前 5 名＋其他
        self.assertIn("const REPORT_PIE_INSIDE = 7;", pie)    # ≥ 7% 標在環上
        self.assertIn("其餘 ${merged.length} 項", pie)        # 資料本身有「其他」時改名
        self.assertIn("原報表未列出的", pie)
        interactions = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        # 只有閱讀版型的圓餅換新畫法；一般報表照舊。
        self.assertIn('chart.dataset.chart === "donut" && overview && typeof renderReportPie === "function"', interactions)
        layout = (ROOT / "templates/sales/reporting/layout.html").read_text(encoding="utf-8")
        frame = (ROOT / "templates/sales/reporting/designer_frame.html").read_text(encoding="utf-8")
        for page in (layout, frame):
            self.assertLess(page.index("js/report-pie.js"), page.index("js/report-interactions.js"))
            self.assertLess(page.index("js/report-month-switch.js"), page.index("js/report-interactions.js"))

    def test_legend_names_do_not_wrap_per_character(self):
        css = (ROOT / "static/css/report-overview.css").read_text(encoding="utf-8")
        legend = re.search(r"\.report-pie-legend \.report-overview-legend__name \{([^}]*)\}", css).group(1)
        self.assertIn("white-space:nowrap", legend)
        self.assertIn("text-overflow:ellipsis", legend)
        self.assertIn("@container (min-width: 480px)", css)
        self.assertRegex(css, r"@media \(prefers-reduced-motion: reduce\) \{\s*\.report-chart-switch__tabs \[role=tab\] \{ transition:none; \}")


# ---- 小型 CSS 層疊計算：在真的 CSS 檔上算出某個元素最後套到的值（選擇器比對＋特異度＋順序＋!important＋繼承）。
# 只支援報表頁用到的語法；不確定的條件（@container、:has() 等）一律當成成立，寧可多算一條規則。
STATE_PSEUDOS = {"hover", "focus", "focus-visible", "focus-within", "active", "visited", "target", "checked",
                 "disabled", "invalid", "placeholder-shown", "empty", "popover-open", "open"}
INHERITED = {"overflow-wrap"}


def _split_top(text, separators):
    parts, depth, current = [], 0, ""
    for char in text:
        depth += char in "([" or -(char in ")]")
        if depth == 0 and char in separators:
            parts.append(current); current = ""
        else:
            current += char
    return parts + [current]


def _media_ok(condition, width):
    condition = condition.strip().lower()
    if not condition:
        return True
    for alternative in _split_top(condition, ","):
        alternative = alternative.strip()
        if "print" in alternative and "screen" not in alternative:
            continue
        ok = True
        for feature in re.findall(r"\(([^()]*)\)", alternative):
            match = re.fullmatch(r"\s*(min|max)-width\s*:\s*([\d.]+)(px|em|rem)\s*", feature)
            if match:
                value = float(match.group(2)) * (16 if match.group(3) != "px" else 1)
                ok &= width >= value if match.group(1) == "min" else width <= value
            elif "prefers-color-scheme" in feature:
                ok &= "light" in feature
            elif "prefers-reduced-motion" in feature:
                ok &= "no-preference" in feature
        if ok:
            return True
    return False


def css_rules(text, width):
    """回傳 [(selector, {prop: (value, important)})]，依檔案順序；@media 依寬度判斷，@keyframes 等略過。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules, index = [], 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return rules
        prelude, depth, end = text[index:start].strip(), 1, start + 1
        while depth:
            depth += (text[end] == "{") - (text[end] == "}")
            end += 1
        body = text[start + 1:end - 1]
        index = end
        if prelude.startswith("@"):
            name = prelude.split()[0][1:].split("(")[0]
            if name == "media" and _media_ok(prelude[6:], width) or name in {"container", "supports", "layer"}:
                rules += css_rules(body, width)
            continue
        declarations = {}
        for declaration in _split_top(re.sub(r"[^{};]*\{[^{}]*\}", "", body), ";"):
            if ":" in declaration:
                prop, value = declaration.split(":", 1)
                important = "!important" in value
                declarations[prop.strip().lower()] = (value.replace("!important", "").strip(), important)
        rules.append((prelude, declarations))


def _compounds(selector):
    """'.a > .b c' → [(None, '.a'), ('>', '.b'), (' ', 'c')]"""
    parts, combinator, current, depth = [], None, "", 0
    for char in selector.strip() + " ":
        depth += char in "([" or -(char in ")]")
        if depth == 0 and (char.isspace() or char in ">+~"):
            if current:
                parts.append((combinator, current)); current = ""; combinator = " "
            if char in ">+~":
                combinator = char
            continue
        current += char
    return parts


def _simple_parts(compound):
    return re.findall(r"::?[\w-]+(?:\((?:[^()]|\([^()]*\))*\))?|\.[\w-]+|#[\w-]+|\[[^\]]*\]|\*|^[a-zA-Z][\w-]*", compound)


def _nth(expression, position):
    expression = expression.replace(" ", "")
    if expression in {"odd", "even"}:
        return position % 2 == (expression == "odd")
    match = re.fullmatch(r"([+-]?\d*)n([+-]\d+)?", expression)
    if not match:
        return position == int(expression)
    a = int(match.group(1) + "1" if match.group(1) in {"", "+", "-"} else match.group(1))
    b = int(match.group(2) or 0)
    return (position - b) * a >= 0 and (a == 0 or (position - b) % a == 0) if a else position == b


def _pseudo(part):
    name, _, argument = part[1:].partition("(")
    return name, argument[:-1]


def _specificity(compound):
    total = [0, 0, 0]
    for part in _simple_parts(compound):
        if part == "*":
            continue
        if part.startswith("#"):
            total[0] += 1
        elif part.startswith((".", "[")):
            total[1] += 1
        elif part.startswith("::") or part in {":before", ":after"}:
            total[2] += 1
        elif part.startswith(":"):
            name, argument = _pseudo(part)
            if name == "where":
                continue
            if name in {"not", "is", "matches", "has"}:
                best = max((_specificity(item.strip()) for item in _split_top(argument, ",")), default=[0, 0, 0])
                total = [x + y for x, y in zip(total, best)]
            else:
                total[1] += 1
        else:
            total[2] += 1
    return total


def _match_compound(compound, node):
    for part in _simple_parts(compound):
        if part == "*":
            continue
        if part.startswith("::") or part in {":before", ":after"}:
            return False  # 偽元素不是這個元素本身
        if part.startswith("."):
            ok = part[1:] in node["classes"]
        elif part.startswith("#"):
            ok = False
        elif part.startswith("["):
            ok = re.split(r"[~|^$*]?=", part[1:-1])[0].strip() in node["attrs"]
        elif part.startswith(":"):
            name, argument = _pseudo(part)
            if name in {"not", "is", "where", "matches"}:
                ok = any(_match_compound(item.strip(), node) for item in _split_top(argument, ","))
                ok = not ok if name == "not" else ok
            elif name in STATE_PSEUDOS:
                ok = False  # 量的是靜止狀態
            elif name == "first-child":
                ok = node["position"] == 1
            elif name == "last-child":
                ok = node["position"] == node["siblings"]
            elif name in {"nth-child", "nth-of-type"}:
                ok = _nth(argument, node["position"])
            elif name in {"link", "any-link"}:
                ok = "href" in node["attrs"]
            elif name == "root":
                ok = node["tag"] == "html"
            else:
                ok = True  # :has() 等：當成成立
        else:
            ok = part.lower() == node["tag"]
        if not ok:
            return False
    return True


def _match_selector(selector, chain):
    """符合就回傳特異度，否則 None。相鄰／後續兄弟選擇器沒有兄弟資料，左邊那一段當成成立。"""
    parts = _compounds(selector)

    def walk(index, position, check=True):
        combinator, compound = parts[index]
        if check and not _match_compound(compound, chain[position]):
            return False
        if index == 0:
            return True
        if combinator == ">":
            return position > 0 and walk(index - 1, position - 1)
        if combinator in "+~":
            return walk(index - 1, position, check=False)
        return any(walk(index - 1, ancestor) for ancestor in range(position - 1, -1, -1))

    if not parts or not walk(len(parts) - 1, len(chain) - 1):
        return None
    total = [0, 0, 0]
    for _, compound in parts:
        total = [x + y for x, y in zip(total, _specificity(compound))]
    return total


def computed(rules, chain, prop, aliases=()):
    """chain：由 html 到目標元素的節點；回傳最後套到的值（含繼承），沒有就回傳 None。"""
    best = None
    for order, (prelude, declarations) in enumerate(rules):
        names = [name for name in (prop, *aliases) if name in declarations]
        if not names:
            continue
        for selector in _split_top(prelude, ","):
            specificity = _match_selector(selector, chain)
            if specificity is None:
                continue
            value, important = declarations[names[-1]]
            key = (important, specificity, order)
            if best is None or key > best[0]:
                best = (key, value)
    value = best[1] if best else None
    if prop in INHERITED and (value is None or value == "inherit") and len(chain) > 1:
        return computed(rules, chain[:-1], prop, aliases)
    return value


def node(spec, position=2, siblings=9, attrs=()):
    tag, *classes = spec.split(".")
    return {"tag": tag, "classes": set(classes), "attrs": set(attrs), "position": position, "siblings": siblings}


class PieLegendMembersCascadeTests(SimpleTestCase):
    """「其他」的成員連結（report-pie.js 產生的 p.report-pie-legend__members > a）不能吃到圖例列的 grid，否則一字一行（T-311 F2）。
    在 app.css → reporting.css → report-overview.css（頁面載入順序）上真的算一次層疊，而不是找字串。"""
    FILES = ("static/css/app.css", "static/css/reporting.css", "static/css/report-overview.css")
    # #5 電動車銷售統計的實際 DOM（瀏覽器量到的祖先鏈）。
    ANCESTORS = ("html", "body", "main.page-shell.page-shell--wide.report-reader-shell.report-overview-shell", "div.report-workspace",
                 "div.report-reader-layout.has-side-dock", "div.report-reader-main.report-sales-overview.report-electric-overview",
                 "div.report-exploration", "div.report-grid", "section.report-panel.report-chart.report-overview-tools-ready",
                 "div.report-pie", "div.report-pie__inner", "div.report-overview-legend.report-pie-legend")

    def rules(self, width):
        return css_rules("\n".join((ROOT / path).read_text(encoding="utf-8") for path in self.FILES), width)

    def chain(self, link_position):
        ancestors = [node(spec) for spec in self.ANCESTORS]
        return ancestors + [node("div.report-pie-legend__other", position=6, siblings=6), node("p.report-pie-legend__members", position=5, siblings=5),
                            node("a", position=link_position, siblings=4, attrs=("href", "data-report-drill"))]

    def test_script_builds_this_structure(self):
        pie = (ROOT / "static/js/report-pie.js").read_text(encoding="utf-8")
        self.assertIn("legend.className = 'report-overview-legend report-pie-legend'", pie)
        self.assertIn("item.classList.add('report-pie-legend__other')", pie)
        self.assertIn("detail.className = 'report-pie-legend__members'", pie)
        self.assertIn("const copy = link.cloneNode(false); copy.textContent = text; detail.append(copy);", pie)

    def test_engine_sees_the_shared_legend_row_grid(self):
        # 對照組：圖例列本身的連結確實是 grid（共用規則），證明計算有讀到那條規則。
        row = [node(spec) for spec in self.ANCESTORS] + [node("a", attrs=("href", "data-report-drill"))]
        self.assertEqual(computed(self.rules(1440), row, "display"), "grid")

    def test_member_links_are_inline_text_at_desktop_and_phone_width(self):
        for width in (1440, 375):
            rules = self.rules(width)
            for position in (1, 2):
                with self.subTest(width=width, link=position):
                    chain = self.chain(position)
                    self.assertEqual(computed(rules, chain, "display"), "inline")
                    self.assertIn(computed(rules, chain, "grid-template-columns", ("grid-template", "grid")), (None, "none"))
                    self.assertEqual(computed(rules, chain, "overflow-wrap", ("word-wrap",)), "normal")
                    self.assertIn(computed(rules, chain, "padding"), (None, "0"))


class MonthSwitchPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("admin", "admin@example.invalid", "Test-Only-123")
        model = VehicleModel.objects.create(brand="eReady", name="Fun", model_number="EV060L", energy_type="electric")
        color = VehicleColor.objects.create(vehicle_model=model, name="白")
        for day in (3, 4):
            SalesOrder.objects.create(source_type="store", order_date=date(2026, 10, 2), registration_date=date(2026, 10, day),
                                      registration_completed_at=timezone.now(), owner_type="local", owner_name="合成車主",
                                      owner_id_number="A123456789", vehicle_model=model, color=color, vehicle_price=10000,
                                      actual_balance=10000, calculated_balance=10000, payment_type="cash", status="completed")

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, config):
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        return self.client.get(reverse("report_display", args=[report.pk])).content.decode()

    def test_electric_page_has_one_switch_with_model_first_and_two_pies(self):
        html = self.page(electric_vehicle_sales())
        self.assertEqual(html.count("data-chart-switch"), 1)
        tabs = re.findall(r'data-switch-tab="(\d+)">([^<]+)</button>', html)
        self.assertEqual(tabs, [("0", "依型號"), ("1", "依銷售來源")])
        self.assertEqual(html.count("data-switch-panel"), 2)
        self.assertIn('aria-labelledby="chart-switch-tab-0"', html)
        self.assertEqual(html.count('data-chart="donut"'), 2)
        self.assertIn("data-current-month=", html)
        # 圖卡順序：切換卡、型號圓餅、銷售來源圓餅
        self.assertLess(html.index("data-chart-switch"), html.index('id="chart-2"'))
        self.assertLess(html.index('id="chart-2"'), html.index('id="chart-3"'))

    def test_total_sales_switch_without_config_change(self):
        html = self.page(total_vehicle_sales())
        self.assertEqual(re.findall(r'data-switch-tab="(\d+)">([^<]+)</button>', html), [("0", "依銷售來源"), ("2", "依車種分類")])

    def test_analysis_page_has_no_switch(self):
        html = self.page(model_analysis("sex"))
        self.assertNotIn("data-chart-switch", html)
        self.assertNotIn("data-switch-panel", html)


class HeatTableAssetsTests(SimpleTestCase):
    def test_dealer_and_platform_use_heat_table_with_validated_scale(self):
        heat = (ROOT / "static/js/report-heat.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_HEAT_LEVELS = 5;", heat)
        self.assertIn("其他平台", heat)
        interactions = (ROOT / "static/js/report-interactions.js").read_text(encoding="utf-8")
        self.assertIn("['dealer_overview', 'platform_overview'].includes(layout)", interactions)
        css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
        for color in ("#a3acf9", "#7d8af6", "#5767f3", "#3446f0", "#1f2aa6", "#3b48ad", "#5262e6", "#7581ff", "#9ea6ff", "#c9cdff"):
            self.assertIn(color, css)
        self.assertEqual(len(re.findall(r"--heat-5: #", css)), 3)  # 亮色、night-blue、跟隨系統深色
        for page in ("layout.html", "designer_frame.html"):
            html = (ROOT / "templates/sales/reporting" / page).read_text(encoding="utf-8")
            self.assertLess(html.index("js/report-heat.js"), html.index("js/report-interactions.js"))


class CountExpandTests(TestCase):
    """台數統計（#13 #14）：點車行就地展開訂單，用同一個 report_detail 與 group，只多 view=count。"""
    @classmethod
    def setUpTestData(cls):
        from sales.tests import test_reporting as fixtures
        fixtures.ReportingTests.setUpTestData.__func__(cls)

    def setUp(self):
        from sales.reporting.engine import validate_config
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        from sales.tests import test_reporting as fixtures
        self.report.published = validate_config(SOURCE_TEMPLATES["gasoline-count"]())
        self.report.save()
        fixtures.ReportingTests.login(self)

    def test_page_folds_full_records_and_loads_expand_script(self):
        html = self.client.get(reverse("report_display", args=[self.report.pk])).content.decode()
        self.assertIn("data-records-fold", html)
        self.assertNotIn("data-records-fold open", html)
        self.assertIn("js/report-count.js", html)
        opened = self.client.get(reverse("report_display", args=[self.report.pk]), {"records_page": "1"}).content.decode()
        self.assertIn("data-records-fold open", opened)

    def test_count_view_lists_orders_with_short_columns(self):
        from sales.reporting.views import publication_key
        url = reverse("report_detail", args=[self.report.pk, 0])
        base = {"group": "__all__", "inline": "1", "revision": publication_key(self.report)}
        html = self.client.get(url, {**base, "view": "count", "label": "不存在的車行"}).content.decode()
        self.assertIn("data-count-orders", html)
        self.assertIn("領牌日期 · 車主", html)
        self.assertIn("歸屬：", html)  # 歸屬車行和展開的車行不同時才標
        plain = self.client.get(url, base).content.decode()
        self.assertNotIn("data-count-orders", plain)  # 沒有 view=count 照舊

    def test_count_view_only_for_count_layout(self):
        from sales.reporting.source_templates import SOURCE_TEMPLATES
        from sales.reporting.views import publication_key
        self.report.published = SOURCE_TEMPLATES["gasoline"]()
        self.report.save()
        url = reverse("report_detail", args=[self.report.pk, 0])
        html = self.client.get(url, {"group": "__all__", "inline": "1", "view": "count", "revision": publication_key(self.report)}).content.decode()
        self.assertNotIn("data-count-orders", html)

    def test_money_format(self):
        from sales.reporting.views import _count_money
        self.assertEqual(_count_money("0.00"), "")
        self.assertEqual(_count_money("1500.00"), "1,500")
        self.assertEqual(_count_money("12.50"), "12.50")
        self.assertEqual(_count_money("待補收支資料"), "待補收支資料")


class AnalysisViewsTests(SimpleTestCase):
    def test_car_paint_filter_uses_existing_color_families(self):
        from sales.templatetags.report_tags import car_paint, car_paint_outline
        self.assertEqual(car_paint("珍珠白 W1"), "#f4f5f7")
        self.assertTrue(car_paint_outline(car_paint("珍珠白")))
        self.assertEqual(car_paint("消光黑"), "#2b2d31")
        self.assertFalse(car_paint_outline(car_paint("消光黑")))
        self.assertEqual(car_paint("未知色"), "")

    def test_assets_and_rules(self):
        views = (ROOT / "static/js/report-analysis-views.js").read_text(encoding="utf-8")
        self.assertIn("const REPORT_SEX_ORDER = ['女性', '男性'];", views)
        self.assertIn("chart.dataset.series === 'sex'", views)
        self.assertIn("chart.dataset.dimension === 'family_color' && chart.dataset.series === 'age_group'", views)
        pie = (ROOT / "static/js/report-pie.js").read_text(encoding="utf-8")
        self.assertIn("fixed: chart.dataset.dimension === 'sex' ? ['女性', '男性'] : []", pie)
        for page in ("layout.html", "designer_frame.html"):
            html = (ROOT / "templates/sales/reporting" / page).read_text(encoding="utf-8")
            self.assertLess(html.index("js/report-analysis-views.js"), html.index("js/report-interactions.js"))


class AnalysisPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MonthSwitchPageTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_scope_labels_fold_and_owner_list_collapsed(self):
        from sales.reporting.source_templates import sex_model_color_analysis
        report = ReportDefinition.objects.create(draft=sex_model_color_analysis(), published=sex_model_color_analysis(), version=1)
        html = self.client.get(reverse("report_display", args=[report.pk])).content.decode()
        self.assertIn('<details class="report-scope-fold"><summary>此圖固定條件</summary>', html)
        self.assertIn("data-records-fold", html)
        self.assertIn("車主名單（", html)

    def test_color_bars_carry_car_paint(self):
        report = ReportDefinition.objects.create(draft=model_analysis("color"), published=model_analysis("color"), version=1)
        html = self.client.get(reverse("report_display", args=[report.pk])).content.decode()
        self.assertIn('data-car-paint="#f4f5f7" data-car-paint-outline', html)


class SharedBaseTests(TestCase):
    """共用基礎：只在閱讀版型（非 standard）生效；一般自訂報表照舊。"""
    @classmethod
    def setUpTestData(cls):
        MonthSwitchPageTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, config):
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        return self.client.get(reverse("report_display", args=[report.pk])).content.decode()

    def test_overview_header_card_link_hint_records_and_spark(self):
        html = self.page(total_vehicle_sales())
        self.assertRegex(html, r'data-report-meta><b>2026/10</b> · 共 <b>2</b> 張')
        self.assertIn('class="report-card-orders" data-report-open-detail', html)
        self.assertIn("report-card-foot--overview", html)
        self.assertEqual(html.count('class="report-overview-hint"'), 1)
        self.assertIn("顯示其他 4 欄", html)  # 閱讀版型明細 11 欄（不含實收），只留 7 個常用欄
        self.assertIn("data-record-extra", html)
        self.assertIn("report-record-note--line", html)
        self.assertIn('class="report-kpi__spark"', html)

    def test_standard_report_unchanged(self):
        from sales.reporting.views import initial_config
        html = self.page({**initial_config(), "include_records": True})
        for marker in ("data-report-meta", "report-card-orders", "report-card-foot--overview", "report-overview-hint",
                       "data-record-extra", "report-kpi__spark", "data-chart-switch"):
            self.assertNotIn(marker, html)


class PlatformDealerHeaderTests(TestCase):
    """平台（#6 #8）、車行（#11 #12）頁：提示只寫能做的事（N1）；T-322 起格子可點開看那個月的訂單。"""
    @classmethod
    def setUpTestData(cls):
        MonthSwitchPageTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, config):
        report = ReportDefinition.objects.create(draft=config, published=config, version=1)
        return self.client.get(reverse("report_display", args=[report.pk])).content.decode()

    def hint(self, html):
        return re.search(r'<p class="report-overview-hint">([^<]*)</p>', html).group(1)

    def test_hint_matches_what_the_page_can_do(self):
        from sales.reporting.source_templates import dealer_sales, electric_platform_sales, gasoline_platform_sales
        # 平台頁：平台名稱不能點；格子可點開看那個月的訂單（T-322），整個平台用上方篩選或「看訂單」。
        for config in (electric_platform_sales(), gasoline_platform_sales()):
            with self.subTest(title=config["title"]):
                html = self.page(config)
                self.assertEqual(self.hint(html), "點格子裡的數字，直接看那個月的訂單，不用換頁。要看某個平台的全部訂單，用上方「平台」篩選，或按「看訂單 →」。")
                self.assertIn('class="report-card-orders" data-report-open-detail', html)
        # 車行頁：車行名稱沿用原本的下鑽連結，點了整頁連動；格子可點開看那個月的訂單（T-322）。
        for config in (dealer_sales(), dealer_sales(gasoline=True)):
            with self.subTest(title=config["title"]):
                self.assertEqual(self.hint(self.page(config)), "點車行名稱，整頁一起篩選；再點一次取消。點格子裡的數字，直接看那個月的訂單，不用換頁。")
        # 其他閱讀版型不變
        self.assertEqual(self.hint(self.page(electric_vehicle_sales())), "點圖上的長條、扇區或格子，整頁一起篩選；再點一次取消。")


class ReaderMetaSeriesMonthTests(SimpleTestCase):
    """車行頁（#11 #12）月份是系列：頁首補期間（N4）；有月份併進「其他系列」時期間不完整就不寫。"""
    def item(self, legend, count=5):
        return {"card": {"chart": "stacked", "dimension": "legacy_dealer", "series": "month"}, "count": count, "rows": [],
                "date_dimension": False, "series_legend": [{"label": label} for label in legend]}

    def test_dealer_page_range_comes_from_month_series(self):
        from sales.reporting.reader_layouts import reader_meta
        self.assertEqual(reader_meta([self.item(["2026/10", "2026/08", "2026/09"])]), {"count": 5, "range": "2026/08–2026/10"})
        self.assertEqual(reader_meta([self.item(["2026/10"])]), {"count": 5, "range": "2026/10"})

    def test_no_range_when_months_are_merged_into_other(self):
        from sales.reporting.reader_layouts import reader_meta
        self.assertEqual(reader_meta([self.item(["2026/10", "2026/09", "其他系列（合併）"])]), {"count": 5})

    def test_month_axis_pages_unchanged(self):
        from sales.reporting.reader_layouts import reader_meta
        month = {"card": {"chart": "stacked", "dimension": "month", "series": "legacy_dealer"}, "count": 3, "date_dimension": True,
                 "rows": [{"label": "2026/09"}, {"label": "2026/11"}], "series_legend": [{"label": "某平台"}]}
        self.assertEqual(reader_meta([month]), {"count": 3, "range": "2026/09–2026/11"})
