"""補助方案的入口（使用者 2026-10-22 T-97）。

使用者照建單提示「在『資料維護區 › 補助方案』新增或停用方案」找不到地方：資料維護區頁面有卡片，
但頁首「資料維護區」選單與手機快捷沒有這一項。改成：提示變成直接連到補助方案頁的連結（另開分頁），
沒有補助方案權限的人不顯示；頁首選單、手機快捷、所在區塊標示都補上補助方案。
"""
from django.urls import reverse

from sales.access.models import ScreenAccessGrant, UserAccessState
from sales.access.registry import SCREENS
from sales.services.mobile_quick_links import MOBILE_QUICK_LINK_DEFINITIONS
from sales.tests import test_subsidy_programs as programs

OLD_HINT = "新增或停用方案；預設金額可留空"


class SubsidyProgramEntryTests(programs.SubsidyProgramTests.__bases__[0]):
    setUpTestData = classmethod(programs.correction_tests.CompletedOrderCorrectionTests.setUpTestData.__func__)
    setUp = programs.SubsidyProgramTests.setUp
    order = programs.SubsidyProgramTests.order

    def edit_page(self):
        response = self.client.get(reverse("order_create"))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_order_form_links_to_subsidy_programs(self):
        html = self.edit_page()
        picker = html.split("data-subsidy-picker", 1)[1].split("</fieldset>", 1)[0]
        self.assertNotIn(OLD_HINT, picker)
        self.assertRegex(picker, r'<a class="subsidy-program-picker__manage" href="%s" target="_blank" rel="noopener">'
                         % reverse("subsidy_program_list"))
        self.assertIn("另開分頁", picker)

    def test_header_menu_lists_subsidy_programs(self):
        html = self.edit_page()
        rules = html.split('id="data-menu-rules"', 1)[1].split("</section>", 1)[0]
        self.assertIn(f'href="{reverse("subsidy_program_list")}"', rules)
        self.assertLess(rules.index("分期公司與方案"), rules.index("<strong>補助方案</strong>"))

    def test_subsidy_program_page_counts_as_data_maintenance(self):
        response = self.client.get(reverse("subsidy_program_list"))
        self.assertTrue(response.context["is_data_maintenance_section"])
        self.assertIn("subsidy_program_list", {item["route"] for item in MOBILE_QUICK_LINK_DEFINITIONS})
        card = self.client.get(reverse("data_maintenance")).content.decode()
        self.assertIn(f'href="{reverse("subsidy_program_list")}"', card)

    def test_people_without_subsidy_program_access_see_no_link(self):
        UserAccessState.objects.create(user=self.user, configured=True)
        ScreenAccessGrant.objects.bulk_create(
            ScreenAccessGrant(user=self.user, screen_key=screen.key, view=True, operate=screen.operate, export=screen.export)
            for screen in SCREENS if screen.key != "subsidy_programs")
        html = self.edit_page()
        self.assertIn("data-subsidy-picker", html)
        self.assertNotIn(f'href="{reverse("subsidy_program_list")}"', html)
        self.assertNotIn(OLD_HINT, html)
