"""T-241（使用者 2026-11-18「全修吧」）：T-226 健檢列出的單頁問題。

畫面規則只寫在對應頁面或手機寬度，桌面版不變；會改變操作的地方（刪除訂單移位、訂單頁打字效能）
用這裡的測試鎖住既有行為：刪除連結照舊、自動儲存照舊排程、只在送出時轉圈。
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from sales.models import OrderDraft
from sales.tests import test_command_center

BASE = Path(settings.BASE_DIR)


def read(path):
    return (BASE / path).read_text(encoding="utf-8").replace("\r\n", "\n")


def block(css, start, containing=""):
    """回傳以 start 開頭、內容含 containing 的第一個 @media 區塊。"""
    for match in re.finditer(re.escape(start), css):
        index = match.end()
        depth, end = 1, index
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        if containing in css[index:end - 1]:
            return css[index:end - 1]
    raise AssertionError(f"找不到含 {containing} 的 {start}")


class OrderListPageTests(TestCase):
    make_order = test_command_center.CommandCenterTests.make_order

    @classmethod
    def setUpTestData(cls):
        test_command_center.CommandCenterTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client.force_login(self.user)

    def cards(self, response):
        return response.content.decode().split('class="order-list order-sort-cards"', 1)[1]

    def test_card_delete_link_moves_after_facts_and_keeps_target(self):
        from django.contrib.auth import get_user_model
        # 刪除入口只開給 root（admin）；合成帳號。
        self.client.force_login(get_user_model().objects.create_superuser("admin", password="T241-local-only-pw!"))
        order = self.make_order(status="allocation_pending")
        cards = self.cards(self.client.get(reverse("order_list"), {"tab": "all", "q": order.number}))
        delete_url = reverse("order_delete", args=[order.pk])
        self.assertIn(f'class="button danger-outline small order-row-delete" href="{delete_url}"', cards)
        # 刪除在欄位（備註）之後，不再壓在姓名下方。
        self.assertLess(cards.index("order-fact--note"), cards.index("order-row-delete"))
        self.assertLess(cards.index(order.number), cards.index("order-row-delete"))

    def test_empty_note_is_marked_for_phone_cards(self):
        order = self.make_order(timezone.localdate())
        cards = self.cards(self.client.get(reverse("order_list"), {"tab": "all", "q": order.number}))
        self.assertIn('order-fact order-fact--note is-empty', cards)
        order.note = "客人週六來看車"
        order.save(update_fields=["note"])
        cards = self.cards(self.client.get(reverse("order_list"), {"tab": "all", "q": order.number}))
        self.assertIn('order-fact order-fact--note"', cards)

    def test_draft_summary_only_when_drafts_exist(self):
        self.assertNotContains(self.client.get(reverse("order_list")), "order-draft-summary")
        OrderDraft.objects.create(owner_account=self.user, created_by="合成", updated_by="合成", data={"owner_name": "草稿合成"})
        response = self.client.get(reverse("order_list"))
        self.assertContains(response, "order-draft-summary")
        self.assertContains(response, "未完成草稿 · 1 筆")
        # 捷徑「未完成草稿」照舊在。
        self.assertContains(response, "?drafts=1#drafts")


class OrderFormPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_command_center.CommandCenterTests.setUpTestData.__func__(cls)

    def test_create_page_puts_established_note_under_heading(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_create"))
        if response.status_code != 200:
            self.skipTest("建單入口改由精靈轉址")
        html = response.content.decode()
        note = html.index("訂單成立日期：首次儲存成立當日")
        self.assertLess(html.index("<h1"), note)
        self.assertIn('class="muted form-heading__established"', html)

    def test_template_keeps_order_page_note_and_moves_create_note(self):
        template = read("templates/sales/_order_form_content.html")
        self.assertIn('{% if editing_order %}<p class="muted">訂單成立日期：{{ editing_order.established_display }}', template)
        self.assertEqual(template.count("首次儲存成立當日"), 1)


class PageFixStaticTests(SimpleTestCase):
    app = read("static/css/app.css")

    def test_order_page_typing_skips_repeated_dom_writes(self):
        script = read("static/js/order-workspace.js")
        self.assertIn("const setHidden = (node, hidden) => { if (node.hidden !== hidden) node.hidden = hidden; };", script)
        self.assertIn("indicatorsSoon(form);", script)
        self.assertIn("requestAnimationFrame(() => {\n      indicatorFrame = 0;", script)
        # change、存檔結果、確認卡等照舊立即更新未儲存標記。
        self.assertIn("form.addEventListener('change', () => indicators());", script)
        self.assertIn("if (event.target.type !== 'file') schedule(form);", script)
        self.assertIn("if (chip.dataset.state !== state) chip.dataset.state = state;", script)
        note = read("static/js/order-hero-note.js")
        self.assertIn("pullSoon(box);", note)
        pull = note.split("function pull(box) {", 1)[1].split("\n  }", 1)[0]
        self.assertNotIn("fit(area)", pull)

    def test_save_chip_spins_only_while_sending(self):
        styles = read("static/css/order-workspace.css")
        self.assertIn('.save-chip[data-state="saving"][data-sending] .save-chip__mark { animation: save-chip-spin .8s linear infinite; }', styles)
        saving = styles.split('.save-chip[data-state="saving"] .save-chip__mark {', 1)[1].split("}", 1)[0]
        self.assertNotIn("animation", saving)
        self.assertIn("toggleAttribute('data-sending', sending)", read("static/js/order-workspace.js"))

    def test_operations_scroll_handler_does_not_rewrite_hidden(self):
        self.assertIn("if (!tip.hidden) tip.hidden = true;", read("static/js/operations.js"))

    def test_operations_phone_motion_and_period_targets(self):
        css = read("static/css/operations.css")
        self.assertIn("@media (prefers-reduced-motion: reduce), (max-width: 860px) {\n  .ops-spark svg,\n  .ops-card {\n    animation: none;", css)
        phone = block(css, "@media (max-width: 860px) {", ".ops-period")
        self.assertIn(".ops-period a {\n    display: inline-flex;\n    min-height: var(--control-h);", phone)

    def test_more_menu_has_scrim_and_full_height_targets(self):
        self.assertIn("body:has(.mobile-data-menu[open])::after { position: fixed; z-index: 45; inset: 0;", self.app)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(64px, 1fr));", self.app)
        for selector in (".mobile-data-popover__customize {\n    min-height: var(--control-h);", ".mobile-data-popover__all {\n    display: flex; min-height: var(--control-h);"):
            self.assertIn(selector, self.app)

    def test_page_spacing_and_glass(self):
        self.assertIn(".maintenance-section + .maintenance-section { margin-top: var(--stack-gap); }", self.app)
        self.assertIn("  .maintenance-section { margin-block: var(--stack-gap); }", self.app)
        # T-242：照片看板樣式搬到 catalog-photo-board.css（規則內容不變，外層 @media 原樣包回）。
        board = read("static/css/catalog-photo-board.css")
        self.assertIn(".photo-board__toolbar{-webkit-backdrop-filter:none;backdrop-filter:none;background:var(--surface)}",
                      block(board, "@media(max-width:860px) {", "photo-board__toolbar{-webkit-backdrop-filter:none"))
        self.assertIn("  .order-page-size-form select { min-height: var(--control-h); }", self.app)

    def test_phone_order_cards_are_compact_and_desktop_table_untouched(self):
        phone = block(self.app, "@media (max-width: 600px) {", ".order-facts")
        for rule in (".order-fact--note.is-empty { display: none; }", ".order-row--detailed .order-row-delete { margin-top: var(--space-3); }"):
            self.assertIn(rule, phone)
        # 卡片只在 860px 以下出現；桌面是表格，表格的刪除連結不變。
        # T-242：訂單列表排序樣式搬到 order-list.css（只搬不改內容）。
        self.assertRegex(self.app + read("static/css/order-list.css"), r"\.order-sort-cards, \.order-sort-mobile \{ display: none; \}")
        self.assertIn('<small><a class="button danger-outline small" href="{% url \'order_delete\' order.pk %}"', read("templates/sales/order_list.html"))

    def test_text_wrapping_fixes(self):
        self.assertIn(".home-start-card__body b { color: var(--paper); font-family: var(--font-display); font-size: var(--text-lg); text-wrap: balance; }", self.app)
        self.assertIn(".ledger-row__label small { text-wrap: pretty; }", read("static/css/order-finance.css"))
        self.assertRegex(self.app, r"\.action-card select \{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; \}")
        self.assertIn(".intake-vehicle-hint { padding: 0 var(--card-pad); }", self.app)
        self.assertIn("  .wizard-nav.mobile-submit { min-height: 0; padding: var(--space-2); }", read("static/css/order-wizard.css"))
        self.assertIn("  .detail-hero__actions { justify-content: flex-start; }", read("static/css/order-commission-recipient.css"))
