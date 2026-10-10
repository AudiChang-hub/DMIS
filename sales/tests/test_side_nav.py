"""1.67.0：共用側邊把手導覽（第一版：建立訂單精靈、Excel 匯入批次、營運總表、資料維護區）。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import Store


class SideNavTests(TestCase):
    def setUp(self):
        Store.objects.create(name="總店", code="MAIN")
        self.root = get_user_model().objects.create_superuser("admin", password="Local-side-nav-984!")
        self.client.force_login(self.root)
        from sales.tests.profit_helpers import unlock_profit
        unlock_profit(self, self.root)

    def test_data_maintenance_has_section_index(self):
        page = self.client.get(reverse("data_maintenance"))
        self.assertContains(page, 'data-side-nav-key="data"')
        for label in ("日常資料", "費率與規則", "工具與管理"):
            self.assertContains(page, f'data-side-nav-section="{label}"')
        self.assertContains(page, "js/side-nav.js")

    def test_operations_report_has_section_index(self):
        page = self.client.get(reverse("operations_report"))
        self.assertContains(page, 'data-side-nav-key="operations"')
        self.assertContains(page, 'data-side-nav-section="收款風險與退款"')

    def test_order_wizard_steps_live_in_side_nav(self):
        page = self.client.get(reverse("order_start"))
        content = page.content.decode()
        self.assertIn('data-side-nav-key="order-wizard"', content)
        nav_start = content.index('data-side-nav-key="order-wizard"')
        self.assertGreater(content.index("wizard-bar__step"), nav_start, "精靈步驟放在側邊列裡")
