from pathlib import Path

from django.conf import settings
from django.core.paginator import Paginator
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase


class SharedPaginationUiTests(SimpleTestCase):
    paginated_templates = (
        "accessory_product_list.html",
        "customer_detail.html",
        "customer_list.html",
        "dashboard.html",
        "incentive_rule_list.html",
        "inventory_list.html",
        "legacy_import_detail.html",
        "operations_report.html",
        "order_list.html",
        "reconciliation_list.html",
        "sales_source_list.html",
        "sales_source_simple_list.html",
        "settlement_cost_rule_list.html",
    )

    def setUp(self):
        self.request_factory = RequestFactory()

    def render_pagination(self, request, page_obj, **kwargs):
        arguments = " ".join(
            f'{key}="{value}"' for key, value in kwargs.items()
        )
        template = Template(
            "{% load pagination_tags %}"
            f"{{% pagination page_obj {arguments} %}}"
        )
        return template.render(Context({"request": request, "page_obj": page_obj}))

    def test_controls_include_first_last_and_direct_page_jump(self):
        request = self.request_factory.get(
            "/orders/",
            {"q": "王小明", "status": "completed", "page": "2", "edit": "99"},
        )
        page_obj = Paginator(range(50), 10).page(2)

        html = self.render_pagination(
            request,
            page_obj,
            aria_label="訂單分頁",
            anchor="results",
            drop="edit",
        )

        self.assertIn("第一頁", html)
        self.assertIn("上一頁", html)
        self.assertIn("下一頁", html)
        self.assertIn("最後一頁", html)
        self.assertIn("第 2／5 頁", html)
        self.assertIn('type="number"', html)
        self.assertIn('min="1"', html)
        self.assertIn('max="5"', html)
        self.assertIn('value="2"', html)
        self.assertIn('action="/orders/#results"', html)
        self.assertIn(
            'href="?q=%E7%8E%8B%E5%B0%8F%E6%98%8E&amp;status=completed&amp;page=1#results"',
            html,
        )
        self.assertIn('name="q" value="王小明"', html)
        self.assertIn('name="status" value="completed"', html)
        self.assertNotIn('name="edit"', html)
        self.assertNotIn('type="hidden" name="page"', html)

    def test_edge_page_actions_remain_visible_but_disabled(self):
        request = self.request_factory.get("/orders/", {"page": "1"})
        html = self.render_pagination(
            request, Paginator(range(20), 10).page(1), aria_label="訂單分頁"
        )

        self.assertIn(
            'aria-disabled="true">第一頁</span>', html
        )
        self.assertIn(
            'aria-disabled="true">上一頁</span>', html
        )
        self.assertIn('href="?page=2">下一頁</a>', html)
        self.assertIn('href="?page=2">最後一頁</a>', html)

    def test_every_paginated_screen_uses_the_shared_component(self):
        template_root = Path(settings.BASE_DIR) / "templates" / "sales"
        for template_name in self.paginated_templates:
            with self.subTest(template=template_name):
                content = (template_root / template_name).read_text(encoding="utf-8")
                self.assertIn("{% pagination ", content)
                self.assertIn("pagination_tags", content)
