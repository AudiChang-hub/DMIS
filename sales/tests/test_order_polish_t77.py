"""1022 投影片三（使用者 2026-10-22）：T-77 內部折扣不寫核准；T-78 步驟不用綠勾；T-79 附件卡片不貼邊。"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from sales.models import SalesOrder
from sales.tests import test_order_steps as steps


class OrderPolishTests(TestCase):
    setUp = steps.OrderStepTests.setUp
    make_order = steps.OrderStepTests.make_order
    registered_v2 = steps.OrderStepTests.registered_v2

    def test_internal_discount_has_no_approval_wording(self):
        order, _vehicle = self.registered_v2()
        SalesOrder.objects.filter(pk=order.pk).update(approved_discount_amount=Decimal("1000"), discount_status="approved")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        card = page.split('class="finance-strip__card finance-discount"', 1)[1].split("</section>", 1)[0]
        self.assertIn(">內部折扣</h2>", card)
        self.assertNotIn("核准", card)
        self.assertNotIn("status-pill", card)
        script = (Path(settings.BASE_DIR) / "static/js/discount-preview.js").read_text(encoding="utf-8")
        self.assertNotIn("核准", script)

    def test_pending_discount_still_flagged(self):
        order, _vehicle = self.registered_v2()
        SalesOrder.objects.filter(pk=order.pk).update(discount_status="pending")
        self.client.force_login(self.user)
        page = self.client.get(reverse("order_detail", args=[order.pk])).content.decode()
        card = page.split('class="finance-strip__card finance-discount"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<span class="status-pill">待確認</span>', card)

    def test_done_steps_show_numbers_not_checkmarks(self):
        html = render_to_string("sales/_order_step_marker.html", {"step": {"state": "done", "number": 4, "key": "allocation"}})
        self.assertEqual(html.strip(), "4")
        css = (Path(settings.BASE_DIR) / "static/css/order-steps.css").read_text(encoding="utf-8")
        self.assertNotIn(".order-step-tab.is-done .order-step-tab__marker", css)
        self.assertNotIn(".order-step.is-done .order-step__marker", css)
        bar = render_to_string("sales/_order_wizard_bar.html", {"wizard": {"steps": [
            {"key": "vehicle", "number": 1, "label": "車款與車價", "state": "done", "reachable": True},
            {"key": "owner", "number": 2, "label": "車主與證件", "state": "current", "reachable": True},
        ]}})
        self.assertNotIn("✓", bar)
        self.assertIn('<span class="wizard-bar__number">1</span>', bar)
        self.assertIn("已完成", bar)

    def test_attachment_cards_pad_their_contents(self):
        css = (Path(settings.BASE_DIR) / "static/css/app.css").read_text(encoding="utf-8")
        self.assertIn(".section-block.order-files>:not(.section-title){margin-inline:var(--card-pad)}", css)
        self.assertIn(".section-block.order-files{padding-bottom:var(--card-pad)}", css)
