"""T-252（使用者 2026-11-19）：手機版全部訂單頁。

日期迄超出卡片右緣：iOS Safari 的原生日期欄位（appearance: auto）以自身內容決定寬度，不理會 width: 100%／min-width: 0，
放在兩欄的篩選格裡就會撐出卡片。訂單表單的 .form-control 日期欄早已用 display: block＋appearance: none 修過（f8202c91），
全部訂單的篩選日期欄不是 .form-control，沒有套到。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STATIC = Path(settings.BASE_DIR) / "static"


def order_list_css():
    """T-242：訂單列表篩選與排序樣式搬到 order-list.css（只搬不改內容），和 app.css 一起讀。"""
    return "".join((STATIC / "css" / name).read_text(encoding="utf-8") for name in ("app.css", "order-list.css"))


def mobile_rule(css, selector):
    """回傳 @media (max-width: 860px) 區塊內指定選擇器的宣告。"""
    for block in re.finditer(r"@media \(max-width: 860px\) \{(.*?)\n\}", css, re.S):
        match = re.search(re.escape(selector) + r" \{([^}]*)\}", block.group(1))
        if match:
            return match.group(1)
    return ""


class OrderFilterDateWidthTests(SimpleTestCase):
    def test_mobile_date_inputs_drop_native_appearance_and_stay_inside_card(self):
        css = order_list_css()
        rule = mobile_rule(css, ".order-filter-bar input[type=date]")
        self.assertIn("display: block", rule)
        self.assertIn("-webkit-appearance: none", rule)
        self.assertIn("appearance: none", rule)
        self.assertIn("max-width: 100%", rule)


TEMPLATE = Path(settings.BASE_DIR) / "templates" / "sales" / "order_list.html"


class OrderListMobileLayoutTests(SimpleTestCase):
    """使用者 2026-11-19 選 A：「T-252 走 A，操作鈕收成更多操作、篩選收進底部面板」。"""

    def test_more_actions_menu_reuses_the_same_permission_gated_buttons(self):
        page = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('<button type="button" class="button ghost order-more-toggle" data-order-more-toggle aria-expanded="false" aria-controls="order-list-actions">更多操作', page)
        actions = re.search(r'<div class="hero-actions" id="order-list-actions">(.*?)</div>', page).group(1)
        for key in ("order_export", "form_print", "order_recycle_bin", "order_deletion_queue", "draft_cleanup_list"):
            self.assertIn(f"{{% if_access '{key}' %}}", actions)
        self.assertIn("data-order-export-link", actions)

    def test_filter_fields_move_into_bottom_sheet_with_apply_and_clear(self):
        page = TEMPLATE.read_text(encoding="utf-8")
        sheet = page[page.index("<dialog class=\"order-filter-sheet\""):page.index("</dialog>")]
        for name in ("date_from", "date_to", "energy_type", "payment_status", "registered", "status"):
            self.assertIn(f'name="{name}"', sheet)
        self.assertIn('data-order-filter-clear>清除</button>', sheet)
        self.assertIn('type="submit" class="button primary" data-order-filter-apply>套用</button>', sheet)
        # 搜尋框留在面板外、常駐；篩選鈕有套用數量。
        self.assertNotIn('name="q"', sheet)
        self.assertIn('data-order-filter-open aria-haspopup="dialog" aria-controls="order-filter-sheet">篩選<span data-order-filter-count></span>', page)

    def test_desktop_keeps_filters_inline_and_hides_mobile_controls(self):
        css = order_list_css()
        self.assertIn(".order-more-toggle, .order-filter-open, .order-filter-chips, .order-filter-sheet__head, .order-filter-sheet__actions { display: none; }", css)
        self.assertIn(".order-filter-bar .order-filter-sheet { display: contents; color: inherit; }", css)
        # T-242：這條搬到 order-list.css 的 860px 以下區塊（只搬不改內容），不在 app.css 的 T-252 區段裡了。
        self.assertEqual(mobile_rule(css, ".order-filter-bar .order-filter-sheet:not([open])"), " display: none; ")

    def test_chips_and_sheet_behaviour(self):
        js = (STATIC / "js/order-list-filters.js").read_text(encoding="utf-8")
        # T-323：車行／平台（src）也列進小標籤與面板的還原／清除（需 PM 同意的測試修改，見 T-323 回報）。
        self.assertIn('const NAMES = ["src", "date_from", "date_to", "energy_type", "payment_status", "registered", "status"];', js)
        self.assertIn('count.textContent = names.length ? `（${names.length}）` : "";', js)
        self.assertIn('clear.textContent = "全部清除";', js)
        # 沒按套用就關閉，欄位回到原值；面板開著時改狀態不立刻送出。
        self.assertIn("if (snapshot) NAMES.forEach", js)
        self.assertNotIn("onchange", re.search(r'<select name="status"[^>]*>', TEMPLATE.read_text(encoding="utf-8")).group(0))  # T-324：狀態按套用才查（PM 核准）
        self.assertNotIn("event.stopPropagation(); }, true);", js)  # T-324：沒有自動送出，不必再攔 change
        self.assertIn('sheet.addEventListener("cancel"', js)


def mobile_rule_block(css):
    start = css.index("/* T-252（使用者 2026-11-19 選 A）")
    return css[start:css.index("@keyframes order-filter-sheet-in", start)]


class OrderListTabsAndSortMobileTests(SimpleTestCase):
    """使用者 2026-11-19：「要，分類頁籤和排序也一起壓縮，只改手機版」。"""

    def test_scope_tabs_become_one_scrollable_row_on_mobile(self):
        css = order_list_css()
        block = css[css.index("/* T-252 擴大範圍"):]
        self.assertRegex(block, r"\.order-results \.order-scope-tabs \{\s*display: flex;[^}]*overflow-x: auto;")
        self.assertIn(".order-scope-tabs .inventory-scope-tab { flex: 0 0 auto;", block)
        js = (STATIC / "js/order-list-filters.js").read_text(encoding="utf-8")
        self.assertIn('const tab = scroller?.querySelector(\'[aria-current="page"]\');', js)
        self.assertIn("scroller.scrollTo({ left: Math.max(0, left), behavior: \"instant\" });", js)

    def test_sort_collapses_into_button_and_sheet_marking_active_columns(self):
        page = TEMPLATE.read_text(encoding="utf-8")
        controls = page[page.index('<div class="order-sort-controls"'):page.index('<div class="inventory-table-wrap order-sort-table"')]
        self.assertIn('data-order-sort-open aria-haspopup="dialog" aria-controls="order-sort-sheet"><span class="order-sort-open__text">排序：', controls)
        self.assertIn('<dialog class="order-sort-sheet" id="order-sort-sheet" aria-labelledby="order-sort-sheet-title" data-order-sort-sheet>', controls)
        self.assertIn('{% if column.rank %} class="is-active" aria-current="true"{% endif %}', controls)
        self.assertIn("</dialog>", controls)
        css = order_list_css()
        self.assertIn(".order-sort-controls .order-sort-sheet { display: contents; color: inherit; }", css)
        self.assertIn(".order-sort-controls .order-sort-sheet:not([open]) { display: none; }", css)

    def test_sort_sheet_closes_before_list_reload_and_returns_focus(self):
        js = (STATIC / "js/order-list-filters.js").read_text(encoding="utf-8")
        self.assertIn('if (event.target.closest("a[href]")) { refocusSort = true; closeSort(false); }', js)
        self.assertIn('document.documentElement.classList.remove("has-order-sort-open");', js)
        self.assertIn("if (refocusSort) { refocusSort = false; openerOf()?.focus({ preventScroll: true }); }", js)


class OrderListExtraCompressionTests(SimpleTestCase):
    """使用者 2026-11-19：「三項都做」——訂單數與每頁筆數一行、未完成草稿併進更多操作、收起「訂單管理」小字。"""

    def test_drafts_link_moves_into_more_actions_with_same_permission(self):
        page = TEMPLATE.read_text(encoding="utf-8")
        actions = re.search(r'<div class="hero-actions" id="order-list-actions">(.*?)</div>', page).group(1)
        self.assertIn("{% if_access 'order_create' %}<a class=\"button ghost order-more-only\" href=\"{% url 'order_list' %}?drafts=1#drafts\">未完成草稿</a>{% endif_access %}", actions)
        self.assertIn("{% if_access 'order_create' %}<a class=\"order-drilldown__drafts\" href=\"{% url 'order_list' %}?drafts=1#drafts\">未完成草稿</a>{% endif_access %}", page)

    def test_mobile_rules_and_desktop_hides_menu_only_link(self):
        css = order_list_css()
        self.assertIn(".order-sort-open, .order-sort-sheet__head, .order-more-only { display: none; }", css)
        block = css[css.index("/* 追加三項"):]
        self.assertIn(".order-list-hero .eyebrow { display: none; }", block)
        self.assertIn(".order-list-hero .hero-actions > .order-more-only { display: flex; }", block)
        self.assertIn(".order-drilldown > .order-drilldown__drafts { display: none; }", block)
        self.assertIn(".order-results .order-list-summary { min-height: 0; flex-direction: row;", block)
