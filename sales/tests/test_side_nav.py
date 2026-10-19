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

    def test_vehicle_model_list_has_brand_and_model_index(self):
        from sales.models import VehicleModel
        VehicleModel.objects.create(brand="SUZUKI", name="目錄測試車", model_number="IX125", model_year=2026,
                                    energy_type=VehicleModel.EnergyType.GAS, displacement_cc=125)
        page = self.client.get(reverse("vehicle_model_list"))
        content = page.content.decode()
        self.assertIn('data-side-nav-key="vehicle-models"', content)
        self.assertIn("js/vehicle-model-list-nav.js", content)
        # 目錄連結對到列表裡的品牌段落與機種列，搜尋字串含型號與年式。
        self.assertIn('href="#vm-brand-1"', content)
        self.assertIn('id="vm-brand-1"', content)
        self.assertIn('href="#vm-family-1-1"', content)
        self.assertIn('id="vm-family-1-1"', content)
        self.assertRegex(content, r'data-model-index-family data-search="[^"]*目錄測試車[^"]*IX125[^"]*2026')

    def test_vehicle_model_list_hides_index_when_empty(self):
        page = self.client.get(reverse("vehicle_model_list") + "?q=不存在的車")
        self.assertNotContains(page, 'data-side-nav-key="vehicle-models"')

    def test_operations_inventory_section_matches_workload_style(self):
        # 1.86.14：庫存概況是頁尾段落，和即時工作量同樣用 dashboard-section，目錄標示由 side-nav.js 的頁底規則處理。
        content = self.client.get(reverse("operations_report")).content.decode()
        self.assertIn('<section class="dashboard-section" data-side-nav-section="庫存概況">', content)
        self.assertIn('<section class="dashboard-section" data-side-nav-section="即時工作量">', content)
