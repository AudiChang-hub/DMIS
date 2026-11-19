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


def mobile_rule(css, selector):
    """回傳 @media (max-width: 860px) 區塊內指定選擇器的宣告。"""
    for block in re.finditer(r"@media \(max-width: 860px\) \{(.*?)\n\}", css, re.S):
        match = re.search(re.escape(selector) + r" \{([^}]*)\}", block.group(1))
        if match:
            return match.group(1)
    return ""


class OrderFilterDateWidthTests(SimpleTestCase):
    def test_mobile_date_inputs_drop_native_appearance_and_stay_inside_card(self):
        css = (STATIC / "css/app.css").read_text(encoding="utf-8")
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
        css = (STATIC / "css/app.css").read_text(encoding="utf-8")
        self.assertIn(".order-more-toggle, .order-filter-open, .order-filter-chips, .order-filter-sheet__head, .order-filter-sheet__actions { display: none; }", css)
        self.assertIn(".order-filter-bar .order-filter-sheet { display: contents; color: inherit; }", css)
        self.assertIn(".order-filter-bar .order-filter-sheet:not([open]) { display: none; }", mobile_rule_block(css))

    def test_chips_and_sheet_behaviour(self):
        js = (STATIC / "js/order-list-filters.js").read_text(encoding="utf-8")
        self.assertIn('const NAMES = ["date_from", "date_to", "energy_type", "payment_status", "registered", "status"];', js)
        self.assertIn('count.textContent = names.length ? `（${names.length}）` : "";', js)
        self.assertIn('clear.textContent = "全部清除";', js)
        # 沒按套用就關閉，欄位回到原值；面板開著時改狀態不立刻送出。
        self.assertIn("if (snapshot) NAMES.forEach", js)
        self.assertIn('sheet.addEventListener("change", (event) => { if (sheet.open) event.stopPropagation(); }, true);', js)
        self.assertIn('sheet.addEventListener("cancel"', js)


def mobile_rule_block(css):
    start = css.index("/* T-252（使用者 2026-11-19 選 A）")
    return css[start:css.index("@keyframes order-filter-sheet-in", start)]
