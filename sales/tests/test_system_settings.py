"""1.73.0：admin 可隨時調整優先配車月數；管理者工具依用途分組。"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from sales.models import SystemSettingChange, allocation_priority_age_months, allocation_priority_cutoff
from sales.services import system_settings
from sales.tests import test_order_lifecycle as lifecycle


class AllocationRuleSettingTests(TestCase):
    setUp_lifecycle = lifecycle.OrderLifecycleTests.setUp

    def setUp(self):
        self.setUp_lifecycle()
        self.admin = get_user_model().objects.create_superuser("admin", password="Local-rule-984!")
        self.addCleanup(system_settings._forget)
        system_settings._forget()

    def test_admin_changes_months_and_rule_applies_immediately(self):
        from datetime import date
        self.assertEqual(allocation_priority_age_months(), 3)
        self.assertEqual(allocation_priority_cutoff(date(2026, 10, 13)), "2026/06")
        self.client.force_login(self.admin)
        page = self.client.get(reverse("allocation_rule_settings"))
        self.assertContains(page, "目前規則")
        self.assertContains(page, "出廠超過 <strong>3 個月</strong>", html=False)
        response = self.client.post(reverse("allocation_rule_settings"), {"months": "1"})
        self.assertRedirects(response, reverse("allocation_rule_settings"))
        self.assertEqual(allocation_priority_age_months(), 1)
        self.assertEqual(allocation_priority_cutoff(date(2026, 10, 13)), "2026/08")
        change = SystemSettingChange.objects.get()
        self.assertEqual((change.before, change.after, change.actor), ("3", "1", "admin"))
        # 範圍外的值不接受。
        self.client.post(reverse("allocation_rule_settings"), {"months": "30"})
        self.assertEqual(allocation_priority_age_months(), 1)

    def test_only_admin_can_open_rule_settings(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("allocation_rule_settings")).status_code, 403)

    def test_management_tools_are_grouped(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("data_maintenance")).content.decode()
        for title in ("帳號與系統規則", "公告、說明文字與列印", "報表設計", "資料匯入與系統檢查"):
            self.assertIn(f'<h3 class="maintenance-subgroup__title">{title}</h3>', page)
            self.assertIn(f"<h3>{title}</h3>", page)  # 上方選單同樣分組
        self.assertIn(reverse("allocation_rule_settings"), page)
        self.assertIn("目前 3 個月", page)

    def test_inventory_rule_notice_uses_current_months_and_links_admin(self):
        from sales.services.system_settings import set_allocation_priority_age_months
        set_allocation_priority_age_months(2, "admin")
        self.client.force_login(self.admin)
        page = self.client.get(reverse("inventory_list")).content.decode()
        self.assertIn("出廠年月超過 2 個月", page)
        self.assertIn(reverse("allocation_rule_settings"), page)


class SiteCopyTabsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("admin", password="Local-copy-984!")
        self.client.force_login(self.admin)

    def test_texts_split_into_area_tabs_grouped_by_page(self):
        page = self.client.get(reverse("site_copy_manage"))
        tabs = {tab["key"]: tab for tab in page.context["tabs"]}
        self.assertEqual(list(tabs), ["order", "print", "vehicle", "dealer", "finance", "home", "system", "common"])
        self.assertEqual(sum(tab["count"] for tab in tabs.values()), len(__import__("sales.services.site_copy", fromlist=["catalog"]).catalog()))
        self.assertEqual(page.context["area"], "order")
        self.assertContains(page, 'aria-label="說明文字分類"')
        self.assertContains(page, 'class="copy-page-heading"')
        self.assertIn("訂單填寫", [item["page"] for item in page.context["area_pages"]])
        printed = self.client.get(reverse("site_copy_manage"), {"area": "print"})
        self.assertTrue(all(row["area"] == "print" for row in printed.context["page_obj"]))
        # 搜尋時自動跳到有結果的頁籤，頁籤台數跟著搜尋條件。
        searched = self.client.get(reverse("site_copy_manage"), {"q": "牌險", "scope": "print"})
        self.assertEqual(searched.context["area"], "print")
        self.assertContains(searched, "print.contract.plate_description")
