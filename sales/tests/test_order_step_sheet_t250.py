"""T-250 B 案（使用者 2026-11-19）：手機版訂單頁的換步驟入口與訂單總覽。

使用者原話：「訂單步驟的位置很不直覺…電腦版有個訂單總覽，手機沒有？」、「往下捲的時候客戶名稱和車行那一列不要縮起來」、
「這樣還要有上一步下一步嗎？…我這個已經是開好訂單後進來維護訂單了」。
手機版（≤860px）精簡列常駐頂端：客戶名稱與狀態、車行、「第 N／7 步」換步驟鈕＋總覽鈕；步驟從底部面板選，左上角把手收起。
電腦版維持左側步驟欄。
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from sales.tests import test_order_flow as flow

STATIC = Path(settings.BASE_DIR) / "static"


def compact_bar(page):
    start = page.index("data-order-compact-bar")
    return page[start:page.index("data-order-stage-start", start)]


class OrderStepEntryPageTests(TestCase):
    setUp = flow.OrderFlowTests.setUp
    make_order = flow.OrderFlowTests.make_order

    def page(self, order, query=""):
        admin = get_user_model().objects.filter(username="admin").first() or get_user_model().objects.create_superuser(
            "admin", password="test-only")
        self.client.force_login(admin)
        response = self.client.get(reverse("order_detail", args=[order.pk]) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_compact_bar_has_step_entry_and_overview_button(self):
        order = self.make_order()
        bar = compact_bar(self.page(order, "?tab=deposit"))
        entry = re.search(r'<button type="button" class="order-step-entry" data-order-step-sheet-open aria-haspopup="dialog" aria-controls="order-step-sheet">(.*?)</button>', bar, re.S)
        self.assertIsNotNone(entry)
        self.assertIn("第 2／7 步・點這裡換步驟", entry.group(1))
        self.assertRegex(entry.group(1), r"<strong data-order-step-entry-label>[^<]+</strong>")
        overview_url = reverse("order_overview", args=[order.pk])
        self.assertIn(f'<a class="order-step-overview" href="{overview_url}" data-order-overview-open="{overview_url}" aria-haspopup="dialog"', bar)

    def test_extra_steps_show_as_other(self):
        bar = compact_bar(self.page(self.make_order(), "?tab=attachments"))
        self.assertIn("其他・點這裡換步驟", bar)

    def test_sheet_dialog_and_handle_modifier(self):
        page = self.page(self.make_order())
        self.assertIn('<dialog class="order-step-sheet" id="order-step-sheet" aria-labelledby="order-step-sheet-title" data-order-step-sheet>', page)
        self.assertIn('<button type="button" class="order-step-sheet__close" data-order-step-sheet-close aria-label="關閉訂單步驟">', page)
        self.assertIn('class="order-nav order-nav--sheet" data-order-nav', page)
        self.assertIn("js/order-step-sheet.js", page)
        # 訂單維護頁不做上一步／下一步（使用者 2026-11-19）。
        self.assertNotIn("上一步", compact_bar(page))

    def test_edit_mode_keeps_handle(self):
        """編輯模式（儲存失敗回填時）沒有精簡列，左上角把手照舊。"""
        from django.template.loader import render_to_string
        order = self.make_order()
        html = render_to_string("sales/_order_step_nav.html", {"order": order, "editing_order": order, "step_list": [], "extra_step_list": []})
        self.assertIn('<div class="order-nav" data-order-nav>', html)
        html = render_to_string("sales/_order_step_nav.html", {"order": order, "step_list": [], "extra_step_list": []})
        self.assertIn('<div class="order-nav order-nav--sheet" data-order-nav>', html)


class OrderStepSheetAssetTests(SimpleTestCase):
    def read(self, name):
        return (STATIC / name).read_text(encoding="utf-8")

    def test_mobile_compact_bar_is_pinned_and_never_shrinks(self):
        css = self.read("css/order-workspace.css")
        block = css[css.index("/* T-250 B 案"):]
        self.assertIn(".order-compact-bar__steps { display: none; }", block)
        self.assertRegex(block, r"@media \(max-width: 860px\) \{\s*\.order-compact-anchor \{ height: auto; \}")
        self.assertIn("opacity: 1; transform: none; visibility: visible; pointer-events: auto; transition: none;", block)
        # 跳到某一步時，標題停在常駐列下方。
        self.assertIn("scroll-margin-top: calc(var(--app-header-height, 62px) + var(--order-compact-height, 0px) + var(--space-3));", block)
        js = self.read("js/order-compact-bar.js")
        self.assertIn("const pinnedQuery = window.matchMedia('(max-width: 860px)');", js)
        self.assertIn("if (pinnedQuery.matches) { setShown(true); return; }", js)
        self.assertIn("root.style.setProperty('--order-compact-height'", js)

    def test_handle_hidden_on_mobile_order_page_only(self):
        steps = self.read("css/order-steps.css")
        self.assertRegex(steps, r"@media \(max-width: 860px\) \{\s*\.order-nav--sheet \.order-nav__handle \{ display: none; \}")
        app = self.read("css/app.css")
        # 頁首不再替收起的把手讓位；其他頁的側欄把手照舊。
        self.assertEqual(app.count(".order-nav:not(.is-pinned, .order-nav--sheet) .order-nav__handle"), 2)
        self.assertNotIn(".order-nav:not(.is-pinned) .order-nav__handle", app)

    def test_sheet_lists_overview_steps_and_other_with_separate_labels(self):
        js = self.read("js/order-step-sheet.js")
        self.assertIn('status.textContent = state === "current" ? "目前進度"', js)
        self.assertIn('here.textContent = "正在看";', js)
        self.assertIn('list(tabs().filter((tab) => !tab.classList.contains("is-main")), "其他");', js)
        self.assertIn("訂單總覽", js)
        # 鍵盤：Esc 關閉、焦點回到按鈕；上下鍵移動。
        self.assertIn('sheet.addEventListener("cancel"', js)
        self.assertIn("opener.focus({ preventScroll: true });", js)
        self.assertIn('event.key !== "ArrowDown" && event.key !== "ArrowUp"', js)
        self.assertNotIn("下一步", js)

    def test_overview_shortcut_uses_visible_trigger(self):
        js = self.read("js/order-overview.js")
        self.assertIn("triggers.find((el) => el.getClientRects().length) || triggers[0]", js)
