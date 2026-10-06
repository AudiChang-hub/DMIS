"""訂單頁步驟分頁：分頁標記、預設分頁、導回網址與錯誤時開啟的分頁。"""
import re
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from sales.models import PaymentRecord
from sales.services.order_next_actions import build_order_next_actions
from sales.services.order_steps import EXTRA_STEPS, STEP_ORDER, build_order_steps, order_step_url
from sales.tests import test_order_lifecycle as lifecycle

ALL_STEPS = STEP_ORDER + EXTRA_STEPS


def tab_markup(page, key):
    return re.search(rf'<a(?=[^>]*id="tab-{key}")[^>]*>', page).group(0)


def panel_markup(page, key):
    return re.search(rf'<section(?=[^>]*id="panel-{key}")[^>]*>', page).group(0)


class OrderDetailTabTests(TestCase):
    setUp = lifecycle.OrderLifecycleTests.setUp
    make_order = lifecycle.OrderLifecycleTests.make_order

    def detail(self, order, query=""):
        self.client.force_login(self.user)
        response = self.client.get(reverse("order_detail", args=[order.pk]) + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_every_step_is_a_tab_with_a_matching_panel(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        page = self.detail(order)

        self.assertEqual(page.count('role="tablist"'), 1)
        self.assertIn('aria-label="訂單步驟"', page)
        self.assertEqual(page.count('role="tab"'), len(ALL_STEPS))
        self.assertEqual(page.count('role="tabpanel"'), len(ALL_STEPS))
        for key in ALL_STEPS:
            tab = tab_markup(page, key)
            self.assertIn(f'aria-controls="panel-{key}"', tab)
            self.assertIn(f'href="{reverse("order_detail", args=[order.pk])}?tab={key}#step-{key}"', tab)
            self.assertIn(f'aria-labelledby="tab-{key}"', panel_markup(page, key))
        # 只有一個分頁被選取，且只有它在 Tab 鍵順序中（roving tabindex）。
        self.assertEqual(page.count('aria-selected="true"'), 1)
        self.assertEqual(page.count('role="tab" aria-controls'), len(ALL_STEPS))
        self.assertEqual(len(re.findall(r'role="tab"[^>]*tabindex="0"', page)), 1)

    def test_extra_steps_live_in_separate_group(self):
        order, _vehicle = self.make_order()
        page = self.detail(order)
        extra = page.split("order-step-bar__group--extra", 1)[1].split("</div>", 1)[0]
        self.assertIn(">其他<", extra)
        for key, title in (("subsidy", "汰舊補助"), ("closing", "取消與結案"), ("history", "處理紀錄")):
            self.assertIn(f'id="tab-{key}"', extra)
            self.assertIn(title, extra)
        self.assertNotIn('id="tab-order"', extra)

    def test_default_tab_is_current_step(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        context = build_order_steps(order, next_actions=build_order_next_actions(order))
        self.assertEqual(context["current_step"], "registration")
        page = self.detail(order)

        self.assertIn('aria-selected="true"', tab_markup(page, "registration"))
        self.assertIn("is-active", panel_markup(page, "registration"))
        self.assertIn("is-current", tab_markup(page, "registration"))
        self.assertIn('aria-selected="false"', tab_markup(page, "deposit"))
        self.assertNotIn("is-active", panel_markup(page, "deposit"))
        # 步驟狀態仍顯示在分頁上：完成打勾、待處理字樣。
        self.assertIn("已完成", page.split('id="tab-order"', 1)[1].split("</a>", 1)[0])
        self.assertIn("待處理", page.split('id="tab-deposit"', 1)[1].split("</a>", 1)[0])

    def test_requested_tab_overrides_default(self):
        order, _vehicle = self.make_order()
        page = self.detail(order, "?tab=history")
        self.assertIn('aria-selected="true"', tab_markup(page, "history"))
        self.assertIn("is-active", panel_markup(page, "history"))
        self.assertIn("處理紀錄", page.split('id="panel-history"', 1)[1])

    def test_panels_render_without_script_and_hide_only_with_tabs_class(self):
        order, _vehicle = self.make_order()
        page = self.detail(order)
        self.assertIn('document.documentElement.classList.add("has-order-tabs")', page)
        css = Path("static/css/order-steps.css").read_text(encoding="utf-8")
        self.assertIn('.has-order-tabs .order-step[role="tabpanel"]:not(.is-active) { display: none; }', css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("@media print", css)
        # 未選取的步驟內容仍在頁面上（無腳本時全部顯示）。
        self.assertIn("車輛交付", page.split('id="panel-delivery"', 1)[1])

    def test_next_action_links_target_tabs(self):
        order, _vehicle = self.make_order()
        page = self.detail(order)
        self.assertIn(f'href="{order_step_url(order.pk, "documents", "signed-documents")}"', page)
        self.assertIn('data-target-tab="documents" data-target-anchor="signed-documents"', page)

    def test_step_url_uses_tab_hash(self):
        detail = reverse("order_detail", args=[7])
        self.assertEqual(order_step_url(7, "allocation"), f"{detail}?tab=allocation#step-allocation")
        self.assertEqual(order_step_url(7, "documents", "signed-documents"), f"{detail}?tab=documents#signed-documents")
        with self.assertRaises(ValueError):
            order_step_url(7, "unknown")

    def test_form_error_redirect_reopens_its_tab(self):
        order, _vehicle = self.make_order(deposit=Decimal("5000"))
        PaymentRecord.objects.filter(order=order, system_key="deposit").update(received_amount=0)
        self.client.force_login(self.user)
        response = self.client.post(reverse("deposit_payment_update", args=[order.pk]), {
            "deposit-received_amount": "abc", "deposit-received_on": "not-a-date",
        })
        self.assertRedirects(response, order_step_url(order.pk, "deposit"), fetch_redirect_response=False)
        followed = self.client.get(response.url)
        page = followed.content.decode()
        self.assertIn('aria-selected="true"', tab_markup(page, "deposit"))
        self.assertIn("is-active", panel_markup(page, "deposit"))
        self.assertTrue(any("訂金未登記" in str(message) for message in followed.context["messages"]))

    def test_script_switches_tabs_by_keyboard_hash_and_errors(self):
        script = Path("static/js/order-workspace.js").read_text(encoding="utf-8")
        for needle in ("ArrowRight", "ArrowLeft", "Home: 0", "End:", "aria-selected", "tab.tabIndex",
                       "hashchange", "step|panel|tab", "url.hash", "'.errorlist, .field-error, [aria-invalid=\"true\"]'",
                       "order-tabpanel-reveal", "prefers-reduced-motion"):
            self.assertIn(needle, script)
        feedback = Path("static/js/form-feedback.js").read_text(encoding="utf-8")
        self.assertIn("order-tabpanel-reveal", feedback)

    def test_edit_page_links_back_to_tabs(self):
        order, _vehicle = self.make_order()
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_edit", args=[order.pk])).content.decode()
        self.assertNotIn('role="tablist"', page)
        self.assertNotIn("has-order-tabs", page)
        self.assertIn(f'href="{reverse("order_detail", args=[order.pk])}?tab=allocation#step-allocation"', page)
